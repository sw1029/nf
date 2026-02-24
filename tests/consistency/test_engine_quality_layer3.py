from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from modules.nf_consistency import engine as consistency_engine
from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo, evidence_repo
from modules.nf_shared.config import Settings
from modules.nf_shared.protocol.dtos import DocumentType, ReliabilityBreakdown, Verdict

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

def _result_row(doc_id: str, score: float, chunk_id: str) -> dict:
    return {
        "source": "fts",
        "score": score,
        "evidence": {
            "doc_id": doc_id,
            "snapshot_id": "snap-ref",
            "chunk_id": chunk_id,
            "section_path": "body",
            "tag_path": "",
            "snippet_text": "snippet",
            "span_start": 0,
            "span_end": 8,
            "fts_score": score,
            "match_type": "EXACT",
            "confirmed": False,
        },
    }

def _single_claim(*_args, **_kwargs):  # noqa: ANN001
    return [
        {
            "segment_start": 0,
            "segment_end": 10,
            "segment_text": "claim age",
            "claim_start": 0,
            "claim_end": 8,
            "claim_text": "claim age",
            "slots": {"age": 14},
            "slot_key": "age",
            "slot_confidence": 1.0,
        }
    ]

def _single_confirmed_fts_result(_conn, _req):  # noqa: ANN001
    return [
        {
            "source": "fts",
            "score": 0.1,
            "evidence": {
                "doc_id": "doc-ref",
                "snapshot_id": "snap-ref",
                "chunk_id": "chunk-ref",
                "section_path": "body",
                "tag_path": "",
                "snippet_text": "reference",
                "span_start": 0,
                "span_end": 8,
                "fts_score": 0.1,
                "match_type": "EXACT",
                "confirmed": True,
            },
        },
        {
            "source": "fts",
            "score": 0.12,
            "evidence": {
                "doc_id": "doc-ref-2",
                "snapshot_id": "snap-ref",
                "chunk_id": "chunk-ref-2",
                "section_path": "body",
                "tag_path": "",
                "snippet_text": "reference2",
                "span_start": 0,
                "span_end": 8,
                "fts_score": 0.12,
                "match_type": "EXACT",
                "confirmed": True,
            },
        },
    ]

def _single_one_confirmed_fts_result(_conn, _req):  # noqa: ANN001
    return [
        {
            "source": "fts",
            "score": 0.1,
            "evidence": {
                "doc_id": "doc-ref",
                "snapshot_id": "snap-ref",
                "chunk_id": "chunk-ref",
                "section_path": "body",
                "tag_path": "",
                "snippet_text": "reference",
                "span_start": 0,
                "span_end": 8,
                "fts_score": 0.1,
                "match_type": "EXACT",
                "confirmed": True,
            },
        }
    ]

@dataclass(frozen=True)
class _FakeFact:
    evidence_eid: str
    value: object
    entity_id: str | None = None

class _FixedGateway:
    def __init__(self, score: float) -> None:
        self._score = score

    def nli_score(self, _bundle):  # noqa: ANN001
        return self._score

    def extract_slots_local(self, _bundle):  # noqa: ANN001
        return []

    def extract_slots_remote(self, _bundle):  # noqa: ANN001
        return []

def test_layer3_promotion_keeps_default_behavior_when_opt_in_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "placeholder"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr("modules.nf_consistency.engine._extract_claims", _single_claim)
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", _single_confirmed_fts_result)
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=True, vector_index_mode="DISABLED"),
    )
    monkeypatch.setattr("modules.nf_consistency.engine.select_model", lambda purpose="consistency": _FixedGateway(0.99))

    engine = ConsistencyEngineImpl(db_path=db_path)
    stats: dict[str, object] = {}
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "stats": stats,
            "layer3_verdict_promotion": False,
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert int(stats.get("layer3_promoted_ok_count", 0)) == 0

def test_layer3_promotion_requires_at_least_two_confirmed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "placeholder"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr("modules.nf_consistency.engine._extract_claims", _single_claim)
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", _single_one_confirmed_fts_result)
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=True, vector_index_mode="DISABLED"),
    )
    monkeypatch.setattr("modules.nf_consistency.engine.select_model", lambda purpose="consistency": _FixedGateway(0.99))

    engine = ConsistencyEngineImpl(db_path=db_path)
    stats: dict[str, object] = {}
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "stats": stats,
            "layer3_verdict_promotion": True,
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert int(stats.get("layer3_promoted_ok_count", 0)) == 0

def test_layer3_promotion_upgrades_unknown_to_ok_when_opted_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "placeholder"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr("modules.nf_consistency.engine._extract_claims", _single_claim)
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", _single_confirmed_fts_result)
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=True, vector_index_mode="DISABLED"),
    )
    monkeypatch.setattr("modules.nf_consistency.engine.select_model", lambda purpose="consistency": _FixedGateway(0.99))

    engine = ConsistencyEngineImpl(db_path=db_path)
    stats: dict[str, object] = {}
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "stats": stats,
            "layer3_verdict_promotion": True,
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.OK
    assert int(stats.get("layer3_promoted_ok_count", 0)) == 1

def test_layer3_promotion_does_not_upgrade_when_model_score_is_low(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "placeholder"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr("modules.nf_consistency.engine._extract_claims", _single_claim)
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", _single_confirmed_fts_result)
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=True, vector_index_mode="DISABLED"),
    )
    monkeypatch.setattr("modules.nf_consistency.engine.select_model", lambda purpose="consistency": _FixedGateway(0.2))

    engine = ConsistencyEngineImpl(db_path=db_path)
    stats: dict[str, object] = {}
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "stats": stats,
            "layer3_verdict_promotion": True,
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert int(stats.get("layer3_promoted_ok_count", 0)) == 0
