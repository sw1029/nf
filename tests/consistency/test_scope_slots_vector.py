from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import evidence_repo, schema_repo
from tests.helpers.consistency_seed import seed_document as _seed_document, seed_schema_fact as _seed_schema_fact
from modules.nf_shared.protocol.dtos import (
    DocumentType,
    EvidenceMatchType,
    FactSource,
    FactStatus,
    SchemaFact,
    SchemaLayer,
    Verdict,
)

def test_consistency_default_doc_scope_limits_vector_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    input_doc_id = "doc-episode-20"
    input_snapshot_id = "snap-episode-20"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=input_doc_id,
            snapshot_id=input_snapshot_id,
            text="hero line",
            doc_type=DocumentType.EPISODE,
            title="Episode 20",
            metadata={"episode_no": 20},
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-episode-25",
            snapshot_id="snap-episode-25",
            text="near episode",
            doc_type=DocumentType.EPISODE,
            title="Episode 25",
            metadata={"episode_no": 25},
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-episode-99",
            snapshot_id="snap-episode-99",
            text="far episode",
            doc_type=DocumentType.EPISODE,
            title="Episode 99",
            metadata={"episode_no": 99},
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-setting",
            snapshot_id="snap-setting",
            text="world setting",
            doc_type=DocumentType.SETTING,
            title="Setting",
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-char",
            snapshot_id="snap-char",
            text="character profile",
            doc_type=DocumentType.CHAR,
            title="Character",
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-plot",
            snapshot_id="snap-plot",
            text="plot timeline",
            doc_type=DocumentType.PLOT,
            title="Plot",
        )

    monkeypatch.setattr("modules.nf_consistency.engine.select_model", lambda purpose: None)
    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda _text, pipeline=None, stats=None: [
            {
                "claim_text": "hero line",
                "segment_text": "hero line",
                "claim_start": 0,
                "claim_end": 9,
                "slots": {"relation": "hero"},
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", lambda _conn, _req: [])

    captured_filters: list[dict[str, object]] = []

    def fake_vector_search(req):  # noqa: ANN001
        filters = req.get("filters")
        if isinstance(filters, dict):
            captured_filters.append(dict(filters))
        return []

    monkeypatch.setattr("modules.nf_consistency.engine.vector_search", fake_vector_search)

    engine = ConsistencyEngineImpl(db_path=db_path)
    engine.run(
        {
            "project_id": project_id,
            "input_doc_id": input_doc_id,
            "input_snapshot_id": input_snapshot_id,
            "range": {"start": 0, "end": 9},
        }
    )

    assert captured_filters
    doc_ids = captured_filters[0].get("doc_ids")
    assert isinstance(doc_ids, list)
    assert input_doc_id in doc_ids
    assert "doc-episode-25" in doc_ids
    assert "doc-setting" in doc_ids
    assert "doc-char" in doc_ids
    assert "doc-plot" in doc_ids
    assert "doc-episode-99" not in doc_ids

def test_consistency_vector_fallback_preserves_requested_doc_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    input_doc_id = "doc-body"
    input_snapshot_id = "snap-body"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=input_doc_id,
            snapshot_id=input_snapshot_id,
            text="hero line",
        )

    monkeypatch.setattr("modules.nf_consistency.engine.select_model", lambda purpose: None)
    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda _text, pipeline=None, stats=None: [
            {
                "claim_text": "hero line",
                "segment_text": "hero line",
                "claim_start": 0,
                "claim_end": 9,
                "slots": {"relation": "hero"},
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", lambda _conn, _req: [])

    captured_filters: list[dict[str, object]] = []

    def fake_vector_search(req):  # noqa: ANN001
        filters = req.get("filters")
        if isinstance(filters, dict):
            captured_filters.append(dict(filters))
        return []

    monkeypatch.setattr("modules.nf_consistency.engine.vector_search", fake_vector_search)

    engine = ConsistencyEngineImpl(db_path=db_path)
    engine.run(
        {
            "project_id": project_id,
            "input_doc_id": input_doc_id,
            "input_snapshot_id": input_snapshot_id,
            "range": {"start": 0, "end": 9},
            "filters": {"doc_ids": ["doc-custom"]},
        }
    )

    assert captured_filters
    assert captured_filters[0].get("doc_ids") == ["doc-custom"]
