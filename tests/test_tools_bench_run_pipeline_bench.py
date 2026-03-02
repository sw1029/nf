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
    assert strict_params["consistency"]["verifier"]["mode"] == "conservative_nli"
    assert strict_params["consistency"]["triage"]["mode"] == "embedding_anomaly"
    assert strict_params["consistency"]["verification_loop"]["enabled"] is True
    assert int(strict_params["consistency"]["verification_loop"]["max_rounds"]) == 2
    assert int(strict_params["consistency"]["verification_loop"]["round_timeout_ms"]) == 250


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
            "verification_loop_trigger_count": 5,
            "verification_loop_rounds_total": 6,
            "verification_loop_timeout_count": 1,
            "verification_loop_stagnation_break_count": 2,
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
            "verification_loop_rounds_total": 4,
            "verification_loop_timeout_count": 1,
            "verification_loop_stagnation_break_count": 1,
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
    assert int(finalized["verification_loop_rounds_total"]) == 10
    assert int(finalized["verification_loop_timeout_count"]) == 2
    assert int(finalized["verification_loop_stagnation_break_count"]) == 3
    assert int(finalized["self_evidence_filtered_count"]) == 10
    assert int(finalized["vid_count_total"]) == 15
    assert int(finalized["violate_count_total"]) == 5
    assert int(finalized["unknown_count_total"]) == 5
    reason_counts = finalized["unknown_reason_counts"]
    assert int(reason_counts["NO_EVIDENCE"]) == 3
    assert int(reason_counts["CONFLICTING_EVIDENCE"]) == 1
    assert int(reason_counts["SLOT_UNCOMPARABLE"]) == 2
    assert float(finalized["violate_rate"]) == pytest.approx(5.0 / 15.0)
    assert float(finalized["unknown_rate"]) == pytest.approx(5.0 / 15.0)
