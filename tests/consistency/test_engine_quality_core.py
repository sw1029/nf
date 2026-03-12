from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

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

def test_segment_text_keeps_abbreviation_token_in_same_sentence() -> None:
    text = "Dr. Kim arrived. Next scene."
    segments = consistency_engine._segment_text(text)
    assert [segment for _, _, segment in segments] == [
        "Dr. Kim arrived.",
        "Next scene.",
    ]

def test_segment_text_keeps_ordinal_token_in_same_sentence() -> None:
    text = "He ranked 1st. in class. Final note."
    segments = consistency_engine._segment_text(text)
    assert [segment for _, _, segment in segments] == [
        "He ranked 1st. in class.",
        "Final note.",
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


def test_filter_results_without_slot_anchor_drops_irrelevant_affiliation_hits() -> None:
    results = [
        _result_row("doc-a", 0.1, "chunk-a"),
        {
            "source": "fts",
            "score": 0.2,
            "evidence": {
                "doc_id": "doc-b",
                "snapshot_id": "snap-ref",
                "chunk_id": "chunk-b",
                "section_path": "body",
                "tag_path": "",
                "snippet_text": "사도련 명가 쪽 인물이었다.",
                "span_start": 0,
                "span_end": 14,
                "fts_score": 0.2,
                "match_type": "EXACT",
                "confirmed": False,
            },
        },
    ]
    results[0]["evidence"]["snippet_text"] = "완전히 무관한 장면이다."

    filtered, removed = consistency_engine._filter_results_without_slot_anchor(
        results,
        slots={"affiliation": "사도련"},
    )

    assert removed == 1
    assert len(filtered) == 1
    assert filtered[0]["evidence"]["doc_id"] == "doc-b"


def test_filter_results_without_slot_anchor_keeps_extractable_title_affiliation_hit() -> None:
    pipeline = consistency_engine.ExtractionPipeline(
        profile={"mode": "rule_only", "allow_generic_narrative_affiliation": True},
        mappings=[],
        gateway=None,
    )
    results = [
        {
            "source": "fts",
            "score": 0.2,
            "evidence": {
                "doc_id": "doc-b",
                "snapshot_id": "snap-ref",
                "chunk_id": "chunk-b",
                "section_path": "body",
                "tag_path": "",
                "snippet_text": "그녀는 라인시스의 제1황녀였다.",
                "span_start": 0,
                "span_end": 17,
                "fts_score": 0.2,
                "match_type": "EXACT",
                "confirmed": False,
            },
        },
    ]

    filtered, removed = consistency_engine._filter_results_without_slot_anchor(
        results,
        slots={"affiliation": "라인시스 제국"},
        pipeline=pipeline,
    )

    assert removed == 0
    assert len(filtered) == 1
    assert filtered[0]["evidence"]["doc_id"] == "doc-b"


def test_filter_results_without_slot_anchor_limits_rescue_to_affiliation() -> None:
    class _CountingPipeline:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, _snippet_text: str) -> SimpleNamespace:
            self.calls += 1
            return SimpleNamespace(slots={"relation": "스승"})

    pipeline = _CountingPipeline()
    results = [
        {
            "source": "fts",
            "score": 0.2,
            "evidence": {
                "doc_id": "doc-b",
                "snapshot_id": "snap-ref",
                "chunk_id": "chunk-b",
                "section_path": "body",
                "tag_path": "",
                "snippet_text": "두 사람은 사형제였다.",
                "span_start": 0,
                "span_end": 11,
                "fts_score": 0.2,
                "match_type": "EXACT",
                "confirmed": False,
            },
        },
    ]

    filtered, removed = consistency_engine._filter_results_without_slot_anchor(
        results,
        slots={"relation": "스승"},
        pipeline=pipeline,
    )

    assert removed == 1
    assert filtered == []
    assert pipeline.calls == 0


