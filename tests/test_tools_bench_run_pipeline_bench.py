from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("run_pipeline_bench")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


@pytest.mark.unit
def test_build_consistency_params_applies_level_policy() -> None:
    mod = _import_module()

    quick_params, quick_level = mod._build_consistency_params(
        consistency_level="quick",
        evidence_link_policy="full",
        evidence_link_cap=20,
    )
    assert quick_level == "quick"
    assert quick_params["consistency"]["graph_mode"] == "off"
    assert quick_params["consistency"]["layer3_verdict_promotion"] is False
    assert quick_params["consistency"]["metadata_grouping_enabled"] is False
    assert quick_params["consistency"]["verifier"]["mode"] == "off"
    assert quick_params["consistency"]["triage"]["mode"] == "off"
    assert quick_params["consistency"]["verification_loop"]["enabled"] is False

    deep_params, deep_level = mod._build_consistency_params(
        consistency_level="deep",
        evidence_link_policy="cap",
        evidence_link_cap=10,
    )
    assert deep_level == "deep"
    assert deep_params["consistency"]["graph_mode"] == "auto"
    assert deep_params["consistency"]["layer3_verdict_promotion"] is True
    assert deep_params["consistency"]["metadata_grouping_enabled"] is True
    assert deep_params["consistency"]["verifier"]["mode"] == "off"
    assert deep_params["consistency"]["triage"]["mode"] == "embedding_anomaly"
    assert deep_params["consistency"]["verification_loop"]["enabled"] is False

    strict_params, strict_level = mod._build_consistency_params(
        consistency_level="strict",
        evidence_link_policy="contradict_only",
        evidence_link_cap=5,
    )
    assert strict_level == "strict"
    assert strict_params["consistency"]["graph_mode"] == "auto"
    assert strict_params["consistency"]["layer3_verdict_promotion"] is True
    assert strict_params["consistency"]["metadata_grouping_enabled"] is True
    assert strict_params["consistency"]["verifier"]["mode"] == "conservative_nli"
    assert strict_params["consistency"]["triage"]["mode"] == "embedding_anomaly"
    assert strict_params["consistency"]["verification_loop"]["enabled"] is True
    assert int(strict_params["consistency"]["verification_loop"]["max_rounds"]) == 2
    assert int(strict_params["consistency"]["verification_loop"]["round_timeout_ms"]) == 800

    override_params, _ = mod._build_consistency_params(
        consistency_level="quick",
        evidence_link_policy="full",
        evidence_link_cap=20,
        graph_mode_override="auto",
        metadata_grouping_override=True,
        verifier_mode_override="conservative_nli",
        triage_mode_override="embedding_anomaly",
        triage_anomaly_threshold_override=0.72,
        triage_max_segments_override=5,
        verification_loop_enabled_override=True,
        verification_loop_max_rounds_override=4,
        verification_loop_timeout_ms_override=900,
    )
    assert override_params["consistency"]["graph_mode"] == "auto"
    assert override_params["consistency"]["metadata_grouping_enabled"] is True
    assert override_params["consistency"]["verifier"]["mode"] == "conservative_nli"
    assert override_params["consistency"]["triage"]["mode"] == "embedding_anomaly"
    assert float(override_params["consistency"]["triage"]["anomaly_threshold"]) == pytest.approx(0.72)
    assert int(override_params["consistency"]["triage"]["max_segments_per_run"]) == 5
    assert override_params["consistency"]["verification_loop"]["enabled"] is True
    assert int(override_params["consistency"]["verification_loop"]["max_rounds"]) == 4
    assert int(override_params["consistency"]["verification_loop"]["round_timeout_ms"]) == 900

    graph_off_index_params = mod._build_index_fts_params(graph_enabled=False, index_grouping_enabled=False)
    assert graph_off_index_params == {}

    graph_on_index_params = mod._build_index_fts_params(graph_enabled=True, index_grouping_enabled=False)
    assert graph_on_index_params["grouping"]["entity_mentions"] is True
    assert graph_on_index_params["grouping"]["time_anchors"] is True
    assert graph_on_index_params["grouping"]["graph_extract"] is True

    grouping_only_index_params = mod._build_index_fts_params(graph_enabled=False, index_grouping_enabled=True)
    assert grouping_only_index_params["grouping"]["entity_mentions"] is True
    assert grouping_only_index_params["grouping"]["time_anchors"] is True


@pytest.mark.unit
def test_extract_index_fts_graph_runtime_reads_grouping_payload() -> None:
    mod = _import_module()
    runtime = mod._extract_index_fts_graph_runtime(
        [
            (
                1,
                {
                    "message": "fts indexed",
                    "payload": {
                        "graph_extract_enabled": True,
                        "entity_mentions_created": 12,
                        "time_anchors_created": 34,
                        "timeline_events_created": 5,
                        "graph_index": {"nodes_entity": 3, "nodes_time": 4, "nodes_timeline": 5},
                        "graph": {"enabled": True, "warning": None},
                    },
                },
            )
        ]
    )
    assert runtime["graph_extract_enabled"] is True
    assert int(runtime["entity_mentions_created"]) == 12
    assert int(runtime["time_anchors_created"]) == 34
    assert int(runtime["timeline_events_created"]) == 5
    assert runtime["graph_index"]["nodes_entity"] == 3


