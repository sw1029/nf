from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _import_module():
    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        sys.modules.pop("render_gate_report", None)
        return importlib.import_module("render_gate_report")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))


@pytest.mark.unit
def test_pipeline_report_surfaces_corroboration_lane_details() -> None:
    mod = _import_module()
    payload = {
        "doc_count": 200,
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "timings_ms": {
            "index_fts": 10.0,
            "index_vec": 20.0,
            "consistency_p95": 1200.0,
            "retrieval_fts_p95": 40.0,
        },
        "graph": {"enabled": False},
        "graph_runtime": {"applied_count": 0},
        "consistency_runtime": {"graph_mode": "off"},
        "semantic": {
            "dataset_profile": {
                "local_profile_only_record_count": 1,
                "consistency_corroboration_policy_counts": {"default": 199, "local_profile_only": 1},
                "consistency_corroboration_filter": {"filter_mode": "all", "selected_record_count": 200},
                "dataset_manifest_entry": {
                    "dataset_generation_version": "20260312-r7",
                    "composite_source_policy": "exclude_fallback_sources_unless_empty",
                    "source_policy_registry_version": "20260307-r1",
                    "manual_review_source_count": 1,
                },
            },
            "consistency_target_selection": {
                "include_local_profile_only": False,
                "local_profile_only_docs_total": 1,
                "skipped_local_profile_only_docs": 1,
                "selected_local_profile_only_docs": 0,
            },
        },
    }

    execution_ok, goal_ok, lines = mod._pipeline_report(payload)
    rendered = "\n".join(lines)

    assert execution_ok is True
    assert goal_ok is True
    assert "pipeline_dataset_generation_version: `20260312-r7`" in rendered
    assert "pipeline_corroboration_lane: `mainline_excludes_local_profile_only`" in rendered
    assert "pipeline_local_profile_only_record_count: `1`" in rendered
    assert "pipeline_consistency_target_selection:" in rendered
    assert "pipeline_actionability_status: `MAINLINE_EMPTY_AFTER_SEPARATION`" in rendered
    assert "pipeline_shadow_reference_present: `false`" in rendered


@pytest.mark.unit
def test_pipeline_report_marks_shadow_local_profile_lane() -> None:
    mod = _import_module()
    payload = {
        "doc_count": 1,
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "timings_ms": {
            "index_fts": 10.0,
            "index_vec": 20.0,
            "consistency_p95": 800.0,
            "retrieval_fts_p95": 15.0,
        },
        "graph": {"enabled": False},
        "graph_runtime": {"applied_count": 0},
        "consistency_runtime": {"graph_mode": "off"},
        "semantic": {
            "dataset_profile": {
                "local_profile_only_record_count": 1,
                "consistency_corroboration_policy_counts": {"local_profile_only": 1},
                "consistency_corroboration_filter": {"filter_mode": "only_local_profile_only"},
                "dataset_manifest_entry": {
                    "dataset_generation_version": "20260312-r7",
                },
            },
            "consistency_target_selection": {
                "include_local_profile_only": True,
                "local_profile_only_docs_total": 1,
                "skipped_local_profile_only_docs": 0,
                "selected_local_profile_only_docs": 1,
            },
        },
    }

    _execution_ok, _goal_ok, lines = mod._pipeline_report(payload)
    rendered = "\n".join(lines)

    assert "pipeline_corroboration_lane: `shadow_local_profile_only`" in rendered