def test_filter_results_without_slot_anchor_reuses_snippet_slot_cache() -> None:
    class _CountingPipeline:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, _snippet_text: str) -> SimpleNamespace:
            self.calls += 1
            return SimpleNamespace(slots={"affiliation": "라인시스"})

    pipeline = _CountingPipeline()
    results = [
        {
            "source": "fts",
            "score": 0.2,
            "evidence": {
                "doc_id": "doc-b",
                "snapshot_id": "snap-ref",
                "chunk_id": "chunk-b",
                "section_path": "body",
                "tag_path": "",
                "snippet_text": "그녀는 라인시스의 제1황녀였다.",
                "span_start": 0,
                "span_end": 17,
                "fts_score": 0.2,
                "match_type": "EXACT",
                "confirmed": False,
            },
        },
    ]
    extracted_slots_cache: dict[tuple[str, int, int], dict[str, object]] = {}
    cache_metrics: dict[str, int] = {}
    rescue_metrics: dict[str, int] = {}

    filtered, removed = consistency_engine._filter_results_without_slot_anchor(
        results,
        slots={"affiliation": "라인시스 제국"},
        pipeline=pipeline,
        extracted_slots_cache=extracted_slots_cache,
        cache_metrics=cache_metrics,
        rescue_metrics=rescue_metrics,
    )
    filtered_second, removed_second = consistency_engine._filter_results_without_slot_anchor(
        results,
        slots={"affiliation": "라인시스 제국"},
        pipeline=pipeline,
        extracted_slots_cache=extracted_slots_cache,
        cache_metrics=cache_metrics,
        rescue_metrics=rescue_metrics,
    )

    assert removed == 0
    assert len(filtered) == 1
    assert removed_second == 0
    assert len(filtered_second) == 1
    assert pipeline.calls == 1
    assert cache_metrics == {"hit_count": 1, "miss_count": 1}
    assert rescue_metrics == {"attempt_count": 2, "ok_count": 2}


def test_judge_with_fact_index_marks_entity_unresolved_without_global_facts() -> None:
    fact_index = {
        ("job", consistency_engine._FACT_ALL_KEY): [
            _FakeFact(evidence_eid="ev-entity-a", value="마법사", entity_id="entity-a"),
        ]
    }
    verdict, links, meta = consistency_engine._judge_with_fact_index(
        {"job": "마법사"},
        fact_index,
        target_entity_id=None,
    )
    assert verdict is None
    assert links == []
    assert meta["entity_unresolved"] is True

def test_judge_with_fact_index_skips_entity_bound_slot_when_entity_unresolved() -> None:
    fact_index = {
        ("job", consistency_engine._FACT_ALL_KEY): [
            _FakeFact(evidence_eid="ev-global", value="마법사", entity_id=None),
            _FakeFact(evidence_eid="ev-entity-a", value="기사", entity_id="entity-a"),
        ],
        ("job", None): [
            _FakeFact(evidence_eid="ev-global", value="마법사", entity_id=None),
        ],
    }
    verdict, links, meta = consistency_engine._judge_with_fact_index(
        {"job": "마법사"},
        fact_index,
        target_entity_id=None,
    )
    assert verdict is None
    assert meta["entity_unresolved"] is True
    assert links == []

def test_judge_with_fact_index_keeps_global_compare_for_time_when_entity_unresolved() -> None:
    fact_index = {
        ("time", consistency_engine._FACT_ALL_KEY): [
            _FakeFact(evidence_eid="ev-global", value="2026년 3월 2일", entity_id=None),
        ],
        ("time", None): [
            _FakeFact(evidence_eid="ev-global", value="2026년 3월 2일", entity_id=None),
        ],
    }
    verdict, links, meta = consistency_engine._judge_with_fact_index(
        {"time": "2026년 3월 2일"},
        fact_index,
        target_entity_id=None,
    )
    assert verdict is Verdict.OK
    assert meta["entity_unresolved"] is False
    assert links == [("ev-global", consistency_engine.EvidenceRole.SUPPORT)]

def test_judge_with_fact_index_marks_numeric_conflict_as_uncomparable() -> None:
    fact_index = {
        ("job", "entity-a"): [
            _FakeFact(evidence_eid="ev-entity-a", value="13기 마법사", entity_id="entity-a"),
        ],
    }
    verdict, links, meta = consistency_engine._judge_with_fact_index(
        {"job": "12기 마법사"},
        fact_index,
        target_entity_id="entity-a",
    )
    assert verdict is None
    assert links == []
    assert meta["saw_uncomparable"] is True
    assert meta["numeric_conflict"] is True

