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

def test_segment_text_splits_on_sentence_boundaries() -> None:
    text = "A. B!\nC?"
    segments = consistency_engine._segment_text(text)
    assert [segment for _, _, segment in segments] == ["A.", "B!", "C?"]

def test_segment_text_handles_decimal_ellipsis_and_quote_tail() -> None:
    text = "Price is 3.14... \"Really?\" He nodded\u2026\nNext line."
    segments = consistency_engine._segment_text(text)
    assert [segment for _, _, segment in segments] == [
        "Price is 3.14...",
        "\"Really?\"",
        "He nodded\u2026",
        "Next line.",
    ]

def test_resolve_graph_mode_keeps_legacy_compatibility() -> None:
    assert consistency_engine._resolve_graph_mode({}, legacy_enabled=False) == "off"
    assert consistency_engine._resolve_graph_mode({}, legacy_enabled=True) == "manual"
    assert consistency_engine._resolve_graph_mode({"graph_mode": "auto"}, legacy_enabled=True) == "auto"

def test_judge_with_fact_index_downgrades_conflicting_evidence_to_unknown() -> None:
    fact_index = {
        ("age", consistency_engine._FACT_ALL_KEY): [
            _FakeFact(evidence_eid="ev-ok", value=10),
            _FakeFact(evidence_eid="ev-violate", value=11),
        ]
    }
    verdict, links, meta = consistency_engine._judge_with_fact_index(
        {"age": 10},
        fact_index,
        target_entity_id=None,
    )
    assert verdict is Verdict.UNKNOWN
    assert meta["conflicting"] is True
    assert len(links) == 2

def test_judge_with_fact_index_excludes_self_fact_evidence_ids() -> None:
    fact_index = {
        ("age", consistency_engine._FACT_ALL_KEY): [
            _FakeFact(evidence_eid="ev-self", value=10),
            _FakeFact(evidence_eid="ev-setting", value=11),
        ]
    }
    verdict, links, meta = consistency_engine._judge_with_fact_index(
        {"age": 10},
        fact_index,
        target_entity_id=None,
        excluded_fact_eids={"ev-self"},
    )
    assert verdict is Verdict.VIOLATE
    assert meta["conflicting"] is False
    assert links == [("ev-setting", consistency_engine.EvidenceRole.CONTRADICT)]

def test_compute_reliability_keeps_unknown_nonzero_when_evidence_exists() -> None:
    breakdown = ReliabilityBreakdown(
        fts_strength=0.12,
        evidence_count=2,
        confirmed_evidence=1,
        model_score=0.3,
    )
    reliability, evidence_conf, decision_conf = consistency_engine._compute_reliability(
        verdict=Verdict.UNKNOWN,
        breakdown=breakdown,
    )
    assert reliability > 0.0
    assert evidence_conf > 0.0
    assert decision_conf > 0.0

def test_resolve_verifier_triage_and_loop_options_defaults() -> None:
    verifier_mode, promote_th, contradict_th, max_chars = consistency_engine._resolve_verifier_options({})
    assert verifier_mode == "off"
    assert promote_th == pytest.approx(0.95)
    assert contradict_th == pytest.approx(0.70)
    assert max_chars == 220

    triage_mode, anomaly_th, max_segments = consistency_engine._resolve_triage_options({})
    assert triage_mode == "off"
    assert anomaly_th == pytest.approx(0.65)
    assert max_segments == 8

    loop_enabled, loop_rounds, loop_timeout_ms = consistency_engine._resolve_verification_loop_options({})
    assert loop_enabled is False
    assert loop_rounds == 2
    assert loop_timeout_ms == 250
