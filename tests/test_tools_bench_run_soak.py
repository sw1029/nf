from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("run_soak")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


@pytest.mark.unit
def test_aggregate_streams_accumulates_failure_breakdown_and_samples() -> None:
    mod = _import_module()

    aggregate = mod._aggregate_streams(
        [
            {
                "jobs_total": 10,
                "jobs_failed": 2,
                "cycles": 1,
                "status_breakdown": {
                    "policy_violations": 1,
                    "submit_retries": 0,
                    "network_errors": 0,
                    "unexpected_errors": 0,
                },
                "_queue_lags_all_ms": [],
                "_queue_lags_consistency_ms": [],
                "_consistency_elapsed_ms": [],
                "_rss_samples": [],
                "workload": {},
                "graph": {},
                "orchestrator_crashes": 0,
                "failed_ratio": 0.2,
                "queue_lag_p95_ms": 0.0,
                "failure_breakdown": {
                    "by_stage": {"CONSISTENCY": 1, "doc_update": 1},
                    "by_status": {"FAILED": 1, "NETWORK_ERROR": 1},
                    "by_stage_status": {"CONSISTENCY:FAILED": 1, "doc_update:NETWORK_ERROR": 1},
                },
                "failure_samples": [
                    {"stage": "CONSISTENCY", "status": "FAILED", "detail": "job_id=1"},
                ],
            },
            {
                "jobs_total": 8,
                "jobs_failed": 1,
                "cycles": 1,
                "status_breakdown": {
                    "policy_violations": 0,
                    "submit_retries": 0,
                    "network_errors": 1,
                    "unexpected_errors": 0,
                },
                "_queue_lags_all_ms": [],
                "_queue_lags_consistency_ms": [],
                "_consistency_elapsed_ms": [],
                "_rss_samples": [],
                "workload": {},
                "graph": {},
                "orchestrator_crashes": 1,
                "failed_ratio": 0.125,
                "queue_lag_p95_ms": 0.0,
                "failure_breakdown": {
                    "by_stage": {"RETRIEVE_VEC": 1},
                    "by_status": {"UNEXPECTED_ERROR": 1},
                    "by_stage_status": {"RETRIEVE_VEC:UNEXPECTED_ERROR": 1},
                },
                "failure_samples": [
                    {"stage": "RETRIEVE_VEC", "status": "UNEXPECTED_ERROR", "detail": "submit failed"},
                ],
            },
        ],
        hours=1.0,
    )

    failure_breakdown = aggregate["failure_breakdown"]
    assert int(failure_breakdown["by_stage"]["CONSISTENCY"]) == 1
    assert int(failure_breakdown["by_stage"]["doc_update"]) == 1
    assert int(failure_breakdown["by_stage"]["RETRIEVE_VEC"]) == 1
    assert int(failure_breakdown["by_status"]["FAILED"]) == 1
    assert int(failure_breakdown["by_status"]["NETWORK_ERROR"]) == 1
    assert int(failure_breakdown["by_status"]["UNEXPECTED_ERROR"]) == 1
    assert int(failure_breakdown["by_stage_status"]["CONSISTENCY:FAILED"]) == 1
    assert int(failure_breakdown["by_stage_status"]["RETRIEVE_VEC:UNEXPECTED_ERROR"]) == 1

    samples = aggregate["failure_samples"]
    assert len(samples) == 2
    assert samples[0]["stage"] == "CONSISTENCY"
    assert samples[1]["stage"] == "RETRIEVE_VEC"


@pytest.mark.unit
def test_resolve_consistency_slot_limits_becomes_more_conservative_when_streams_exceed_capacity() -> None:
    mod = _import_module()

    running_limit, outstanding_limit = mod._resolve_consistency_slot_limits(streams=4, max_heavy_jobs=2)
    assert running_limit == 1
    assert outstanding_limit == 2

    running_limit_equal, outstanding_limit_equal = mod._resolve_consistency_slot_limits(streams=2, max_heavy_jobs=2)
    assert running_limit_equal == 2
    assert outstanding_limit_equal == 3