@pytest.mark.unit
def test_pick_retrieval_queries_prioritizes_graph_signal_when_graph_enabled() -> None:
    mod = _import_module()
    records = [
        {"content": "아무 신호 없는 일반 문장이다."},
        {"content": "평범한 서술이 이어진다. 그날 성문이 열렸다. 이후 전개가 계속된다."},
        {"content": "또 다른 일반 문장이다."},
    ]

    queries = mod._pick_retrieval_queries(records, limit=2, seed=1, graph_enabled=True)

    assert len(queries) == 2
    assert "그날" in queries[0]


@pytest.mark.unit
def test_classify_graph_query_signal_types_detects_entity_timeline_and_time_anchor() -> None:
    mod = _import_module()

    signal_types = mod._classify_graph_query_signal_types("리아 황녀는 연회 다음 날 귀환했다.")

    assert signal_types == ["entity_alias", "timeline_signal", "time_anchor"]


@pytest.mark.unit
def test_pick_retrieval_query_candidates_exposes_signal_metadata() -> None:
    mod = _import_module()
    records = [
        {"content": "아무 신호 없는 일반 문장이다.", "source_id": "SRC-a", "episode_no": 1},
        {"content": "리아 황녀는 연회 다음 날 귀환했다.", "source_id": "SRC-b", "episode_no": 2},
        {"content": "그날 성문이 열렸다.", "source_id": "SRC-c", "episode_no": 3},
    ]

    candidates = mod._pick_retrieval_query_candidates(records, limit=2, seed=1, graph_enabled=True)

    assert len(candidates) == 2
    assert candidates[0]["signal_types"]
    assert candidates[0]["source_id"].startswith("SRC-")
    assert isinstance(candidates[0]["episode_no"], int)
    assert any("entity_alias" in item["signal_types"] for item in candidates)


@pytest.mark.unit
def test_pick_retrieval_query_candidates_prefers_supported_time_anchor_signals() -> None:
    mod = _import_module()
    records = [
        {"content": "리아 황녀가 귀환했다.", "source_id": "SRC-a", "episode_no": 1},
        {"content": "평범한 설명이 이어진다.", "source_id": "SRC-b", "episode_no": 2},
        {"content": "며칠 후 회의가 열렸다.", "source_id": "SRC-c", "episode_no": 3},
    ]

    candidates = mod._pick_retrieval_query_candidates(
        records,
        limit=2,
        seed=1,
        graph_enabled=True,
        index_runtime={
            "entity_mentions_created": 0,
            "time_anchors_created": 5,
            "timeline_events_created": 0,
            "graph_index": {"nodes_entity": 0, "nodes_time": 5, "nodes_timeline": 0},
        },
    )

    assert len(candidates) == 2
    assert "time_anchor" in candidates[0]["signal_types"]
    assert candidates[0]["source_id"] == "SRC-c"


@pytest.mark.unit
def test_pick_retrieval_queries_uses_compact_prefix_when_graph_disabled() -> None:
    mod = _import_module()
    records = [
        {"content": "첫 문장.\n둘째 문장.\n셋째 문장."},
    ]

    queries = mod._pick_retrieval_queries(records, limit=1, seed=1, graph_enabled=False)

    assert queries == ["첫 문장. 둘째 문장. 셋째 문장."]


@pytest.mark.unit
def test_consistency_signal_summary_ignores_unsupported_profile_and_quoted_age_lines() -> None:
    mod = _import_module()

    summary = mod._consistency_signal_summary('이름은 메이레이.\n"448살입니다."')

    assert int(summary["score"]) == 0
    assert summary["signal_counts"] == {}
    assert summary["first_signal_offset"] is None


@pytest.mark.unit
def test_pick_consistency_targets_prioritizes_extractable_claim_docs() -> None:
    mod = _import_module()
    doc_ids = ["doc-1", "doc-2", "doc-3", "doc-4"]
    records = [
        {"content": "일반 서술문이다."},
        {"content": "소속: 라인시스 제국\n관계: 주인공의 동생"},
        {"content": "[PM 5:31]\n나이는 14세였다."},
        {"content": "이름은 메이레이다."},
    ]

    selected, summary = mod._pick_consistency_targets(doc_ids, records=records, sample_count=2, seed=1)

    assert [str(item["doc_id"]) for item in selected] == ["doc-2", "doc-3"]
    assert summary["mode"] == "signal_priority_then_signal_window"
    assert int(summary["signal_positive_docs_total"]) == 2
    assert int(summary["selected_signal_positive_docs"]) == 2
    assert int(summary["selected_signal_type_counts"]["affiliation"]) >= 1
    assert int(summary["selected_signal_type_counts"]["relation"]) >= 1
    assert int(summary["selected_signal_type_counts"]["age"]) >= 1
    assert summary["selected_window_sample"][0]["doc_id"] == "doc-2"