def test_judge_with_fact_index_prefers_entity_scoped_facts_over_global_for_entity_bound_slot() -> None:
    fact_index = {
        ("job", "entity-a"): [
            _FakeFact(evidence_eid="ev-entity-a", value="마법사", entity_id="entity-a"),
        ],
        ("job", None): [
            _FakeFact(evidence_eid="ev-global", value="검사", entity_id=None),
        ],
    }
    verdict, links, meta = consistency_engine._judge_with_fact_index(
        {"job": "마법사"},
        fact_index,
        target_entity_id="entity-a",
    )
    assert verdict is Verdict.OK
    assert meta["conflicting"] is False
    assert links == [("ev-entity-a", consistency_engine.EvidenceRole.SUPPORT)]

def test_judge_with_fact_index_ignores_descriptive_support_phrase_for_relation() -> None:
    fact_index = {
        ("relation", consistency_engine._FACT_ALL_KEY): [
            _FakeFact(evidence_eid="ev-support", value="주인공을 돕는 조력자"),
            _FakeFact(evidence_eid="ev-violate", value="배신자"),
        ],
    }
    verdict, links, meta = consistency_engine._judge_with_fact_index(
        {"relation": "조력자"},
        fact_index,
        target_entity_id=None,
    )
    assert verdict is Verdict.VIOLATE
    assert meta["conflicting"] is False
    assert links == [("ev-violate", consistency_engine.EvidenceRole.CONTRADICT)]

def test_compare_slot_allows_affiliation_prefix_entity_match() -> None:
    judged = consistency_engine._compare_slot("affiliation", "라인시스 제국", "라인시스")
    assert judged is Verdict.OK

def test_compare_slot_does_not_allow_contains_ok_for_job() -> None:
    judged = consistency_engine._compare_slot("job", "흑마법사", "마법사")
    assert judged is not Verdict.OK

def test_overlaps_any_span_rejects_tiny_overlap_under_ratio_threshold() -> None:
    has_overlap = consistency_engine._overlaps_any_span(
        0,
        20,
        [(19, 25)],
        min_overlap_chars=3,
        min_overlap_ratio=0.20,
    )
    assert has_overlap is False

def test_overlaps_any_span_accepts_sufficient_overlap() -> None:
    has_overlap = consistency_engine._overlaps_any_span(
        0,
        20,
        [(2, 12)],
        min_overlap_chars=3,
        min_overlap_ratio=0.20,
    )
    assert has_overlap is True

def test_promote_confirmed_evidence_rejects_tiny_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        consistency_engine,
        "_load_user_tag_spans",
        lambda *_args, **_kwargs: [(19, 25)],
    )
    monkeypatch.setattr(
        consistency_engine,
        "_load_approved_evidence_spans",
        lambda *_args, **_kwargs: [],
    )
    results = [
        {
            "evidence": {
                "doc_id": "doc-1",
                "snapshot_id": "snap-1",
                "span_start": 0,
                "span_end": 20,
                "confirmed": False,
            }
        }
    ]
    rejected_count = consistency_engine._promote_confirmed_evidence(
        None,
        project_id="project-1",
        results=results,
        user_tag_span_cache={},
        approved_evidence_span_cache={},
    )
    assert rejected_count == 1
    assert bool(results[0]["evidence"]["confirmed"]) is False

def test_promote_confirmed_evidence_accepts_sufficient_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        consistency_engine,
        "_load_user_tag_spans",
        lambda *_args, **_kwargs: [(2, 12)],
    )
    monkeypatch.setattr(
        consistency_engine,
        "_load_approved_evidence_spans",
        lambda *_args, **_kwargs: [],
    )
    results = [
        {
            "evidence": {
                "doc_id": "doc-1",
                "snapshot_id": "snap-1",
                "span_start": 0,
                "span_end": 20,
                "confirmed": False,
            }
        }
    ]
    rejected_count = consistency_engine._promote_confirmed_evidence(
        None,
        project_id="project-1",
        results=results,
        user_tag_span_cache={},
        approved_evidence_span_cache={},
    )
    assert rejected_count == 0
    assert bool(results[0]["evidence"]["confirmed"]) is True

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
    assert reliability <= 0.45
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
