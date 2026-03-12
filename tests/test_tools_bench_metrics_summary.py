from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


def _write_bench(
    path: Path,
    *,
    doc_count: int,
    finished_at: str,
    consistency_p95: float,
    retrieval_fts_p95: float,
    dataset_path: str | None = None,
    bench_label: str | None = None,
    status: dict[str, object] | None = None,
    artifact_cohort: str | None = None,
) -> None:
    payload = {
        "doc_count": doc_count,
        "finished_at": finished_at,
        "dataset_path": dataset_path or f"verify/datasets/DS-GROWTH-{doc_count}.jsonl",
        "bench_label": bench_label or "",
        "artifact_cohort": artifact_cohort or "",
        "status": status or {},
        "timings_ms": {
            "consistency_p95": consistency_p95,
            "retrieval_fts_p95": retrieval_fts_p95,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_failure(
    path: Path,
    *,
    dataset_path: str,
    bench_label: str,
    attempt_stage: str,
    error_class: str,
    generated_at_utc: str = "2026-03-07T08:00:00Z",
) -> None:
    payload = {
        "generated_at_utc": generated_at_utc,
        "ok": False,
        "failure_kind": "bench_transport_or_frontdoor",
        "dataset_path": dataset_path,
        "bench_label": bench_label,
        "attempt_stage": attempt_stage,
        "error_class": error_class,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.unit
def test_bench_latest_metrics_summary_detects_trend_and_status(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260220T100000Z.json",
        doc_count=200,
        finished_at="2026-02-20T10:00:00Z",
        consistency_p95=100.0,
        retrieval_fts_p95=50.0,
    )
    _write_bench(
        bench_dir / "20260221T100000Z.json",
        doc_count=200,
        finished_at="2026-02-21T10:00:00Z",
        consistency_p95=130.0,
        retrieval_fts_p95=52.0,
    )
    _write_bench(
        bench_dir / "20260220T110000Z.json",
        doc_count=400,
        finished_at="2026-02-20T11:00:00Z",
        consistency_p95=200.0,
        retrieval_fts_p95=80.0,
    )
    _write_bench(
        bench_dir / "20260221T110000Z.json",
        doc_count=400,
        finished_at="2026-02-21T11:00:00Z",
        consistency_p95=205.0,
        retrieval_fts_p95=92.0,
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(bench_dir)
    ds200 = summary["datasets"]["DS-200"]
    ds400 = summary["datasets"]["DS-400"]
    ds800 = summary["datasets"]["DS-800"]

    assert ds200["status"] == "FAIL"
    assert ds200["metric_status"]["consistency_p95"] == "HARD_FAIL"
    assert ds400["status"] == "WARN"
    assert ds400["metric_status"]["retrieval_fts_p95"] == "SOFT_WARNING"
    assert ds800["status"] == "MISSING"
    assert summary["overall_status"] == "FAIL"

    markdown = summary_mod.render_markdown(summary)
    assert "Latest Metrics Summary" in markdown
    assert "| DS-200 |" in markdown
    assert "| DS-800 |" in markdown


@pytest.mark.unit
def test_bench_latest_metrics_summary_supports_diversity_keys_and_no_baseline_warn(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260301T100000Z.json",
        doc_count=200,
        finished_at="2026-03-01T10:00:00Z",
        consistency_p95=210.0,
        retrieval_fts_p95=120.0,
        dataset_path="verify/datasets/DS-DIVERSE-200.jsonl",
    )
    _write_bench(
        bench_dir / "20260301T110000Z.json",
        doc_count=400,
        finished_at="2026-03-01T11:00:00Z",
        consistency_p95=410.0,
        retrieval_fts_p95=160.0,
        dataset_path="verify/datasets/DS-DIVERSE-400.jsonl",
    )
    _write_bench(
        bench_dir / "20260301T120000Z.json",
        doc_count=200,
        finished_at="2026-03-01T12:00:00Z",
        consistency_p95=999.0,
        retrieval_fts_p95=999.0,
        dataset_path="verify/datasets/DS-CONTROL-D.jsonl",
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    datasets = ("DS-DIVERSE-200", "DS-DIVERSE-400", "DS-DIVERSE-800")
    summary = summary_mod.summarize_benchmarks(bench_dir, datasets=datasets)

    ds200 = summary["datasets"]["DS-DIVERSE-200"]
    ds400 = summary["datasets"]["DS-DIVERSE-400"]
    ds800 = summary["datasets"]["DS-DIVERSE-800"]
    assert ds200["status"] == "NO_BASELINE"
    assert ds400["status"] == "NO_BASELINE"
    assert ds800["status"] == "MISSING"
    assert summary["rule_evaluation"]["no_baseline"] is True
    assert summary["overall_status"] == "WARN"

    markdown = summary_mod.render_markdown(summary)
    assert "| DS-DIVERSE-200 |" in markdown
    assert "| DS-DIVERSE-800 |" in markdown


@pytest.mark.unit
def test_bench_latest_metrics_summary_label_filter_avoids_matrix_operational_mix(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    # Operational baseline (should be chosen when label filter is enabled)
    _write_bench(
        bench_dir / "20260301T100000Z.json",
        doc_count=200,
        finished_at="2026-03-01T10:00:00Z",
        consistency_p95=100.0,
        retrieval_fts_p95=50.0,
        dataset_path="verify/datasets/DS-GROWTH-200.jsonl",
        bench_label="operational-main:DS-200",
    )
    # Matrix artifact that should not be used as operational baseline
    _write_bench(
        bench_dir / "20260301T101000Z.json",
        doc_count=200,
        finished_at="2026-03-01T10:10:00Z",
        consistency_p95=80.0,
        retrieval_fts_p95=50.0,
        dataset_path="verify/datasets/DS-GROWTH-200.jsonl",
        bench_label="matrix-DS200-run1-on",
    )
    # Latest operational run
    _write_bench(
        bench_dir / "20260301T102000Z.json",
        doc_count=200,
        finished_at="2026-03-01T10:20:00Z",
        consistency_p95=102.0,
        retrieval_fts_p95=50.0,
        dataset_path="verify/datasets/DS-GROWTH-200.jsonl",
        bench_label="operational-main:DS-200",
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    # Old behavior equivalent: dataset-only comparison can pick matrix as previous and hard-fail.
    unfiltered = summary_mod.summarize_benchmarks(bench_dir, datasets=("DS-200",))
    assert unfiltered["datasets"]["DS-200"]["status"] == "FAIL"
    assert unfiltered["overall_status"] == "FAIL"

    # New behavior: only operational-main artifacts are eligible for baseline/trend comparison.
    filtered = summary_mod.summarize_benchmarks(
        bench_dir,
        datasets=("DS-200",),
        label_prefixes=("operational-main:",),
        strict_label_filter=True,
    )
    assert filtered["datasets"]["DS-200"]["latest_file"] == "20260301T102000Z.json"
    assert filtered["datasets"]["DS-200"]["previous_file"] == "20260301T100000Z.json"
    assert filtered["datasets"]["DS-200"]["status"] == "PASS"
    assert filtered["overall_status"] == "PASS"


@pytest.mark.unit
def test_bench_latest_metrics_summary_operational_label_mode_applies_preset(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260301T100000Z.json",
        doc_count=400,
        finished_at="2026-03-01T10:00:00Z",
        consistency_p95=2400.0,
        retrieval_fts_p95=80.0,
        dataset_path="verify/datasets/DS-GROWTH-400.jsonl",
        bench_label="operational-main:DS-400",
    )
    _write_bench(
        bench_dir / "20260301T101000Z.json",
        doc_count=400,
        finished_at="2026-03-01T10:10:00Z",
        consistency_p95=1900.0,
        retrieval_fts_p95=70.0,
        dataset_path="verify/datasets/DS-GROWTH-400.jsonl",
        bench_label="matrix-DS400-run1-off",
    )
    _write_bench(
        bench_dir / "20260301T102000Z.json",
        doc_count=400,
        finished_at="2026-03-01T10:20:00Z",
        consistency_p95=2450.0,
        retrieval_fts_p95=82.0,
        dataset_path="verify/datasets/DS-GROWTH-400.jsonl",
        bench_label="operational-main:DS-400",
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(
        bench_dir,
        datasets=("DS-400",),
        label_mode="operational",
    )
    ds400 = summary["datasets"]["DS-400"]

    assert ds400["latest_file"] == "20260301T102000Z.json"
    assert ds400["previous_file"] == "20260301T100000Z.json"
    assert ds400["status"] == "PASS"
    assert ds400["absolute_status"] == "PASS"
    assert summary["label_filter"]["mode"] == "operational"
    assert summary["label_filter"]["strict_label_filter"] is True
    assert summary["label_filter"]["prefixes"] == ["operational-main:", "operational-diversity-main:"]
    assert summary["overall_status"] == "WARN"


@pytest.mark.unit
def test_bench_latest_metrics_summary_excludes_unsuccessful_pipeline_artifacts(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260301T100000Z.json",
        doc_count=800,
        finished_at="2026-03-01T10:00:00Z",
        consistency_p95=2200.0,
        retrieval_fts_p95=60.0,
        dataset_path="verify/datasets/DS-GROWTH-800.jsonl",
        bench_label="operational-main:DS-800",
        status={
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
    )
    _write_bench(
        bench_dir / "20260301T101000Z.json",
        doc_count=800,
        finished_at="2026-03-01T10:10:00Z",
        consistency_p95=1900.0,
        retrieval_fts_p95=55.0,
        dataset_path="verify/datasets/DS-GROWTH-800.jsonl",
        bench_label="operational-main:DS-800",
        status={
            "index_fts": "FAILED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(
        bench_dir,
        datasets=("DS-800",),
        label_mode="operational",
    )
    ds800 = summary["datasets"]["DS-800"]

    assert ds800["latest_file"] == "20260301T100000Z.json"
    assert ds800["latest_successful_file"] == "20260301T100000Z.json"
    assert ds800["latest_attempt_file"] == "20260301T101000Z.json"
    assert ds800["latest_attempt_status"] == "index_fts:FAILED"
    assert ds800["latest_attempt_succeeded"] is False
    assert ds800["status"] == "NO_BASELINE"
    assert summary["label_filter"]["excluded_unsuccessful_status"] == 1


@pytest.mark.unit
def test_bench_latest_metrics_summary_separates_trend_status_from_absolute_goal_status(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260307T100000Z.json",
        doc_count=800,
        finished_at="2026-03-07T10:00:00Z",
        consistency_p95=11796.49,
        retrieval_fts_p95=27.90,
        dataset_path="verify/datasets/DS-DIVERSE-800.jsonl",
        bench_label="operational-diversity-main:DS-DIVERSE-800",
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(bench_dir, datasets=("DS-DIVERSE-800",))
    ds800 = summary["datasets"]["DS-DIVERSE-800"]

    assert ds800["status"] == "NO_BASELINE"
    assert ds800["absolute_metric_status"]["consistency_p95"] == "FAIL"
    assert ds800["absolute_metric_status"]["retrieval_fts_p95"] == "PASS"
    assert ds800["absolute_status"] == "FAIL"
    assert summary["overall_status"] == "WARN"
    assert summary["absolute_goal_status"] == "FAIL"

    markdown = summary_mod.render_markdown(summary)
    assert "overall_status (trend_relative)" in markdown
    assert "absolute_goal_status" in markdown


@pytest.mark.unit
def test_bench_latest_metrics_summary_surfaces_latest_attempt_without_overwriting_latest_successful(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260307T060000Z.json",
        doc_count=400,
        finished_at="2026-03-07T06:00:00Z",
        consistency_p95=2200.0,
        retrieval_fts_p95=40.0,
        dataset_path="verify/datasets/DS-GROWTH-400.jsonl",
        bench_label="operational-main:DS-400",
        status={
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
    )
    _write_bench(
        bench_dir / "20260307T070000Z.json",
        doc_count=400,
        finished_at="2026-03-07T07:00:00Z",
        consistency_p95=1800.0,
        retrieval_fts_p95=35.0,
        dataset_path="verify/datasets/DS-GROWTH-400.jsonl",
        bench_label="operational-main:DS-400",
        status={
            "index_fts": "FAILED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(
        bench_dir,
        datasets=("DS-400",),
        label_mode="operational",
    )
    ds400 = summary["datasets"]["DS-400"]

    assert ds400["latest_file"] == "20260307T060000Z.json"
    assert ds400["latest_successful_file"] == "20260307T060000Z.json"
    assert ds400["latest_attempt_file"] == "20260307T070000Z.json"
    assert ds400["latest_attempt_status"] == "index_fts:FAILED"
    assert ds400["latest_attempt_succeeded"] is False

    markdown = summary_mod.render_markdown(summary)
    assert "20260307T070000Z.json (index_fts:FAILED)" in markdown


@pytest.mark.unit
def test_bench_latest_metrics_summary_tracks_failure_artifact_as_latest_attempt(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260307T060000Z.json",
        doc_count=800,
        finished_at="2026-03-07T06:00:00Z",
        consistency_p95=2200.0,
        retrieval_fts_p95=40.0,
        dataset_path="verify/datasets/DS-GROWTH-800.jsonl",
        bench_label="operational-main:DS-800",
        status={
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
    )
    _write_failure(
        bench_dir / "failure_20260307T080000Z.json",
        dataset_path="verify/datasets/DS-GROWTH-800.jsonl",
        bench_label="operational-main:DS-800",
        attempt_stage="index_vec",
        error_class="RemoteDisconnected",
        generated_at_utc="2026-03-07T08:00:00Z",
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(
        bench_dir,
        datasets=("DS-800",),
        label_mode="operational",
    )
    ds800 = summary["datasets"]["DS-800"]

    assert ds800["latest_successful_file"] == "20260307T060000Z.json"
    assert ds800["latest_attempt_file"] == "failure_20260307T080000Z.json"
    assert ds800["latest_attempt_status"] == "index_vec:RemoteDisconnected"
    assert ds800["latest_attempt_succeeded"] is False


@pytest.mark.unit
def test_bench_latest_metrics_summary_prefers_canonical_operational_cohort_when_present(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260309T080000Z.json",
        doc_count=200,
        finished_at="2026-03-09T08:00:00Z",
        consistency_p95=100.0,
        retrieval_fts_p95=50.0,
        dataset_path="verify/datasets/DS-GROWTH-200.jsonl",
        bench_label="operational-main:DS-200",
        artifact_cohort="operational_closeout",
    )
    _write_bench(
        bench_dir / "20260309T081000Z.json",
        doc_count=200,
        finished_at="2026-03-09T08:10:00Z",
        consistency_p95=101.0,
        retrieval_fts_p95=51.0,
        dataset_path="verify/datasets/DS-GROWTH-200.jsonl",
        bench_label="operational-main:DS-200",
        artifact_cohort="operational_closeout",
    )
    _write_bench(
        bench_dir / "20260309T082000Z.json",
        doc_count=200,
        finished_at="2026-03-09T08:20:00Z",
        consistency_p95=80.0,
        retrieval_fts_p95=40.0,
        dataset_path="verify/datasets/DS-GROWTH-200.jsonl",
        bench_label="operational-main:DS-200",
        artifact_cohort="",
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(
        bench_dir,
        datasets=("DS-200",),
        label_mode="operational",
    )
    ds200 = summary["datasets"]["DS-200"]

    assert ds200["latest_file"] == "20260309T081000Z.json"
    assert ds200["previous_file"] == "20260309T080000Z.json"
    assert ds200["latest_attempt_file"] == "20260309T082000Z.json"
    assert summary["label_filter"]["preferred_artifact_cohort"] == "operational_closeout"
    assert summary["label_filter"]["excluded_artifact_cohort_mismatch"] >= 1
    assert "DS-200" in summary["label_filter"]["artifact_cohort_filter_applied_datasets"]

    markdown = summary_mod.render_markdown(summary)
    assert "20260309T082000Z.json (SUCCEEDED)" in markdown


@pytest.mark.unit
def test_bench_latest_metrics_summary_keeps_older_operational_baseline_when_only_latest_has_cohort(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260309T070000Z.json",
        doc_count=400,
        finished_at="2026-03-09T07:00:00Z",
        consistency_p95=100.0,
        retrieval_fts_p95=50.0,
        dataset_path="verify/datasets/DS-GROWTH-400.jsonl",
        bench_label="operational-main:DS-400",
        artifact_cohort="",
    )
    _write_bench(
        bench_dir / "20260309T071000Z.json",
        doc_count=400,
        finished_at="2026-03-09T07:10:00Z",
        consistency_p95=101.0,
        retrieval_fts_p95=51.0,
        dataset_path="verify/datasets/DS-GROWTH-400.jsonl",
        bench_label="operational-main:DS-400",
        artifact_cohort="operational_closeout",
    )
    _write_bench(
        bench_dir / "20260309T072000Z.json",
        doc_count=400,
        finished_at="2026-03-09T07:20:00Z",
        consistency_p95=80.0,
        retrieval_fts_p95=40.0,
        dataset_path="verify/datasets/DS-GROWTH-400.jsonl",
        bench_label="operational-main:DS-400",
        artifact_cohort="",
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(
        bench_dir,
        datasets=("DS-400",),
        label_mode="operational",
    )
    ds400 = summary["datasets"]["DS-400"]

    assert ds400["latest_file"] == "20260309T071000Z.json"
    assert ds400["previous_file"] == "20260309T070000Z.json"
    assert ds400["latest_attempt_file"] == "20260309T072000Z.json"


@pytest.mark.unit
def test_bench_latest_metrics_summary_keeps_newer_failure_attempt_visible_after_cohort_filter(tmp_path: Path) -> None:
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)

    _write_bench(
        bench_dir / "20260309T080000Z.json",
        doc_count=800,
        finished_at="2026-03-09T08:00:00Z",
        consistency_p95=120.0,
        retrieval_fts_p95=55.0,
        dataset_path="verify/datasets/DS-GROWTH-800.jsonl",
        bench_label="operational-main:DS-800",
        artifact_cohort="operational_closeout",
        status={
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
    )
    _write_bench(
        bench_dir / "20260309T081000Z.json",
        doc_count=800,
        finished_at="2026-03-09T08:10:00Z",
        consistency_p95=121.0,
        retrieval_fts_p95=56.0,
        dataset_path="verify/datasets/DS-GROWTH-800.jsonl",
        bench_label="operational-main:DS-800",
        artifact_cohort="operational_closeout",
        status={
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
    )
    _write_failure(
        bench_dir / "failure_20260309T083000Z.json",
        dataset_path="verify/datasets/DS-GROWTH-800.jsonl",
        bench_label="operational-main:DS-800",
        attempt_stage="consistency_jobs",
        error_class="URLError",
        generated_at_utc="2026-03-09T08:30:00Z",
    )

    bench_tools_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_tools_dir))
    try:
        summary_mod = importlib.import_module("summarize_latest_metrics")
    finally:
        if str(bench_tools_dir) in sys.path:
            sys.path.remove(str(bench_tools_dir))

    summary = summary_mod.summarize_benchmarks(
        bench_dir,
        datasets=("DS-800",),
        label_mode="operational",
    )
    ds800 = summary["datasets"]["DS-800"]

    assert ds800["latest_file"] == "20260309T081000Z.json"
    assert ds800["latest_attempt_file"] == "failure_20260309T083000Z.json"
    assert ds800["latest_attempt_status"] == "consistency_jobs:URLError"
    assert ds800["latest_attempt_succeeded"] is False