@pytest.mark.unit
def test_pick_consistency_targets_skips_local_profile_only_records_by_default() -> None:
    mod = _import_module()
    doc_ids = ["doc-1", "doc-2", "doc-3"]
    records = [
        {
            "content": "이름: 금철생\n\n나이: 스물 다섯\n\n소속: 사도련 백전귀(百戰鬼)\n\n별호: 규백도귀",
        },
        {
            "content": "소속: 라인시스 제국\n관계: 주인공의 동생",
        },
        {
            "content": "평범한 대화문이다.",
        },
    ]

    selected, summary = mod._pick_consistency_targets(doc_ids, records=records, sample_count=2, seed=1)

    assert [str(item["doc_id"]) for item in selected] == ["doc-2", "doc-3"]
    assert int(summary["local_profile_only_docs_total"]) == 1
    assert int(summary["skipped_local_profile_only_docs"]) == 1
    assert int(summary["selected_local_profile_only_docs"]) == 0
    assert summary["include_local_profile_only"] is False


@pytest.mark.unit
def test_filter_records_for_shadow_track_selects_local_profile_only_subset() -> None:
    mod = _import_module()
    records = [
        {"content": "이름: 금철생\n\n소속: 사도련 백전귀(百戰鬼)\n\n별호: 규백도귀"},
        {"content": "무림맹은 갈라지고, 사도련은 들썩거린다."},
    ]

    selected, summary = mod._filter_records_for_shadow_track(records, only_local_profile_only=True)

    assert len(selected) == 1
    assert str(summary["filter_mode"]) == "only_local_profile_only"
    assert int(summary["input_record_count"]) == 2
    assert int(summary["selected_record_count"]) == 1
    assert int(summary["local_profile_only_selected_count"]) == 1


