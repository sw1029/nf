from __future__ import annotations

import importlib
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

    graph_off_index_params = mod._build_index_fts_params(graph_enabled=False)
    assert graph_off_index_params == {}

    graph_on_index_params = mod._build_index_fts_params(graph_enabled=True)
    assert graph_on_index_params["grouping"]["entity_mentions"] is True
    assert graph_on_index_params["grouping"]["time_anchors"] is True
    assert graph_on_index_params["grouping"]["graph_extract"] is True


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
def test_pick_retrieval_queries_uses_compact_prefix_when_graph_disabled() -> None:
    mod = _import_module()
    records = [
        {"content": "첫 문장.\n둘째 문장.\n셋째 문장."},
    ]

    queries = mod._pick_retrieval_queries(records, limit=1, seed=1, graph_enabled=False)

    assert queries == ["첫 문장. 둘째 문장. 셋째 문장."]


@pytest.mark.unit
def test_consistency_runtime_aggregates_counts_unknown_reasons_and_rates() -> None:
    mod = _import_module()
    runtime = mod._new_consistency_runtime(graph_mode="off")

    mod._accumulate_consistency_runtime(
        runtime,
        {
            "graph_mode": "auto",
            "graph_expand_applied_count": 1,
            "graph_auto_trigger_count": 2,
            "graph_auto_skip_count": 3,
            "layer3_rerank_applied_count": 4,
            "layer3_model_fallback_count": 1,
            "layer3_model_enabled": True,
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
            "layer3_promoted_ok_count": 1,
            "vid_count": 10,
            "violate_count": 3,
            "unknown_count": 4,
            "unknown_reason_counts": {"NO_EVIDENCE": 2, "CONFLICTING_EVIDENCE": 1},
        },
    )
    mod._accumulate_consistency_runtime(
        runtime,
        {
            "graph_expand_applied_count": 2,
            "layer3_model_enabled": False,
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
            "vid_count": 5,
            "violate_count": 2,
            "unknown_count": 1,
            "unknown_reason_counts": {"NO_EVIDENCE": 1, "SLOT_UNCOMPARABLE": 2},
        },
    )
    finalized = mod._finalize_consistency_runtime(runtime)

    assert finalized["graph_mode"] == "auto"
    assert int(finalized["jobs_sampled"]) == 2
    assert int(finalized["graph_expand_applied_count"]) == 3
    assert int(finalized["verification_loop_attempted_rounds_total"]) == 10
    assert int(finalized["verification_loop_rounds_total"]) == 10
    assert int(finalized["verification_loop_timeout_count"]) == 2
    assert int(finalized["verification_loop_stagnation_break_count"]) == 3
    assert int(finalized["layer3_model_enabled_jobs"]) == 1
    assert int(finalized["layer3_nli_capable_jobs"]) == 1
    assert int(finalized["layer3_reranker_capable_jobs"]) == 0
    assert int(finalized["layer3_effective_capable_jobs"]) == 1
    assert int(finalized["layer3_promotion_enabled_jobs"]) == 2
    inactive_reason_counts = finalized["layer3_inactive_reason_counts"]
    assert int(inactive_reason_counts["LOCAL_RERANKER_DISABLED"]) == 1
    assert int(inactive_reason_counts["GLOBAL_LAYER3_MODEL_DISABLED"]) == 1
    assert int(inactive_reason_counts["STRICT_VERIFIER_NLI_UNAVAILABLE"]) == 1
    assert float(finalized["layer3_model_enabled_ratio"]) == pytest.approx(0.5)
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
    assert float(finalized["violate_rate"]) == pytest.approx(5.0 / 15.0)
    assert float(finalized["unknown_rate"]) == pytest.approx(5.0 / 15.0)
