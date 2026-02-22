from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"missing artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _pipeline_thresholds(doc_count: int) -> tuple[float, float]:
    # Aligned with current policy notes in IMPLEMENTATION_STATUS:
    # retrieval_fts_p95: DS-200 <= 300ms, DS-800 <= 450ms
    # consistency_p95: global gate <= 2500ms
    retrieval_fts_target = 300.0 if doc_count <= 200 else 450.0
    consistency_target = 2500.0
    return retrieval_fts_target, consistency_target


def _render_bool(value: bool) -> str:
    return "PASS" if value else "FAIL"


def _pipeline_report(payload: dict[str, Any], baseline: dict[str, Any] | None = None) -> tuple[bool, bool, list[str]]:
    status = payload.get("status") or {}
    timings = payload.get("timings_ms") or {}
    consistency_runtime = payload.get("consistency_runtime") or {}
    doc_count = _as_int(payload.get("doc_count"), 0)

    execution_complete = all(
        key in timings
        for key in ("index_fts", "index_vec", "consistency_p95", "retrieval_fts_p95")
    ) and all(
        key in status
        for key in ("index_fts", "index_vec", "ingest_failures", "consistency_failures")
    )

    retrieval_fts_target, consistency_target = _pipeline_thresholds(doc_count)
    baseline_timings = (baseline or {}).get("timings_ms") or {}
    baseline_consistency = _as_float(baseline_timings.get("consistency_p95"), 0.0)
    baseline_retrieval = _as_float(baseline_timings.get("retrieval_fts_p95"), 0.0)
    current_consistency = _as_float(timings.get("consistency_p95"))
    current_retrieval = _as_float(timings.get("retrieval_fts_p95"))
    consistency_regressed_ok = True
    retrieval_regressed_ok = True
    if baseline_consistency > 0.0:
        consistency_regressed_ok = current_consistency <= (baseline_consistency * 1.10)
    if baseline_retrieval > 0.0:
        retrieval_regressed_ok = current_retrieval <= (baseline_retrieval * 1.10)

    graph_mode = str(consistency_runtime.get("graph_mode") or "off")
    graph_expand_applied_count = _as_int(consistency_runtime.get("graph_expand_applied_count"), 0)
    graph_auto_trigger_count = _as_int(consistency_runtime.get("graph_auto_trigger_count"), 0)
    graph_auto_skip_count = _as_int(consistency_runtime.get("graph_auto_skip_count"), 0)
    auto_total = graph_auto_trigger_count + graph_auto_skip_count
    auto_apply_rate = _safe_ratio(float(graph_auto_trigger_count), float(auto_total))

    goal_checks = {
        "index_jobs_succeeded": status.get("index_fts") == "SUCCEEDED" and status.get("index_vec") == "SUCCEEDED",
        "ingest_failures_zero": _as_int(status.get("ingest_failures")) == 0,
        "consistency_failures_zero": _as_int(status.get("consistency_failures")) == 0,
        "retrieve_vec_failures_zero": _as_int(status.get("retrieve_vec_failures")) == 0,
        "retrieval_fts_p95_gate": current_retrieval <= retrieval_fts_target,
        "consistency_p95_gate": current_consistency <= consistency_target,
        "consistency_p95_regression_le_10pct": consistency_regressed_ok,
        "retrieval_fts_p95_regression_le_10pct": retrieval_regressed_ok,
        "graph_off_applied_zero": graph_mode != "off" or graph_expand_applied_count == 0,
        "graph_auto_apply_rate_le_30pct": graph_mode != "auto" or auto_apply_rate <= 0.30,
    }
    goal_achieved = all(goal_checks.values())

    lines = [
        f"- pipeline_execution_complete: `{_render_bool(execution_complete)}`",
        f"- pipeline_goal_achieved: `{_render_bool(goal_achieved)}`",
        f"- pipeline_doc_count: `{doc_count}`",
        f"- pipeline_retrieval_fts_p95_ms: `{current_retrieval:.2f}` (target <= {retrieval_fts_target:.0f})",
        f"- pipeline_consistency_p95_ms: `{current_consistency:.2f}` (target <= {consistency_target:.0f})",
        f"- pipeline_retrieval_vec_p95_ms: `{_as_float(timings.get('retrieval_vec_p95')):.2f}`",
        f"- baseline_consistency_p95_ms: `{baseline_consistency:.2f}`",
        f"- baseline_retrieval_fts_p95_ms: `{baseline_retrieval:.2f}`",
        f"- pipeline_graph: `{payload.get('graph')}`",
        f"- pipeline_graph_runtime: `{payload.get('graph_runtime')}`",
        f"- pipeline_consistency_runtime: `{consistency_runtime}`",
        f"- consistency_graph_mode: `{graph_mode}`",
        f"- consistency_graph_auto_apply_rate: `{auto_apply_rate:.4f}`",
    ]
    for key, passed in goal_checks.items():
        lines.append(f"- {key}: `{_render_bool(passed)}`")
    return execution_complete, goal_achieved, lines