@pytest.mark.unit
def test_consistency_runtime_aggregates_counts_unknown_reasons_and_rates() -> None:
    mod = _import_module()
    runtime = mod._new_consistency_runtime(graph_mode="off")

    mod._accumulate_consistency_runtime(
        runtime,
        {
            "segment_count": 8,
            "segments_with_claims_count": 5,
            "claim_count": 6,
            "claims_processed": 4,
            "claims_skipped_low_confidence": 1,
            "claim_slot_counts": {"relation": 2, "age": 1},
            "slot_matches": 6,
            "slot_candidate_count": 7,
            "slot_candidate_selected": 6,
            "avg_slot_confidence": 0.8,
            "triage_total_claims": 6,
            "triage_selected_claims": 4,
            "triage_skipped_claims": 2,
            "graph_mode": "auto",
            "graph_expand_applied_count": 1,
            "graph_auto_trigger_count": 2,
            "graph_auto_skip_count": 3,
            "layer3_rerank_applied_count": 4,
            "layer3_model_fallback_count": 1,
            "layer3_model_enabled": True,
            "layer3_local_nli_enabled": True,
            "layer3_remote_api_enabled": False,
            "layer3_local_reranker_enabled": False,
            "layer3_nli_capable": True,
            "layer3_reranker_capable": False,
            "layer3_effective_capable": True,
            "layer3_promotion_enabled": True,
            "layer3_inactive_reasons": ["LOCAL_RERANKER_DISABLED"],
            "verification_loop_trigger_count": 5,
            "verification_loop_attempted_rounds_total": 7,
            "verification_loop_rounds_total": 6,
            "verification_loop_timeout_count": 1,
            "verification_loop_stagnation_break_count": 2,
            "verification_loop_round_elapsed_ms_sum": 140.0,
            "verification_loop_round_elapsed_ms_max": 40.0,
            "verification_loop_round_elapsed_ms_samples": [10.0, 20.0, 30.0, 40.0],
            "verification_loop_candidate_growth_total": 9,
            "verification_loop_candidate_growth_samples": [1, 2, 3, 3],
            "verification_loop_exit_reason_counts": {"verdict_resolved": 2, "candidate_stagnation": 1},
            "verification_loop_reason_transition_counts": {"NO_EVIDENCE->CONFLICTING_EVIDENCE": 2},
            "self_evidence_filtered_count": 7,
            "retrieval_anchor_filtered_count": 3,
            "anchor_filtered_slot_counts": {"relation": 3},
            "snippet_slot_cache_hit_count": 5,
            "snippet_slot_cache_miss_count": 2,
            "anchor_rescue_attempt_count": 4,
            "anchor_rescue_ok_count": 1,
            "snippet_corroborated_count": 1,
            "layer3_promoted_ok_count": 1,
            "vid_count": 10,
            "violate_count": 3,
            "unknown_count": 4,
            "unknown_reason_counts": {"NO_EVIDENCE": 2, "CONFLICTING_EVIDENCE": 1},
            "unknown_slot_counts": {"relation": 2, "age": 1},
            "no_evidence_slot_counts": {"relation": 1, "age": 1},
        },
    )
    mod._accumulate_consistency_runtime(
        runtime,
        {
            "segment_count": 10,
            "segments_with_claims_count": 4,
            "claim_count": 5,
            "claims_processed": 3,
            "claims_skipped_low_confidence": 2,
            "claim_slot_counts": {"relation": 1, "affiliation": 2},
            "slot_matches": 5,
            "slot_candidate_count": 6,
            "slot_candidate_selected": 5,
            "avg_slot_confidence": 0.4,
            "triage_total_claims": 5,
            "triage_selected_claims": 3,
            "triage_skipped_claims": 2,
            "graph_expand_applied_count": 2,
            "layer3_model_enabled": False,
            "layer3_local_nli_enabled": False,
            "layer3_remote_api_enabled": False,
            "layer3_local_reranker_enabled": False,
            "layer3_nli_capable": False,
            "layer3_reranker_capable": False,
            "layer3_effective_capable": False,
            "layer3_promotion_enabled": True,
            "layer3_inactive_reasons": ["GLOBAL_LAYER3_MODEL_DISABLED", "STRICT_VERIFIER_NLI_UNAVAILABLE"],
            "verification_loop_attempted_rounds_total": 3,
            "verification_loop_rounds_total": 4,
            "verification_loop_timeout_count": 1,
            "verification_loop_stagnation_break_count": 1,
            "verification_loop_round_elapsed_ms_sum": 60.0,
            "verification_loop_round_elapsed_ms_max": 25.0,
            "verification_loop_round_elapsed_ms_samples": [15.0, 20.0, 25.0],
            "verification_loop_candidate_growth_total": 2,
            "verification_loop_candidate_growth_samples": [0, 1, 1],
            "verification_loop_exit_reason_counts": {"timeout_before_round": 1},
            "verification_loop_reason_transition_counts": {"CONFLICTING_EVIDENCE-><none>": 1},
            "self_evidence_filtered_count": 3,
            "retrieval_anchor_filtered_count": 1,
            "anchor_filtered_slot_counts": {"affiliation": 1},
            "snippet_slot_cache_hit_count": 4,
            "snippet_slot_cache_miss_count": 3,
            "anchor_rescue_attempt_count": 2,
            "anchor_rescue_ok_count": 1,
            "snippet_corroborated_count": 2,
            "vid_count": 5,
            "violate_count": 2,
            "unknown_count": 1,
            "unknown_reason_counts": {"NO_EVIDENCE": 1, "SLOT_UNCOMPARABLE": 2},
            "unknown_slot_counts": {"affiliation": 1},
            "no_evidence_slot_counts": {"affiliation": 1},
        },
    )
    finalized = mod._finalize_consistency_runtime(runtime)

    assert finalized["graph_mode"] == "auto"
    assert int(finalized["jobs_sampled"]) == 2
    assert int(finalized["segment_count_total"]) == 18
    assert int(finalized["segments_with_claims_count_total"]) == 9
    assert int(finalized["claim_count_total"]) == 11
    assert int(finalized["claims_processed_total"]) == 7
    assert int(finalized["claims_skipped_low_confidence_total"]) == 3
    assert finalized["claim_slot_counts"] == {"relation": 3, "age": 1, "affiliation": 2}
    assert int(finalized["slot_matches_total"]) == 11
    assert int(finalized["slot_candidate_count_total"]) == 13
    assert int(finalized["slot_candidate_selected_total"]) == 11
    assert int(finalized["triage_total_claims_total"]) == 11
    assert int(finalized["triage_selected_claims_total"]) == 7
    assert int(finalized["triage_skipped_claims_total"]) == 4
    assert float(finalized["slot_detection_rate"]) == pytest.approx(9.0 / 18.0)
    assert float(finalized["claims_skipped_low_confidence_rate"]) == pytest.approx(3.0 / 7.0)
    assert float(finalized["triage_selection_rate"]) == pytest.approx(7.0 / 11.0)
    assert float(finalized["avg_slot_confidence"]) == pytest.approx(0.6)
    assert int(finalized["graph_expand_applied_count"]) == 3
    assert int(finalized["verification_loop_attempted_rounds_total"]) == 10
    assert int(finalized["verification_loop_rounds_total"]) == 10
    assert int(finalized["verification_loop_timeout_count"]) == 2
    assert int(finalized["verification_loop_stagnation_break_count"]) == 3
    assert int(finalized["layer3_model_enabled_jobs"]) == 1
    assert int(finalized["layer3_local_nli_enabled_jobs"]) == 1
    assert int(finalized["layer3_remote_api_enabled_jobs"]) == 0
    assert int(finalized["layer3_local_reranker_enabled_jobs"]) == 0
    assert int(finalized["layer3_nli_capable_jobs"]) == 1
    assert int(finalized["layer3_reranker_capable_jobs"]) == 0
    assert int(finalized["layer3_effective_capable_jobs"]) == 1
    assert int(finalized["layer3_promotion_enabled_jobs"]) == 2
    inactive_reason_counts = finalized["layer3_inactive_reason_counts"]
    assert int(inactive_reason_counts["LOCAL_RERANKER_DISABLED"]) == 1
    assert int(inactive_reason_counts["GLOBAL_LAYER3_MODEL_DISABLED"]) == 1
    assert int(inactive_reason_counts["STRICT_VERIFIER_NLI_UNAVAILABLE"]) == 1
    assert float(finalized["layer3_model_enabled_ratio"]) == pytest.approx(0.5)
    assert float(finalized["layer3_local_nli_enabled_ratio"]) == pytest.approx(0.5)
    assert float(finalized["layer3_remote_api_enabled_ratio"]) == pytest.approx(0.0)
    assert float(finalized["layer3_local_reranker_enabled_ratio"]) == pytest.approx(0.0)
    assert float(finalized["layer3_nli_capable_ratio"]) == pytest.approx(0.5)
    assert float(finalized["layer3_reranker_capable_ratio"]) == pytest.approx(0.0)
    assert float(finalized["layer3_effective_capable_ratio"]) == pytest.approx(0.5)
    assert float(finalized["layer3_promotion_enabled_ratio"]) == pytest.approx(1.0)
    assert float(finalized["verification_loop_round_elapsed_ms_sum"]) == pytest.approx(200.0)
    assert float(finalized["verification_loop_round_elapsed_ms_max"]) == pytest.approx(40.0)
    assert float(finalized["verification_loop_round_elapsed_ms_avg"]) == pytest.approx(20.0)
    assert float(finalized["verification_loop_round_elapsed_ms_p95"]) == pytest.approx(37.0)
    assert int(finalized["verification_loop_candidate_growth_total"]) == 11
    assert float(finalized["verification_loop_candidate_growth_avg"]) == pytest.approx(1.1)
    assert float(finalized["verification_loop_candidate_growth_p95"]) == pytest.approx(3.0)
    assert int(finalized["self_evidence_filtered_count"]) == 10
    assert int(finalized["retrieval_anchor_filtered_count"]) == 4
    assert finalized["anchor_filtered_slot_counts"] == {"relation": 3, "affiliation": 1}
    assert int(finalized["snippet_slot_cache_hit_count"]) == 9
    assert int(finalized["snippet_slot_cache_miss_count"]) == 5
    assert float(finalized["snippet_slot_cache_hit_rate"]) == pytest.approx(9.0 / 14.0)
    assert int(finalized["anchor_rescue_attempt_count"]) == 6
    assert int(finalized["anchor_rescue_ok_count"]) == 2
    assert float(finalized["anchor_rescue_ok_rate"]) == pytest.approx(2.0 / 6.0)
    assert int(finalized["snippet_corroborated_count"]) == 3
    assert int(finalized["vid_count_total"]) == 15
    assert int(finalized["violate_count_total"]) == 5
    assert int(finalized["unknown_count_total"]) == 5
    exit_counts = finalized["verification_loop_exit_reason_counts"]
    assert int(exit_counts["verdict_resolved"]) == 2
    assert int(exit_counts["candidate_stagnation"]) == 1
    assert int(exit_counts["timeout_before_round"]) == 1
    transition_counts = finalized["verification_loop_reason_transition_counts"]
    assert int(transition_counts["NO_EVIDENCE->CONFLICTING_EVIDENCE"]) == 2
    assert int(transition_counts["CONFLICTING_EVIDENCE-><none>"]) == 1
    reason_counts = finalized["unknown_reason_counts"]
    assert int(reason_counts["NO_EVIDENCE"]) == 3
    assert int(reason_counts["CONFLICTING_EVIDENCE"]) == 1
    assert int(reason_counts["SLOT_UNCOMPARABLE"]) == 2
    assert finalized["unknown_slot_counts"] == {"relation": 2, "age": 1, "affiliation": 1}
    assert finalized["no_evidence_slot_counts"] == {"relation": 1, "age": 1, "affiliation": 1}
    assert int(finalized["jobs_with_claims_total"]) == 2
    assert finalized["slot_diagnostics_schema_status"] == "COMPLETE"
    assert int(finalized["slot_diagnostics_present_jobs"]) == 2
    assert int(finalized["slot_diagnostics_partial_jobs"]) == 0
    assert int(finalized["slot_diagnostics_missing_jobs"]) == 0
    assert int(finalized["slot_diagnostics_missing_with_claims_jobs"]) == 0
    assert float(finalized["slot_diagnostics_complete_job_rate"]) == pytest.approx(1.0)
    assert float(finalized["slot_diagnostics_missing_with_claims_rate"]) == pytest.approx(0.0)
    assert float(finalized["violate_rate"]) == pytest.approx(5.0 / 15.0)
    assert float(finalized["unknown_rate"]) == pytest.approx(5.0 / 15.0)


