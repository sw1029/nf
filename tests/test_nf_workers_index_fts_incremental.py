from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo, schema_repo
from modules.nf_shared.protocol.dtos import DocumentType, FactSource
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
def test_index_fts_uses_fts_meta_incremental_skip(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "나이 11살\n장소: 서울"

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
        payload={"scope": doc_id},
        params={},
        db_path=db_path,
    )
    runner._handle_index_fts(ctx_1)

    with db.connect(db_path) as conn:
        payload_1 = _last_event_payload(conn, job_id_1)
        assert payload_1["incremental"] is True
        assert payload_1["docs_indexed"] == 1
        assert payload_1["docs_skipped"] == 0

    job_id_2 = f"job-{uuid.uuid4()}"
    ctx_2 = runner.WorkerContext(
        job_id=job_id_2,
        project_id=project_id,
        payload={"scope": doc_id},
        params={},
        db_path=db_path,
    )
    runner._handle_index_fts(ctx_2)

    with db.connect(db_path) as conn:
        payload_2 = _last_event_payload(conn, job_id_2)
        assert payload_2["incremental"] is True
        assert payload_2["docs_indexed"] == 0
        assert payload_2["docs_skipped"] == 1

        schema_repo.create_tag_assignment(
            conn,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            span_start=0,
            span_end=3,
            tag_path="설정/인물/주인공",
            user_value="x",
            created_by=FactSource.USER,
        )

    job_id_3 = f"job-{uuid.uuid4()}"
    ctx_3 = runner.WorkerContext(
        job_id=job_id_3,
        project_id=project_id,
        payload={"scope": doc_id},
        params={},
        db_path=db_path,
    )
    runner._handle_index_fts(ctx_3)

    with db.connect(db_path) as conn:
        payload_3 = _last_event_payload(conn, job_id_3)
        assert payload_3["incremental"] is True
        assert payload_3["docs_indexed"] == 1
        assert payload_3["docs_skipped"] == 0

