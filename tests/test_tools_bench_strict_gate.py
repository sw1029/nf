from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("check_consistency_strict_gate")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


def _artifact(
    *,
    consistency_p95: float,
    retrieval_fts_p95: float,
    level: str = "strict",
    timeout_count: int = 0,
    rounds_total: int = 10,
    conflicting_unknown_count: int = 0,
    violate_count_total: int = 0,
) -> dict:
    return {
        "timings_ms": {
            "consistency_p95": consistency_p95,
            "retrieval_fts_p95": retrieval_fts_p95,
        },
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "parallel": {
            "consistency_level": level,
        },
        "consistency_runtime": {
            "unknown_reason_counts": {"CONFLICTING_EVIDENCE": conflicting_unknown_count},
            "verification_loop_trigger_count": 3,
            "verification_loop_rounds_total": rounds_total,
            "verification_loop_timeout_count": timeout_count,
            "verification_loop_stagnation_break_count": 1,
            "self_evidence_filtered_count": 2,
            "vid_count_total": 10,
            "violate_count_total": violate_count_total,
            "unknown_count_total": 3,
        },
    }


@pytest.mark.unit
def test_strict_gate_passes_when_all_conditions_are_met() -> None:
    mod = _import_module()
    baseline = _artifact(consistency_p95=1000.0, retrieval_fts_p95=300.0, level="quick")
    control = _artifact(consistency_p95=1700.0, retrieval_fts_p95=440.0, level="strict", timeout_count=1, rounds_total=10)
    inject = _artifact(
        consistency_p95=1750.0,
        retrieval_fts_p95=430.0,
        level="strict",
        timeout_count=1,
        rounds_total=10,
        conflicting_unknown_count=2,
    )

    result = mod.evaluate_strict_gate(
        baseline_payload=baseline,
        control_payload=control,
        inject_payload=inject,
    )

    assert result["passed"] is True
    assert all(bool(check["passed"]) for check in result["checks"])


@pytest.mark.unit
def test_strict_gate_fails_on_perf_ratio_exceed() -> None:
    mod = _import_module()
    baseline = _artifact(consistency_p95=1000.0, retrieval_fts_p95=300.0, level="quick")
    control = _artifact(consistency_p95=1900.0, retrieval_fts_p95=440.0, level="strict")
    inject = _artifact(
        consistency_p95=1700.0,
        retrieval_fts_p95=430.0,
        level="strict",
        conflicting_unknown_count=1,
    )

    result = mod.evaluate_strict_gate(
        baseline_payload=baseline,
        control_payload=control,
        inject_payload=inject,
    )

    assert result["passed"] is False
    perf_check = next(item for item in result["checks"] if item["name"] == "strict_perf_ratio_within_limit")
    assert perf_check["passed"] is False


@pytest.mark.unit
def test_strict_gate_fails_when_inject_conflict_signal_missing() -> None:
    mod = _import_module()
    baseline = _artifact(consistency_p95=1000.0, retrieval_fts_p95=300.0, level="quick")
    control = _artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict")
    inject = _artifact(
        consistency_p95=1700.0,
        retrieval_fts_p95=430.0,
        level="strict",
        conflicting_unknown_count=0,
        violate_count_total=0,
    )

    result = mod.evaluate_strict_gate(
        baseline_payload=baseline,
        control_payload=control,
        inject_payload=inject,
    )

    assert result["passed"] is False
    signal_check = next(item for item in result["checks"] if item["name"] == "inject_conflict_signal_present")
    assert signal_check["passed"] is False