@pytest.mark.unit
def test_consistency_runtime_marks_mixed_slot_diagnostic_schema_when_old_worker_payloads_are_present() -> None:
    mod = _import_module()
    runtime = mod._new_consistency_runtime(graph_mode="off")

    mod._accumulate_consistency_runtime(
        runtime,
        {
            "segment_count": 4,
            "segments_with_claims_count": 1,
            "claim_count": 1,
            "claims_processed": 1,
            "claim_slot_counts": {"relation": 1},
            "slot_matches": 1,
            "slot_candidate_count": 1,
            "slot_candidate_selected": 1,
            "avg_slot_confidence": 0.7,
            "triage_total_claims": 1,
            "triage_selected_claims": 1,
            "triage_skipped_claims": 0,
            "anchor_filtered_slot_counts": {},
            "unknown_slot_counts": {"relation": 1},
            "no_evidence_slot_counts": {"relation": 1},
            "vid_count": 1,
            "unknown_count": 1,
            "unknown_reason_counts": {"NO_EVIDENCE": 1},
        },
    )
    mod._accumulate_consistency_runtime(
        runtime,
        {
            "segment_count": 3,
            "segments_with_claims_count": 1,
            "claim_count": 1,
            "claims_processed": 1,
            "slot_matches": 1,
            "slot_candidate_count": 1,
            "slot_candidate_selected": 1,
            "avg_slot_confidence": 0.5,
            "triage_total_claims": 1,
            "triage_selected_claims": 1,
            "triage_skipped_claims": 0,
            "vid_count": 1,
            "unknown_count": 1,
            "unknown_reason_counts": {"NO_EVIDENCE": 1},
        },
    )
    finalized = mod._finalize_consistency_runtime(runtime)

    assert int(finalized["jobs_with_claims_total"]) == 2
    assert finalized["slot_diagnostics_schema_status"] == "MIXED"
    assert int(finalized["slot_diagnostics_present_jobs"]) == 1
    assert int(finalized["slot_diagnostics_partial_jobs"]) == 0
    assert int(finalized["slot_diagnostics_missing_jobs"]) == 1
    assert int(finalized["slot_diagnostics_missing_with_claims_jobs"]) == 1
    assert float(finalized["slot_diagnostics_complete_job_rate"]) == pytest.approx(0.5)
    assert float(finalized["slot_diagnostics_missing_with_claims_rate"]) == pytest.approx(0.5)


