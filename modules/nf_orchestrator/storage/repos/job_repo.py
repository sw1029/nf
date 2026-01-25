from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from modules.nf_shared.protocol.dtos import Job, JobEvent, JobEventLevel, JobStatus, JobType


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def create_job(
    conn,
    project_id: str,
    job_type: JobType,
    inputs: dict[str, Any],
    params: dict[str, Any],
) -> Job:
    job_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO jobs (
            job_id, project_id, type, status, created_at, queued_at,
            inputs_json, params_json, cancel_requested
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
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


def update_job_status(conn, job_id: str, status: JobStatus) -> Job | None:
    ts = _now_ts()
    conn.execute(
        "UPDATE jobs SET status = ?, finished_at = ? WHERE job_id = ?",
        (status.value, ts, job_id),
    )
    conn.commit()
    return get_job(conn, job_id)


def cancel_job(conn, job_id: str) -> Job | None:
    ts = _now_ts()
    conn.execute(
        "UPDATE jobs SET status = ?, finished_at = ?, cancel_requested = 1 WHERE job_id = ?",
        (JobStatus.CANCELED.value, ts, job_id),
    )
    conn.commit()
    return get_job(conn, job_id)


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
