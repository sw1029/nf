import sqlite3
from pathlib import Path

import pytest

from modules.nf_orchestrator.services.job_service import JobServiceImpl
from modules.nf_orchestrator.services.project_service import ProjectServiceImpl
from modules.nf_orchestrator.storage import db as storage_db
from modules.nf_orchestrator.storage.repos import job_repo
from modules.nf_shared.protocol.dtos import JobEventLevel, JobStatus, JobType


@pytest.mark.unit
def test_project_service_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    service = ProjectServiceImpl(db_path)

    created = service.create_project("Project One", {"mode": "dev"})
    assert created.project_id
    assert created.name == "Project One"

    listed = service.list_projects()
    assert len(listed) == 1

    fetched = service.get_project(created.project_id)
    assert fetched is not None
    assert fetched.project_id == created.project_id

    updated = service.update_project(created.project_id, "Project Two", {"mode": "prod"})
    assert updated is not None
    assert updated.name == "Project Two"
    assert updated.settings["mode"] == "prod"

    assert service.delete_project(created.project_id) is True
    assert service.get_project(created.project_id) is None


@pytest.mark.unit
def test_job_service_events(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    service = JobServiceImpl(db_path)

    job = service.submit("project-1", JobType.INDEX_FTS, {}, {})
    events = service.list_events(job.job_id)
    assert events

    last_seq = events[-1][0]
    service.cancel(job.job_id)

    follow_up = service.list_events(job.job_id, after_seq=last_seq)
    assert any(event.level == JobEventLevel.WARN for _, event in follow_up)


@pytest.mark.unit
def test_job_service_payload_roundtrip_and_retry_eligible_states(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    service = JobServiceImpl(db_path)

    inputs = {"scope": "doc-123"}
    params = {"consistency": {"verification_loop": {"enabled": False}}}
    job = service.submit("project-1", JobType.INDEX_FTS, inputs, params)

    loaded_inputs, loaded_params = service.get_payloads(job.job_id)
    assert loaded_inputs == inputs
    assert loaded_params == params

    with storage_db.connect(db_path) as conn:
        updated = job_repo.update_job_status(conn, job.job_id, JobStatus.FAILED)
    assert updated is not None
    assert updated.status is JobStatus.FAILED
    assert updated.status in {JobStatus.FAILED, JobStatus.CANCELED}


@pytest.mark.unit
def test_job_success_status_clears_stale_error_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    service = JobServiceImpl(db_path)
    job = service.submit("project-1", JobType.INDEX_FTS, {"scope": "global"}, {})

    with storage_db.connect(db_path) as conn:
        job_repo.set_job_error(conn, job.job_id, error_code="INTERNAL_ERROR", error_message="database is locked")
        updated = job_repo.update_job_status(conn, job.job_id, JobStatus.SUCCEEDED)

    assert updated is not None
    assert updated.status is JobStatus.SUCCEEDED
    assert updated.error_code is None
    assert updated.error_message is None


@pytest.mark.unit
def test_db_initializer_drops_redundant_verdict_evidence_index(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS verdict_evidence_link (
                vid TEXT NOT NULL,
                eid TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (vid, eid, role)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_verdict_evidence_vid ON verdict_evidence_link(vid)")
        conn.commit()

    with storage_db.connect(db_path) as conn:
        rows = conn.execute("PRAGMA index_list('verdict_evidence_link')").fetchall()
        indexes = {str(row["name"]) for row in rows}
    assert "idx_verdict_evidence_vid" not in indexes


@pytest.mark.unit
def test_db_initializer_sets_user_version_and_backfills_missing_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                queued_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                inputs_json TEXT,
                params_json TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()

    with storage_db.connect(db_path) as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        job_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}

    assert version >= 1
    assert {"priority", "lease_owner", "lease_expires_at", "attempts", "max_attempts", "error_code"} <= job_columns


@pytest.mark.unit
def test_db_connect_applies_extended_busy_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    with storage_db.connect(db_path) as conn:
        busy_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
    assert busy_timeout == 30000