@pytest.mark.unit
def test_graph_runtime_tracks_samples_skip_reasons_and_signal_counts() -> None:
    mod = _import_module()
    runtime = mod._new_graph_runtime(index_runtime={"nodes_time": 3})

    mod._accumulate_graph_runtime(
        runtime,
        candidate={
            "query": "리아 황녀는 연회 다음 날 귀환했다.",
            "signal_types": ["entity_alias", "timeline_signal", "time_anchor"],
            "source_id": "SRC-1",
            "episode_no": 2,
        },
        graph_payload={
            "applied": True,
            "seed_doc_count": 2,
            "expanded_doc_count": 4,
            "boosted_result_count": 3,
        },
    )
    mod._accumulate_graph_runtime(
        runtime,
        candidate={
            "query": "평범한 문장이다.",
            "signal_types": [],
            "source_id": "SRC-2",
            "episode_no": 3,
        },
        graph_payload={
            "applied": False,
            "reason": "no_seeds",
            "seed_doc_count": 0,
            "expanded_doc_count": 0,
            "boosted_result_count": 0,
        },
    )

    assert runtime["index_runtime"]["nodes_time"] == 3
    assert int(runtime["applied_count"]) == 1
    assert int(runtime["sampled_jobs"]) == 2
    assert int(runtime["skipped_reason_counts"]["no_seeds"]) == 1
    assert int(runtime["seed_signal_type_counts"]["entity_alias"]) == 1
    assert int(runtime["seed_signal_type_counts"]["timeline_signal"]) == 1
    assert int(runtime["seed_signal_type_counts"]["time_anchor"]) == 1
    assert runtime["applied_queries_sample"][0]["applied"] is True
    assert runtime["skipped_queries_sample"][0]["reason"] == "no_seeds"


