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

def test_consistency_two_stage_retrieval_can_surface_graph_boosted_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "시로는 10살이다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    def fake_fts_search(_conn, req):  # noqa: ANN001
        filters = req.get("filters") or {}
        doc_ids = filters.get("doc_ids")
        if isinstance(doc_ids, list) and "doc-boost" in doc_ids:
            return [_result_row("doc-boost", 0.01, "chunk-boost")]
        rows = []
        for idx in range(1, 12):
            rows.append(_result_row(f"doc-{idx}", 0.05 + (idx * 0.1), f"chunk-{idx}"))
        return rows

    def fake_graph_expand(_conn, **_kwargs):  # noqa: ANN001
        return ["doc-boost"], {
            "applied": True,
            "reason": "",
            "seed_docs": ["doc-boost"],
            "expanded_docs": ["doc-boost"],
            "doc_distances": {"doc-boost": 1},
            "seed_doc_count": 1,
            "expanded_doc_count": 1,
            "candidate_doc_count": 1,
            "max_hops": 1,
            "doc_cap": 200,
        }

    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", fake_fts_search)
    monkeypatch.setattr("modules.nf_consistency.engine.expand_candidate_docs_with_graph", fake_graph_expand)

    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "graph_mode": "manual",
        }
    )

    assert verdicts
    assert any(item.verdict is Verdict.UNKNOWN for item in verdicts)
    assert any(item.reliability_overall > 0.0 for item in verdicts)

    with db.connect(db_path) as conn:
        evidences = evidence_repo.list_evidence(conn, project_id, doc_id="doc-boost")
    assert evidences, "graph-boosted candidate should survive rerank and final top-k"