@pytest.mark.unit
def test_pipeline_report_uses_shadow_reference_for_actionability_separation() -> None:
    mod = _import_module()
    pipeline_payload = {
        "doc_count": 200,
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "timings_ms": {
            "index_fts": 10.0,
            "index_vec": 20.0,
            "consistency_p95": 1200.0,
            "retrieval_fts_p95": 40.0,
        },
        "graph": {"enabled": False},
        "graph_runtime": {"applied_count": 0},
        "consistency_runtime": {
            "graph_mode": "off",
            "claim_count_total": 0,
            "unknown_count_total": 0,
            "unknown_rate": 0.0,
        },
        "semantic": {
            "dataset_profile": {
                "local_profile_only_record_count": 1,
                "consistency_corroboration_policy_counts": {"default": 199, "local_profile_only": 1},
                "consistency_corroboration_filter": {"filter_mode": "all"},
                "dataset_manifest_entry": {
                    "dataset_generation_version": "20260312-r7",
                },
            },
            "consistency_target_selection": {
                "include_local_profile_only": False,
                "local_profile_only_docs_total": 1,
                "skipped_local_profile_only_docs": 1,
                "selected_local_profile_only_docs": 0,
            },
        },
    }
    shadow_payload = {
        "doc_count": 1,
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "timings_ms": {
            "index_fts": 10.0,
            "index_vec": 20.0,
            "consistency_p95": 800.0,
            "retrieval_fts_p95": 15.0,
        },
        "graph": {"enabled": False},
        "graph_runtime": {"applied_count": 0},
        "consistency_runtime": {
            "graph_mode": "off",
            "claim_count_total": 1,
            "unknown_count_total": 1,
            "unknown_rate": 1.0,
            "unknown_reason_counts": {"NO_EVIDENCE": 1},
        },
        "semantic": {
            "dataset_profile": {
                "local_profile_only_record_count": 1,
                "consistency_corroboration_policy_counts": {"local_profile_only": 1},
                "consistency_corroboration_filter": {"filter_mode": "only_local_profile_only"},
                "dataset_manifest_entry": {
                    "dataset_generation_version": "20260312-r7",
                },
            },
            "consistency_target_selection": {
                "include_local_profile_only": True,
                "local_profile_only_docs_total": 1,
                "skipped_local_profile_only_docs": 0,
                "selected_local_profile_only_docs": 1,
            },
        },
    }

    _execution_ok, _goal_ok, lines = mod._pipeline_report(pipeline_payload, pipeline_shadow=shadow_payload)
    rendered = "\n".join(lines)

    assert "pipeline_actionability_status: `SEPARATED_TO_SHADOW`" in rendered
    assert "pipeline_shadow_reference_present: `true`" in rendered
    assert "pipeline_shadow_reference_claim_count_total: `1`" in rendered
    assert "pipeline_shadow_reference_unknown_reason_counts: `{'NO_EVIDENCE': 1}`" in rendered


@pytest.mark.unit
def test_pipeline_report_surfaces_latest_attempt_from_summary_row() -> None:
    mod = _import_module()
    payload = {
        "doc_count": 800,
        "dataset_path": "verify/datasets/DS-GROWTH-800.jsonl",
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "timings_ms": {
            "index_fts": 10.0,
            "index_vec": 20.0,
            "consistency_p95": 1200.0,
            "retrieval_fts_p95": 40.0,
        },
        "graph": {"enabled": False},
        "graph_runtime": {"applied_count": 0},
        "consistency_runtime": {"graph_mode": "off", "claim_count_total": 1, "unknown_count_total": 1, "unknown_rate": 1.0},
    }

    _execution_ok, _goal_ok, lines = mod._pipeline_report(
        payload,
        latest_summary_row={
            "latest_successful_file": "20260309T163346Z.json",
            "latest_attempt_file": "failure_20260309T184430Z.json",
            "latest_attempt_status": "consistency_jobs:URLError",
            "latest_attempt_succeeded": False,
        },
    )
    rendered = "\n".join(lines)

    assert "pipeline_latest_successful_file: `20260309T163346Z.json`" in rendered
    assert "pipeline_latest_attempt_file: `failure_20260309T184430Z.json`" in rendered
    assert "pipeline_latest_attempt_status: `consistency_jobs:URLError`" in rendered
    assert "pipeline_latest_attempt_succeeded: `false`" in rendered


@pytest.mark.unit
def test_pipeline_report_surfaces_slot_diagnostic_schema_status() -> None:
    mod = _import_module()
    payload = {
        "doc_count": 800,
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "timings_ms": {
            "index_fts": 10.0,
            "index_vec": 20.0,
            "consistency_p95": 1200.0,
            "retrieval_fts_p95": 40.0,
        },
        "graph": {"enabled": False},
        "graph_runtime": {"applied_count": 0},
        "consistency_runtime": {
            "graph_mode": "off",
            "claim_count_total": 12,
            "unknown_count_total": 10,
            "unknown_rate": 0.8333,
            "slot_diagnostics_schema_status": "MIXED",
            "slot_diagnostics_present_jobs": 60,
            "slot_diagnostics_missing_jobs": 40,
            "slot_diagnostics_missing_with_claims_jobs": 6,
        },
    }

    _execution_ok, _goal_ok, lines = mod._pipeline_report(payload)
    rendered = "\n".join(lines)

    assert "pipeline_slot_diagnostics_schema_status: `MIXED`" in rendered
    assert "pipeline_slot_diagnostics_missing_jobs: `40`" in rendered
    assert "pipeline_slot_diagnostics_missing_with_claims_jobs: `6`" in rendered