@pytest.mark.unit
def test_summarize_dataset_records_tracks_segmentation_and_inject_metadata() -> None:
    mod = _import_module()
    profile = mod._summarize_dataset_records(
        [
            {
                "dataset": "DS-GROWTH-200",
                "source_id": "SRC-alpha",
                "source_segmentation_mode": "header_boundary",
                "source_boundary_pattern": "episode_hwa",
                "consistency_corroboration_policy": "local_profile_only",
            },
            {
                "dataset": "DS-GROWTH-200",
                "source_id": "SRC-beta",
                "source_segmentation_mode": "fallback_chunk",
                "inject_strategy": "append_marker_statement",
                "injected_kind": "age",
                "judge_requested_backend": "local_nli",
                "judge_effective_backend": "local_nli_fallback",
                "judge_prompt_version": "inject-quality-judge-v1",
                "judge_fallback_used": True,
            },
            {
                "dataset": "DS-GROWTH-200",
                "source_id": "SRC-beta",
                "source_segmentation_mode": "fallback_chunk",
                "inject_strategy": "control_no_inject",
            },
        ]
    )

    assert int(profile["record_count"]) == 3
    assert int(profile["unique_source_files"]) == 2
    assert int(profile["source_segmentation_mode_counts"]["header_boundary"]) == 1
    assert int(profile["source_segmentation_mode_counts"]["fallback_chunk"]) == 2
    assert int(profile["source_boundary_pattern_counts"]["episode_hwa"]) == 1
    assert int(profile["injected_kind_counts"]["age"]) == 1
    assert int(profile["inject_strategy_counts"]["append_marker_statement"]) == 1
    assert int(profile["inject_strategy_counts"]["control_no_inject"]) == 1
    assert int(profile["inject_record_count"]) == 1
    assert int(profile["requested_backend_counts"]["local_nli"]) == 1
    assert int(profile["effective_backend_counts"]["local_nli_fallback"]) == 1
    assert int(profile["prompt_version_counts"]["inject-quality-judge-v1"]) == 1
    assert int(profile["consistency_corroboration_policy_counts"]["local_profile_only"]) == 1
    assert int(profile["local_profile_only_record_count"]) == 1
    assert int(profile["fallback_used_count"]) == 1
    assert profile["generic_append_inject_present"] is True
    assert profile["growth_prefix_dataset"] is True


@pytest.mark.unit
def test_top_level_output_fields_expose_semantic_and_guard_paths() -> None:
    mod = _import_module()
    run = mod.BenchRunResult(
        started_at="2026-03-07T00:00:00Z",
        finished_at="2026-03-07T00:00:01Z",
        base_url="http://127.0.0.1:8085",
        dataset_path="verify/datasets/DS-INJECT-C.jsonl",
        dataset_hash="dataset-hash",
        project_id="project-1",
        doc_count=1,
        rss_mb_process=0.0,
        timings_ms={"consistency_p95": 1.0},
        status={"index_fts": "SUCCEEDED"},
        semantic={
            "dataset_profile": {"record_count": 1},
            "frontdoor_probe": {"request_path": "/health"},
            "guards": {
                "index_jobs_succeeded": True,
                "ingest_failures_zero": False,
                "consistency_failures_zero": True,
                "retrieve_vec_failures_zero": True,
            },
            "graph": {
                "applied_count": 2,
                "sampled_jobs": 5,
                "index_runtime": {"nodes_time": 3},
                "applied_queries_sample": [{"query": "sample applied"}],
                "skipped_queries_sample": [{"query": "sample skipped"}],
                "skipped_reason_counts": {"no_seeds": 2},
                "seed_signal_type_counts": {"time_anchor": 3},
            },
            "consistency_runtime": {"unknown_rate": 0.25},
        },
        semantic_hash="semantic-hash",
        metrics_hash="metrics-hash",
    )

    output_fields = mod._top_level_output_fields(run)

    assert output_fields["semantic"]["dataset_profile"]["record_count"] == 1
    assert output_fields["guards"]["index_jobs_succeeded"] is True
    assert output_fields["guards"]["ingest_failures_zero"] is False
    assert output_fields["frontdoor_probe"]["request_path"] == "/health"
    assert output_fields["graph_index_runtime"]["nodes_time"] == 3
    assert output_fields["graph_runtime"]["applied_count"] == 2
    assert output_fields["graph_runtime"]["sampled_jobs"] == 5
    assert output_fields["graph_runtime"]["applied_queries_sample"][0]["query"] == "sample applied"
    assert int(output_fields["graph_runtime"]["skipped_reason_counts"]["no_seeds"]) == 2
    assert int(output_fields["graph_runtime"]["seed_signal_type_counts"]["time_anchor"]) == 3
    assert output_fields["consistency_runtime"]["unknown_rate"] == pytest.approx(0.25)


