from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo
from modules.nf_shared.protocol.dtos import DocumentType


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
        title="Doc",
        doc_type=DocumentType.EPISODE,
        path=str(text_path),
        head_snapshot_id=snapshot_id,
        checksum=checksum,
        version=1,
    )


@pytest.mark.unit
def test_consistency_forwards_entity_time_filters_to_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "시로는 14세였다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    captured_filters: list[dict] = []
    vector_called = {"value": False}

    def fake_fts_search(_conn, req):  # noqa: ANN001
        filters = req.get("filters")
        if isinstance(filters, dict):
            captured_filters.append(filters)
        return []

    def fail_vector_search(_req):  # noqa: ANN001
        vector_called["value"] = True
        raise AssertionError("vector_search should not be called when metadata filters are set")

    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", fake_fts_search)
    monkeypatch.setattr("modules.nf_consistency.engine.vector_search", fail_vector_search)

    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "filters": {
                "entity_id": "entity-siro",
                "time_key": "ep:1/scene:1/rel:현재",
                "timeline_idx": 7,
            },
        }
    )

    assert verdicts
    assert captured_filters
    assert any(
        item.get("entity_id") == "entity-siro"
        and item.get("time_key") == "ep:1/scene:1/rel:현재"
        and int(item.get("timeline_idx")) == 7
        for item in captured_filters
    )
    assert vector_called["value"] is False