def _soak_report(payload: dict[str, Any]) -> tuple[bool, bool, list[str]]:
    timings = payload.get("timings_ms") or {}
    execution_complete = all(
        key in payload for key in ("failed_ratio", "orchestrator_crashes", "queue_lag_p95_ms", "rss_drift_pct")
    )

    goal_checks = {
        "failed_ratio_lt_1pct": _as_float(payload.get("failed_ratio"), 1.0) < 0.01,
        "orchestrator_crashes_zero": _as_int(payload.get("orchestrator_crashes"), 1) == 0,
        "queue_lag_p95_lt_60s": _as_float(payload.get("queue_lag_p95_ms"), 999999.0) < 60000.0,
        "rss_drift_lt_15pct": _as_float(payload.get("rss_drift_pct"), 999999.0) < 15.0,
        "consistency_p95_gate": _as_float(payload.get("consistency_p95_ms"), 999999.0) <= 2500.0,
    }
    goal_achieved = all(goal_checks.values())

    lines = [
        f"- soak_execution_complete: `{_render_bool(execution_complete)}`",
        f"- soak_goal_achieved: `{_render_bool(goal_achieved)}`",
        f"- soak_hours_target: `{_as_float(payload.get('hours_target')):.2f}`",
        f"- soak_failed_ratio: `{_as_float(payload.get('failed_ratio')):.6f}`",
        f"- soak_orchestrator_crashes: `{_as_int(payload.get('orchestrator_crashes'))}`",
        f"- soak_queue_lag_all_p95_ms: `{_as_float((timings or {}).get('queue_lag_all_p95')):.2f}`",
        f"- soak_queue_lag_consistency_p95_ms: `{_as_float((timings or {}).get('queue_lag_consistency_p95')):.2f}`",
        f"- soak_consistency_p95_ms: `{_as_float(payload.get('consistency_p95_ms')):.2f}`",
        f"- soak_rss_drift_pct: `{_as_float(payload.get('rss_drift_pct')):.2f}`",
        f"- soak_graph: `{payload.get('graph')}`",
        f"- soak_graph_runtime: `{payload.get('graph_runtime')}`",
    ]
    for key, passed in goal_checks.items():
        lines.append(f"- {key}: `{_render_bool(passed)}`")
    return execution_complete, goal_achieved, lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Render execution-vs-goal gate report from benchmark artifacts.")
    parser.add_argument("--pipeline", type=Path, default=None)
    parser.add_argument("--pipeline-baseline", type=Path, default=None)
    parser.add_argument("--soak", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    pipeline = _load_json(args.pipeline)
    pipeline_baseline = _load_json(args.pipeline_baseline)
    soak = _load_json(args.soak)
    if pipeline is None and soak is None:
        raise SystemExit("at least one of --pipeline or --soak is required")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    git_sha = (
        (((pipeline or {}).get("repro") or {}).get("run_manifest") or {}).get("git_sha")
        or (((soak or {}).get("repro") or {}).get("run_manifest") or {}).get("git_sha")
        or "unknown"
    )

    lines: list[str] = [
        "# Final Gate Report",
        "",
        f"- generated_at_utc: `{now}`",
        f"- git_sha: `{git_sha}`",
    ]
    if args.pipeline is not None:
        lines.append(f"- pipeline_artifact: `{args.pipeline}`")
    if args.pipeline_baseline is not None:
        lines.append(f"- pipeline_baseline_artifact: `{args.pipeline_baseline}`")
    if args.soak is not None:
        lines.append(f"- soak_artifact: `{args.soak}`")
    lines.append("")

    overall_execution = True
    overall_goal = True
    if pipeline is not None:
        execution_ok, goal_ok, report_lines = _pipeline_report(pipeline, pipeline_baseline)
        overall_execution = overall_execution and execution_ok
        overall_goal = overall_goal and goal_ok
        lines.append("## Pipeline")
        lines.extend(report_lines)
        lines.append("")
    if soak is not None:
        execution_ok, goal_ok, report_lines = _soak_report(soak)
        overall_execution = overall_execution and execution_ok
        overall_goal = overall_goal and goal_ok
        lines.append("## Soak")
        lines.extend(report_lines)
        lines.append("")

    lines.extend(
        [
            "## Overall",
            f"- execution_complete: `{_render_bool(overall_execution)}`",
            f"- goal_achieved: `{_render_bool(overall_goal)}`",
        ]
    )

    output = args.output
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = Path("verify/benchmarks") / f"gate_report_{stamp}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
