from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


def _import_module():
    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        sys.modules.pop("summarize_latest_metrics", None)
        return importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))


def _write_bench(
    path: Path,
    *,
    bench_label: str = "ws4-quick-ab:DS-200-baseline-r21",
    selection_override: dict | None = None,
    filter_override: dict | None = None,
    runtime_override: dict | None = None,
) -> None:
    payload = {
        "doc_count": 200,
        "finished_at": "2026-03-08T11:48:38Z",
        "dataset_path": "verify/datasets/DS-GROWTH-200.jsonl",
        "bench_label": bench_label,
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "timings_ms": {
            "consistency_p95": 1234.0,
            "retrieval_fts_p95": 45.0,
        },
        "consistency_runtime": {
            "claim_count_total": 0,
            "unknown_count_total": 0,
            "violate_count_total": 0,
            "unknown_rate": 0.0,
            "violate_rate": 0.0,
            "slot_detection_rate": 0.0,
            "claims_skipped_low_confidence_rate": 0.0,
            "triage_selection_rate": 0.0,
            "unknown_reason_counts": {},
            **(runtime_override or {}),
        },
        "semantic": {
            "dataset_profile": {
                "local_profile_only_record_count": 1,
                "consistency_corroboration_policy_counts": {
                    "default": 199,
                    "local_profile_only": 1,
                },
                "consistency_corroboration_filter": filter_override or {
                    "filter_mode": "all",
                    "selected_record_count": 200,
                },
                "dataset_manifest_entry": {
                    "dataset_generation_version": "20260312-r7",
                    "composite_source_policy": "exclude_fallback_sources_unless_empty",
                    "source_policy_registry_version": "20260307-r1",
                    "manual_review_source_count": 1,
                    "local_profile_only_record_count": 1,
                    "consistency_corroboration_policy_counts": {
                        "default": 199,
                        "local_profile_only": 1,
                    },
                },
            },
            "consistency_target_selection": selection_override or {
                "include_local_profile_only": False,
                "local_profile_only_docs_total": 1,
                "skipped_local_profile_only_docs": 1,
                "selected_local_profile_only_docs": 0,
            },
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.unit
def test_summary_surfaces_corroboration_lane_metadata(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    _write_bench(bench_dir / "20260308T114838Z.json")

    mod = _import_module()
    summary = mod.summarize_benchmarks(bench_dir, datasets=("DS-200",))
    ds200 = summary["datasets"]["DS-200"]

    assert ds200["latest_dataset_generation_version"] == "20260312-r7"
    assert ds200["latest_composite_source_policy"] == "exclude_fallback_sources_unless_empty"
    assert ds200["latest_source_policy_registry_version"] == "20260307-r1"
    assert ds200["latest_manual_review_source_count"] == 1
    assert ds200["latest_local_profile_only_record_count"] == 1
    assert ds200["latest_corroboration_lane"] == "mainline_excludes_local_profile_only"
    assert ds200["latest_consistency_target_selection"]["skipped_local_profile_only_docs"] == 1


@pytest.mark.unit
def test_render_markdown_includes_corroboration_lane_section(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    _write_bench(bench_dir / "20260308T114838Z.json")

    mod = _import_module()
    summary = mod.summarize_benchmarks(bench_dir, datasets=("DS-200",))
    markdown = mod.render_markdown(summary)

    assert "## Corroboration Lane" in markdown
    assert "generation=`20260312-r7`" in markdown
    assert "lane=`mainline_excludes_local_profile_only`" in markdown


@pytest.mark.unit
def test_summary_surfaces_two_lane_actionability_with_shadow_reference(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    _write_bench(
        bench_dir / "20260308T114838Z.json",
        bench_label="operational-main:DS-200",
    )
    _write_bench(
        bench_dir / "20260308T114345Z.json",
        bench_label="operational-shadow:local-profile-only",
        selection_override={
            "include_local_profile_only": True,
            "local_profile_only_docs_total": 1,
            "skipped_local_profile_only_docs": 0,
            "selected_local_profile_only_docs": 1,
        },
        filter_override={
            "filter_mode": "only_local_profile_only",
            "selected_record_count": 1,
        },
        runtime_override={
            "claim_count_total": 1,
            "unknown_count_total": 1,
            "unknown_rate": 1.0,
            "unknown_reason_counts": {"NO_EVIDENCE": 1},
        },
    )

    mod = _import_module()
    summary = mod.summarize_benchmarks(bench_dir, datasets=("DS-200",), label_mode="operational")
    ds200 = summary["datasets"]["DS-200"]

    assert ds200["latest_actionability_status"] == "SEPARATED_TO_SHADOW"
    assert ds200["latest_consistency_runtime"]["claim_count_total"] == 0
    assert ds200["latest_shadow_reference"]["file"] == "20260308T114345Z.json"
    assert ds200["latest_shadow_reference"]["corroboration_lane"] == "shadow_local_profile_only"
    assert ds200["latest_shadow_reference"]["consistency_runtime"]["claim_count_total"] == 1
    assert ds200["latest_shadow_reference"]["consistency_runtime"]["unknown_reason_counts"]["NO_EVIDENCE"] == 1

    markdown = mod.render_markdown(summary)
    assert "## Actionability View" in markdown
    assert "status=`SEPARATED_TO_SHADOW`" in markdown


@pytest.mark.unit
def test_summary_preserves_slot_diagnostic_schema_status_in_runtime_view(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    _write_bench(
        bench_dir / "20260309T152007Z.json",
        bench_label="operational-main:DS-200",
        runtime_override={
            "claim_count_total": 4,
            "unknown_count_total": 4,
            "unknown_rate": 1.0,
            "claim_slot_counts": {"relation": 2, "age": 1},
            "unknown_slot_counts": {"relation": 2},
            "no_evidence_slot_counts": {"relation": 1},
            "slot_diagnostics_schema_status": "MIXED",
            "slot_diagnostics_present_jobs": 2,
            "slot_diagnostics_partial_jobs": 0,
            "slot_diagnostics_missing_jobs": 3,
            "slot_diagnostics_missing_with_claims_jobs": 1,
            "slot_diagnostics_complete_job_rate": 0.4,
            "slot_diagnostics_missing_with_claims_rate": 0.25,
        },
    )

    mod = _import_module()
    summary = mod.summarize_benchmarks(bench_dir, datasets=("DS-200",), label_mode="operational")
    ds200 = summary["datasets"]["DS-200"]
    runtime = ds200["latest_consistency_runtime"]

    assert runtime["slot_diagnostics_schema_status"] == "MIXED"
    assert runtime["slot_diagnostics_present_jobs"] == 2
    assert runtime["slot_diagnostics_missing_jobs"] == 3
    assert runtime["slot_diagnostics_missing_with_claims_jobs"] == 1
    assert runtime["slot_diagnostics_complete_job_rate"] == pytest.approx(0.4)
    assert runtime["slot_diagnostics_missing_with_claims_rate"] == pytest.approx(0.25)
    assert runtime["claim_slot_counts"] == {"relation": 2, "age": 1}
    assert runtime["unknown_slot_counts"] == {"relation": 2}
    assert runtime["no_evidence_slot_counts"] == {"relation": 1}

    markdown = mod.render_markdown(summary)
    assert "slot_diag=`MIXED`" in markdown
