from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo
from modules.nf_shared.protocol.dtos import DocumentType
from modules.nf_workers import runner


def _seed_document(
    conn,
    *,
    tmp_path: Path,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    text: str,
) -> None:
    text_path = tmp_path / f"{doc_id}_{snapshot_id}.txt"
    text_path.write_text(text, encoding="utf-8")
    checksum = docstore.checksum_text(text)
    document_repo.create_snapshot(
        conn,
        snapshot_id=snapshot_id,
        project_id=project_id,
        doc_id=doc_id,
        version=1,
        path=str(text_path),
        checksum=checksum,
    )
    document_repo.create_document(
        conn,
        doc_id=doc_id,
        project_id=project_id,
        title="EPISODE 1",
        doc_type=DocumentType.EPISODE,
        path=str(text_path),
        head_snapshot_id=snapshot_id,
        checksum=checksum,
        version=1,
    )


def _last_event_payload(conn, job_id: str) -> dict:
    row = conn.execute(
        """
        SELECT payload_json
        FROM job_events
        WHERE job_id = ?
        ORDER BY seq DESC
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    assert row is not None
    raw = row["payload_json"]
    assert isinstance(raw, str) and raw
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.unit
def test_ingest_uses_incremental_skip_when_snapshot_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "이름: 시로\n나이: 14세\n직업: 노 클래스\n재능: 재능 없음"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    job_id_1 = f"job-{uuid.uuid4()}"
    ctx_1 = runner.WorkerContext(
        job_id=job_id_1,
        project_id=project_id,
        payload={"doc_id": doc_id},
        params={},
        db_path=db_path,
    )
    runner._handle_ingest(ctx_1)

    with db.connect(db_path) as conn:
        payload_1 = _last_event_payload(conn, job_id_1)
        count_1 = conn.execute("SELECT COUNT(*) AS cnt FROM schema_version WHERE project_id = ?", (project_id,)).fetchone()
        assert payload_1["incremental"] is True
        assert payload_1["docs_skipped"] == 0
        assert int(count_1["cnt"]) == 1

    job_id_2 = f"job-{uuid.uuid4()}"
    ctx_2 = runner.WorkerContext(
        job_id=job_id_2,
        project_id=project_id,
        payload={"doc_id": doc_id},
        params={},
        db_path=db_path,
    )
    runner._handle_ingest(ctx_2)

    with db.connect(db_path) as conn:
        payload_2 = _last_event_payload(conn, job_id_2)
        count_2 = conn.execute("SELECT COUNT(*) AS cnt FROM schema_version WHERE project_id = ?", (project_id,)).fetchone()
        assert payload_2["incremental"] is True
        assert payload_2["docs_skipped"] == 1
        assert int(payload_2["claims_processed"]) == 0
        assert int(count_2["cnt"]) == 1
