from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import job_repo, project_repo
from modules.nf_shared.config import Settings
from modules.nf_shared.protocol.dtos import JobType
from modules.nf_workers import runner


@pytest.mark.unit
def test_run_worker_emits_memory_pressure_pause_reason_with_cooldown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    with db.connect(db_path) as conn:
        project = project_repo.create_project(conn, "p", {})
        job = job_repo.create_job(conn, project.project_id, JobType.CONSISTENCY, {}, {})

    pressure_states = iter([True, True, False])

    def fake_memory_pressure(_max_ram_mb: int) -> bool:
        try:
            return next(pressure_states)
        except StopIteration:
            return False

    monkeypatch.setattr(runner, "_memory_pressure", fake_memory_pressure)
    monkeypatch.setattr(runner, "_get_process_rss_mb", lambda: 4096.0)
    monkeypatch.setattr(
        runner,
        "load_config",
        lambda: Settings(max_ram_mb=1024, max_heavy_jobs=1),
    )
    monkeypatch.setattr(runner, "_run_job", lambda _job_type, _ctx: None)

    runner.run_worker(db_path=db_path, poll_interval=0.01, max_jobs=1)

    with db.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT level, payload_json
            FROM job_events
            WHERE job_id = ?
            ORDER BY seq ASC
            """,
            (job.job_id,),
        ).fetchall()

    warn_payloads = []
    for row in rows:
        if row["level"] != "WARN":
            continue
        raw = row["payload_json"]
        if not isinstance(raw, str) or not raw:
            continue
        payload = json.loads(raw)
        if payload.get("reason_code") == "PAUSED_DUE_TO_MEMORY_PRESSURE":
            warn_payloads.append(payload)

    assert len(warn_payloads) == 1
    payload = warn_payloads[0]
    assert payload["reason_code"] == "PAUSED_DUE_TO_MEMORY_PRESSURE"
    assert int(payload["max_ram_mb"]) == 1024
    assert float(payload["rss_mb"]) >= 4096.0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error_message",),
    (
        ("database is locked",),
        ("database schema is locked: main",),
        ("database table is locked",),
    ),
)
def test_run_worker_retries_transient_sqlite_lock_during_leasing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_message: str,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    with db.connect(db_path) as conn:
        project = project_repo.create_project(conn, "p", {})
        job = job_repo.create_job(conn, project.project_id, JobType.INDEX_FTS, {"scope": "global"}, {})

    real_connect = runner.db.connect
    attempts = {"count": 0}

    def flaky_connect(path=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise sqlite3.OperationalError(error_message)
        return real_connect(path)

    monkeypatch.setattr(runner, "_memory_pressure", lambda _max_ram_mb: False)
    monkeypatch.setattr(runner, "_run_job", lambda _job_type, _ctx: None)
    monkeypatch.setattr(runner.db, "connect", flaky_connect)

    runner.run_worker(db_path=db_path, poll_interval=0.01, max_jobs=1)

    with db.connect(db_path) as conn:
        loaded = job_repo.get_job(conn, job.job_id)

    assert loaded is not None
    assert loaded.status.name == "SUCCEEDED"
    assert attempts["count"] >= 2


@pytest.mark.unit
def test_transient_sqlite_lock_helper_rejects_non_lock_error() -> None:
    assert runner._is_transient_sqlite_lock_error(sqlite3.OperationalError("disk I/O error")) is False


@pytest.mark.unit
def test_worker_context_heartbeat_extends_job_lease(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    with db.connect(db_path) as conn:
        project = project_repo.create_project(conn, "p", {})
        job = job_repo.create_job(conn, project.project_id, JobType.INDEX_FTS, {"scope": "global"}, {})
        job_repo.update_job_status(conn, job.job_id, runner.JobStatus.RUNNING)
        job_repo.extend_lease(conn, job.job_id, lease_seconds=5)
        before = conn.execute("select lease_expires_at from jobs where job_id = ?", (job.job_id,)).fetchone()["lease_expires_at"]

    ctx = runner.WorkerContext(
        job_id=job.job_id,
        project_id=project.project_id,
        payload={"scope": "global"},
        params={},
        db_path=db_path,
        lease_seconds=30,
    )

    renewed = ctx.heartbeat(force=True)

    with db.connect(db_path) as conn:
        after = conn.execute("select lease_expires_at from jobs where job_id = ?", (job.job_id,)).fetchone()["lease_expires_at"]

    assert renewed is True
    assert isinstance(before, str)
    assert isinstance(after, str)
    assert after > before
