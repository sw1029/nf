import sqlite3
from pathlib import Path

import pytest

from modules.nf_orchestrator.services.job_service import JobServiceImpl
from modules.nf_orchestrator.services.project_service import ProjectServiceImpl
from modules.nf_orchestrator.storage import db as storage_db
from modules.nf_shared.protocol.dtos import JobEventLevel, JobType


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
