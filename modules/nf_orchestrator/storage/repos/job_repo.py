from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from modules.nf_shared.protocol.dtos import Job, JobEvent, JobEventLevel, JobStatus, JobType


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_seconds(ts: str, seconds: int) -> str:
    parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (parsed + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_job(row: Any) -> Job:
    return Job(
        job_id=row["job_id"],
        type=JobType(row["type"]),
        project_id=row["project_id"],
        status=JobStatus(row["status"]),
        created_at=row["created_at"],
        queued_at=row["queued_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _build_in_clause(values: Iterable[str]) -> tuple[str, list[str]]:
    values = list(values)
    placeholders = ",".join(["?"] * len(values))
    return f"({placeholders})", values


def create_job(
    conn,
    project_id: str,
    job_type: JobType,
    inputs: dict[str, Any],
    params: dict[str, Any],
    *,
    priority: int = 100,
) -> Job:
    job_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO jobs (
            job_id, project_id, type, status, created_at, queued_at,
            inputs_json, params_json, cancel_requested, priority
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            job_id,
            project_id,
            job_type.value,
            JobStatus.QUEUED.value,
            ts,
            ts,
            json.dumps(inputs or {}),
            json.dumps(params or {}),
            priority,
        ),
    )
    conn.commit()
    return Job(
        job_id=job_id,
        type=job_type,
        project_id=project_id,
        status=JobStatus.QUEUED,
        created_at=ts,
        queued_at=ts,
    )


def get_job(conn, job_id: str) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def get_job_payloads(conn, job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    row = conn.execute(
        "SELECT inputs_json, params_json FROM jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        return {}, {}
    inputs = json.loads(row["inputs_json"]) if row["inputs_json"] else {}
    params = json.loads(row["params_json"]) if row["params_json"] else {}
    return inputs, params


def update_job_status(conn, job_id: str, status: JobStatus) -> Job | None:
    ts = _now_ts()
    if status is JobStatus.RUNNING:
        conn.execute(
            "UPDATE jobs SET status = ?, started_at = ? WHERE job_id = ?",
            (status.value, ts, job_id),
        )
    elif status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED}:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, finished_at = ?, lease_owner = NULL, lease_expires_at = NULL
            WHERE job_id = ?
            """,
            (status.value, ts, job_id),
        )
    else:
        conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status.value, job_id))
    conn.commit()
    return get_job(conn, job_id)


def cancel_job(conn, job_id: str) -> Job | None:
    ts = _now_ts()
    conn.execute(
        """
        UPDATE jobs
        SET status = ?, finished_at = ?, cancel_requested = 1
        WHERE job_id = ?
        """,
        (JobStatus.CANCELED.value, ts, job_id),
    )
    conn.commit()
    return get_job(conn, job_id)


def is_cancel_requested(conn, job_id: str) -> bool:
    row = conn.execute("SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return False
    return bool(row["cancel_requested"])


def add_job_event(
    conn,
    job_id: str,
    level: JobEventLevel,
    message: str,
    *,
    progress: float | None = None,
    metrics: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, JobEvent]:
    event_id = str(uuid.uuid4())
    ts = _now_ts()
    cur = conn.execute(
        """
        INSERT INTO job_events (
            event_id, job_id, ts, level, message, progress, metrics_json, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            job_id,
            ts,
            level.value,
            message,
            progress,
            json.dumps(metrics) if metrics is not None else None,
            json.dumps(payload) if payload is not None else None,
        ),
    )
    conn.commit()
    event = JobEvent(
        event_id=event_id,
        job_id=job_id,
        ts=ts,
        level=level,
        message=message,
        progress=progress,
        metrics=metrics,
        payload=payload,
    )
    return int(cur.lastrowid), event


def list_job_events(conn, job_id: str, *, after_seq: int = 0) -> list[tuple[int, JobEvent]]:
    rows = conn.execute(
        """
        SELECT * FROM job_events
        WHERE job_id = ? AND seq > ?
        ORDER BY seq ASC
        """,
        (job_id, after_seq),
    ).fetchall()
    events: list[tuple[int, JobEvent]] = []
    for row in rows:
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else None
        payload = json.loads(row["payload_json"]) if row["payload_json"] else None
        event = JobEvent(
            event_id=row["event_id"],
            job_id=row["job_id"],
            ts=row["ts"],
            level=JobEventLevel(row["level"]),
            message=row["message"],
            progress=row["progress"],
            metrics=metrics,
            payload=payload,
        )
        events.append((row["seq"], event))
    return events


def requeue_expired_jobs(conn, now_ts: str) -> int:
    cur = conn.execute(
        """
        UPDATE jobs
        SET status = ?, lease_owner = NULL, lease_expires_at = NULL
        WHERE status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
        """,
        (JobStatus.QUEUED.value, JobStatus.RUNNING.value, now_ts),
    )
    conn.commit()
    return cur.rowcount


def count_running_jobs(conn, job_types: list[JobType]) -> int:
    if not job_types:
        return 0
    clause, params = _build_in_clause([job.value for job in job_types])
    row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM jobs WHERE status = ? AND type IN {clause}",
        [JobStatus.RUNNING.value, *params],
    ).fetchone()
    if row is None:
        return 0
    return int(row["cnt"])


def list_queued_jobs(conn, job_types: list[JobType], *, limit: int = 20) -> list[Job]:
    if not job_types or limit <= 0:
        return []
    clause, params = _build_in_clause([job.value for job in job_types])
    rows = conn.execute(
        f"""
        SELECT *
        FROM jobs
        WHERE status = ? AND type IN {clause}
        ORDER BY priority DESC, created_at ASC
        LIMIT ?
        """,
        [JobStatus.QUEUED.value, *params, int(limit)],
    ).fetchall()
    return [_row_to_job(row) for row in rows]


def lease_next_job(
    conn,
    *,
    worker_id: str,
    lease_seconds: int,
    allow_job_types: list[JobType] | None = None,
    deny_job_types: list[JobType] | None = None,
) -> tuple[Job, dict[str, Any], dict[str, Any]] | None:
    now = _now_ts()
    requeue_expired_jobs(conn, now)

    query = "SELECT job_id FROM jobs WHERE status = ?"
    params: list[Any] = [JobStatus.QUEUED.value]
    if allow_job_types:
        clause, values = _build_in_clause([job.value for job in allow_job_types])
        query += f" AND type IN {clause}"
        params.extend(values)
    if deny_job_types:
        clause, values = _build_in_clause([job.value for job in deny_job_types])
        query += f" AND type NOT IN {clause}"
        params.extend(values)
    query += " ORDER BY priority DESC, created_at ASC LIMIT 1"

    row = conn.execute(query, params).fetchone()
    if row is None:
        return None

    job_id = row["job_id"]
    lease_expires_at = _add_seconds(now, lease_seconds)
    cur = conn.execute(
        """
        UPDATE jobs
        SET status = ?, started_at = ?, lease_owner = ?, lease_expires_at = ?
        WHERE job_id = ? AND status = ?
        """,
        (
            JobStatus.RUNNING.value,
            now,
            worker_id,
            lease_expires_at,
            job_id,
            JobStatus.QUEUED.value,
        ),
    )
    if cur.rowcount == 0:
        conn.commit()
        return None
    conn.commit()

    job = get_job(conn, job_id)
    if job is None:
        return None
    inputs, params = get_job_payloads(conn, job_id)
    return job, inputs, params


def extend_lease(conn, job_id: str, *, lease_seconds: int) -> None:
    now = _now_ts()
    lease_expires_at = _add_seconds(now, lease_seconds)
    conn.execute(
        "UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?",
        (lease_expires_at, job_id),
    )
    conn.commit()


def set_job_error(conn, job_id: str, *, error_code: str, error_message: str) -> None:
    conn.execute(
        "UPDATE jobs SET error_code = ?, error_message = ? WHERE job_id = ?",
        (error_code, error_message, job_id),
    )
    conn.commit()