@pytest.mark.unit
def test_build_consistency_override_summary_reads_cli_namespace() -> None:
    mod = _import_module()

    class _Args:
        consistency_graph_mode = "manual"
        consistency_metadata_grouping = "on"
        consistency_layer3_promotion = "off"
        consistency_verifier_mode = "conservative_nli"
        consistency_triage_mode = "embedding_anomaly"
        consistency_triage_anomaly_threshold = 0.61
        consistency_triage_max_segments = 7
        consistency_verification_loop = "on"
        consistency_verification_loop_max_rounds = 5
        consistency_verification_loop_timeout_ms = 1100

    summary = mod._build_consistency_override_summary(_Args())

    assert summary["graph_mode"] == "manual"
    assert summary["metadata_grouping_enabled"] is True
    assert summary["layer3_verdict_promotion"] is False
    assert summary["verifier_mode"] == "conservative_nli"
    assert summary["triage_mode"] == "embedding_anomaly"
    assert float(summary["triage_anomaly_threshold"]) == pytest.approx(0.61)
    assert int(summary["triage_max_segments_per_run"]) == 7
    assert summary["verification_loop_enabled"] is True
    assert int(summary["verification_loop_max_rounds"]) == 5
    assert int(summary["verification_loop_timeout_ms"]) == 1100


@pytest.mark.unit
def test_build_failure_payload_keeps_transport_context() -> None:
    mod = _import_module()

    class _Args:
        base_url = "http://127.0.0.1:8085"
        dataset = "verify/datasets/DS-GROWTH-50.jsonl"
        bench_label = "validation:transport-failure"
        profile = "throughput"
        consistency_level = "quick"

    cause = mod.ApiRequestError(
        base_url="http://127.0.0.1:8085",
        method="POST",
        path="/projects",
        error_class="RemoteDisconnected",
        detail="Remote end closed connection without response",
    )
    stage_error = mod.BenchStageError("project_create", cause)

    payload = mod._build_failure_payload(args=_Args(), stage_error=stage_error)

    assert payload["attempt_stage"] == "project_create"
    assert payload["attempt_index"] == 1
    assert payload["request_method"] == "POST"
    assert payload["request_path"] == "/projects"
    assert payload["request_body_shape"] == {}
    assert payload["error_class"] == "RemoteDisconnected"
    assert payload["base_url"] == "http://127.0.0.1:8085"
    assert payload["transport"]["method"] == "POST"


@pytest.mark.unit
def test_probe_frontdoor_uses_health_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()

    class _Client:
        def get(self, path):  # noqa: ANN001
            assert path == "/health"
            return {"status": "ok"}

    payload = mod._probe_frontdoor(_Client())

    assert payload["request_path"] == "/health"
    assert payload["response"] == {"status": "ok"}


@pytest.mark.unit
def test_load_dataset_manifest_entry_reads_generation_version_and_policy(tmp_path: Path) -> None:
    mod = _import_module()
    datasets_dir = tmp_path / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = datasets_dir / "DS-GROWTH-50.jsonl"
    dataset_path.write_text("", encoding="utf-8")
    manifest = {
        "dataset_generation_version": "20260312-r7",
        "composite_source_policy": "exclude_fallback_sources_unless_empty",
        "datasets": {
            "DS-GROWTH-50": {
                "path": str(dataset_path),
                "sampling_strategy": "shuffled_seed_42_prefix_50",
            }
        },
    }
    (datasets_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    entry = mod._load_dataset_manifest_entry(dataset_path)

    assert entry["dataset_generation_version"] == "20260312-r7"
    assert entry["composite_source_policy"] == "exclude_fallback_sources_unless_empty"
    assert entry["sampling_strategy"] == "shuffled_seed_42_prefix_50"


@pytest.mark.unit
def test_top_level_output_fields_keep_corroboration_filter_summary() -> None:
    mod = _import_module()
    run = mod.BenchRunResult(
        started_at="2026-03-07T00:00:00Z",
        finished_at="2026-03-07T00:00:01Z",
        base_url="http://127.0.0.1:8085",
        dataset_path="verify/datasets/DS-GROWTH-200.jsonl",
        dataset_hash="dataset-hash",
        project_id="project-1",
        doc_count=1,
        rss_mb_process=0.0,
        timings_ms={"consistency_p95": 1.0},
        status={"index_fts": "SUCCEEDED"},
        semantic={
            "dataset_profile": {
                "record_count": 1,
                "consistency_corroboration_filter": {
                    "filter_mode": "only_local_profile_only",
                    "selected_record_count": 1,
                },
            },
            "frontdoor_probe": {"request_path": "/health"},
            "guards": {"index_jobs_succeeded": True},
            "graph": {"applied_count": 0, "sampled_jobs": 0, "index_runtime": {}},
            "consistency_runtime": {},
        },
        semantic_hash="semantic-hash",
        metrics_hash="metrics-hash",
    )

    output_fields = mod._top_level_output_fields(run)

    assert output_fields["semantic"]["dataset_profile"]["consistency_corroboration_filter"]["filter_mode"] == "only_local_profile_only"
