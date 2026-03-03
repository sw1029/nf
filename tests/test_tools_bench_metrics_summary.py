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
) -> None:
    payload = {
        "doc_count": doc_count,
        "finished_at": finished_at,
        "dataset_path": dataset_path or f"verify/datasets/DS-GROWTH-{doc_count}.jsonl",
        "timings_ms": {
            "consistency_p95": consistency_p95,
            "retrieval_fts_p95": retrieval_fts_p95,
        },
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