@pytest.mark.unit
def test_shadow_report_surfaces_secondary_lane_details_without_primary_gate_effect() -> None:
    mod = _import_module()
    payload = {
        "doc_count": 1,
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "timings_ms": {
            "index_fts": 10.0,
            "index_vec": 20.0,
            "consistency_p95": 800.0,
            "retrieval_fts_p95": 15.0,
        },
        "graph": {"enabled": False},
        "graph_runtime": {"applied_count": 0},
        "consistency_runtime": {
            "graph_mode": "off",
            "claim_count_total": 1,
            "unknown_count_total": 1,
            "violate_count_total": 0,
            "unknown_rate": 1.0,
            "unknown_reason_counts": {"NO_EVIDENCE": 1},
        },
        "semantic": {
            "dataset_profile": {
                "local_profile_only_record_count": 1,
                "consistency_corroboration_policy_counts": {"local_profile_only": 1},
                "consistency_corroboration_filter": {"filter_mode": "only_local_profile_only"},
                "dataset_manifest_entry": {
                    "dataset_generation_version": "20260312-r7",
                },
            },
            "consistency_target_selection": {
                "include_local_profile_only": True,
                "local_profile_only_docs_total": 1,
                "skipped_local_profile_only_docs": 0,
                "selected_local_profile_only_docs": 1,
            },
        },
    }

    execution_ok, goal_ok, lines = mod._shadow_report(payload)
    rendered = "\n".join(lines)

    assert execution_ok is True
    assert goal_ok is True
    assert "shadow_secondary_only: `true`" in rendered
    assert "shadow_goal_in_overall_gate: `false`" in rendered
    assert "shadow_claim_count_total: `1`" in rendered
    assert "shadow_unknown_reason_counts:" in rendered
    assert "shadow_corroboration_lane: `shadow_local_profile_only`" in rendered


@pytest.mark.unit
def test_main_keeps_overall_goal_from_pipeline_and_soak_when_shadow_lane_is_only_secondary(tmp_path: Path) -> None:
    mod = _import_module()
    pipeline_path = tmp_path / "pipeline.json"
    soak_path = tmp_path / "soak.json"
    shadow_path = tmp_path / "shadow.json"
    output_path = tmp_path / "report.md"

    pipeline_path.write_text(
        """{
  "doc_count": 200,
  "status": {
    "index_fts": "SUCCEEDED",
    "index_vec": "SUCCEEDED",
    "ingest_failures": 0,
    "consistency_failures": 0,
    "retrieve_vec_failures": 0
  },
  "timings_ms": {
    "index_fts": 10.0,
    "index_vec": 20.0,
    "consistency_p95": 1200.0,
    "retrieval_fts_p95": 40.0
  },
  "graph": {"enabled": false},
  "graph_runtime": {"applied_count": 0},
  "consistency_runtime": {"graph_mode": "off"},
  "repro": {"run_manifest": {"git_sha": "abc123"}}
}""",
        encoding="utf-8",
    )
    soak_path.write_text(
        """{
  "failed_ratio": 0.0,
  "orchestrator_crashes": 0,
  "queue_lag_p95_ms": 1000.0,
  "rss_drift_pct": 0.0,
  "consistency_p95_ms": 1400.0,
  "hours_target": 0.5,
  "timings_ms": {
    "queue_lag_all_p95": 1000.0,
    "queue_lag_consistency_p95": 1000.0
  },
  "graph": {"enabled": false},
  "graph_runtime": {"jobs_applied": 0}
}""",
        encoding="utf-8",
    )
    shadow_path.write_text(
        """{
  "doc_count": 1,
  "status": {
    "index_fts": "SUCCEEDED",
    "index_vec": "SUCCEEDED",
    "ingest_failures": 0,
    "consistency_failures": 1,
    "retrieve_vec_failures": 0
  },
  "timings_ms": {
    "index_fts": 10.0,
    "index_vec": 20.0,
    "consistency_p95": 800.0,
    "retrieval_fts_p95": 15.0
  },
  "graph": {"enabled": false},
  "graph_runtime": {"applied_count": 0},
  "consistency_runtime": {
    "graph_mode": "off",
    "claim_count_total": 1,
    "unknown_count_total": 1,
    "violate_count_total": 0,
    "unknown_rate": 1.0,
    "unknown_reason_counts": {"NO_EVIDENCE": 1}
  }
}""",
        encoding="utf-8",
    )

    old_argv = sys.argv
    try:
        sys.argv = [
            "render_gate_report.py",
            "--pipeline",
            str(pipeline_path),
            "--pipeline-shadow",
            str(shadow_path),
            "--soak",
            str(soak_path),
            "--output",
            str(output_path),
        ]
        assert mod.main() == 0
    finally:
        sys.argv = old_argv

    rendered = output_path.read_text(encoding="utf-8")
    assert "## Shadow Lane" in rendered
    assert "- shadow_goal_achieved: `FAIL`" in rendered
    assert "- goal_achieved: `PASS`" in rendered
