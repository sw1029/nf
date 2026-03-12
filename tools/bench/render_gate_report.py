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


def _infer_dataset_key(payload: dict[str, Any]) -> str:
    dataset_path = str(payload.get("dataset_path") or "")
    if "DS-GROWTH-200" in dataset_path:
        return "DS-200"
    if "DS-GROWTH-400" in dataset_path:
        return "DS-400"
    if "DS-GROWTH-800" in dataset_path:
        return "DS-800"
    doc_count = _as_int(payload.get("doc_count"), 0)
    return f"DS-{doc_count}" if doc_count in (200, 400, 800) else ""


def _pipeline_thresholds(doc_count: int) -> tuple[float, float]:
    # Aligned with current policy notes in IMPLEMENTATION_STATUS:
    # retrieval_fts_p95: DS-200 <= 300ms, DS-800 <= 450ms
    # consistency_p95: global gate <= 2500ms
    retrieval_fts_target = 300.0 if doc_count <= 200 else 450.0
    consistency_target = 2500.0
    return retrieval_fts_target, consistency_target


def _extract_corroboration_summary(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = payload.get("semantic")
    if not isinstance(semantic, dict):
        return {}
    dataset_profile = semantic.get("dataset_profile")
    if not isinstance(dataset_profile, dict):
        dataset_profile = {}
    manifest_entry = dataset_profile.get("dataset_manifest_entry")
    if not isinstance(manifest_entry, dict):
        manifest_entry = {}
    corroboration_filter = dataset_profile.get("consistency_corroboration_filter")
    if not isinstance(corroboration_filter, dict):
        corroboration_filter = {}
    target_selection = semantic.get("consistency_target_selection")
    if not isinstance(target_selection, dict):
        target_selection = {}
    policy_counts = dataset_profile.get("consistency_corroboration_policy_counts")
    if not isinstance(policy_counts, dict):
        policy_counts = manifest_entry.get("consistency_corroboration_policy_counts")
    if not isinstance(policy_counts, dict):
        policy_counts = {}

    lane = ""
    filter_mode = str(corroboration_filter.get("filter_mode") or "")
    if filter_mode == "only_local_profile_only":
        lane = "shadow_local_profile_only"
    else:
        local_profile_only_docs_total = _as_int(target_selection.get("local_profile_only_docs_total"), 0)
        skipped_local_profile_only_docs = _as_int(target_selection.get("skipped_local_profile_only_docs"), 0)
        if local_profile_only_docs_total > 0 and skipped_local_profile_only_docs > 0:
            lane = "mainline_excludes_local_profile_only"
        elif _as_int(dataset_profile.get("local_profile_only_record_count"), 0) > 0:
            lane = "dataset_contains_local_profile_only"

    return {
        "dataset_generation_version": str(manifest_entry.get("dataset_generation_version") or ""),
        "composite_source_policy": str(manifest_entry.get("composite_source_policy") or ""),
        "source_policy_registry_version": str(manifest_entry.get("source_policy_registry_version") or ""),
        "manual_review_source_count": _as_int(manifest_entry.get("manual_review_source_count"), 0),
        "local_profile_only_record_count": _as_int(
            dataset_profile.get("local_profile_only_record_count", manifest_entry.get("local_profile_only_record_count")),
            0,
        ),
        "consistency_corroboration_policy_counts": dict(policy_counts),
        "consistency_corroboration_filter": dict(corroboration_filter),
        "consistency_target_selection": dict(target_selection),
        "corroboration_lane": lane,
    }


def _extract_consistency_runtime_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    runtime = payload.get("consistency_runtime")
    if not isinstance(runtime, dict):
        semantic = payload.get("semantic")
        if isinstance(semantic, dict):
            runtime = semantic.get("consistency_runtime")
    if not isinstance(runtime, dict):
        runtime = {}
    unknown_reason_counts = runtime.get("unknown_reason_counts")
    if not isinstance(unknown_reason_counts, dict):
        unknown_reason_counts = {}
    claim_slot_counts = runtime.get("claim_slot_counts")
    if not isinstance(claim_slot_counts, dict):
        claim_slot_counts = {}
    unknown_slot_counts = runtime.get("unknown_slot_counts")
    if not isinstance(unknown_slot_counts, dict):
        unknown_slot_counts = {}
    no_evidence_slot_counts = runtime.get("no_evidence_slot_counts")
    if not isinstance(no_evidence_slot_counts, dict):
        no_evidence_slot_counts = {}
    return {
        "claim_count_total": _as_int(runtime.get("claim_count_total"), 0),
        "unknown_count_total": _as_int(runtime.get("unknown_count_total"), 0),
        "violate_count_total": _as_int(runtime.get("violate_count_total"), 0),
        "unknown_rate": _as_float(runtime.get("unknown_rate"), 0.0),
        "jobs_with_claims_total": _as_int(runtime.get("jobs_with_claims_total"), 0),
        "slot_diagnostics_schema_status": str(runtime.get("slot_diagnostics_schema_status") or ""),
        "slot_diagnostics_present_jobs": _as_int(runtime.get("slot_diagnostics_present_jobs"), 0),
        "slot_diagnostics_partial_jobs": _as_int(runtime.get("slot_diagnostics_partial_jobs"), 0),
        "slot_diagnostics_missing_jobs": _as_int(runtime.get("slot_diagnostics_missing_jobs"), 0),
        "slot_diagnostics_missing_with_claims_jobs": _as_int(
            runtime.get("slot_diagnostics_missing_with_claims_jobs"),
            0,
        ),
        "slot_diagnostics_complete_job_rate": _as_float(runtime.get("slot_diagnostics_complete_job_rate"), 0.0),
        "slot_diagnostics_missing_with_claims_rate": _as_float(
            runtime.get("slot_diagnostics_missing_with_claims_rate"),
            0.0,
        ),
        "claim_slot_counts": {str(key): _as_int(value, 0) for key, value in claim_slot_counts.items() if isinstance(key, str)},
        "unknown_slot_counts": {
            str(key): _as_int(value, 0) for key, value in unknown_slot_counts.items() if isinstance(key, str)
        },
        "no_evidence_slot_counts": {
            str(key): _as_int(value, 0) for key, value in no_evidence_slot_counts.items() if isinstance(key, str)
        },
        "unknown_reason_counts": dict(unknown_reason_counts),
    }


def _classify_actionability(
    *,
    pipeline_runtime: dict[str, Any],
    pipeline_lane: str,
    shadow_runtime: dict[str, Any],
    shadow_lane: str,
) -> tuple[str, str]:
    claim_count_total = _as_int(pipeline_runtime.get("claim_count_total"), 0)
    unknown_count_total = _as_int(pipeline_runtime.get("unknown_count_total"), 0)
    violate_count_total = _as_int(pipeline_runtime.get("violate_count_total"), 0)
    shadow_claim_count_total = _as_int(shadow_runtime.get("claim_count_total"), 0)

    if claim_count_total > 0:
        if unknown_count_total >= claim_count_total and violate_count_total == 0:
            return (
                "MAINLINE_ALL_UNKNOWN",
                "mainline claims are present but unresolved; inspect unknown_reason_counts before treating the lane as actionable",
            )
        return ("MAINLINE_ACTIVE", "mainline actionable claims are present")
    if pipeline_lane == "mainline_excludes_local_profile_only":
        if shadow_claim_count_total > 0 and shadow_lane == "shadow_local_profile_only":
            return (
                "SEPARATED_TO_SHADOW",
                "mainline excludes local-profile-only claims; the secondary shadow lane carries the corroboration-only workload",
            )
        return (
            "MAINLINE_EMPTY_AFTER_SEPARATION",
            "mainline excludes local-profile-only claims and no shadow corroboration workload was observed in the supplied shadow reference",
        )
    return ("NO_MAINLINE_CLAIMS", "mainline produced no actionable claims")


def _build_actionability_summary(
    pipeline_payload: dict[str, Any],
    pipeline_shadow_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pipeline_corroboration = _extract_corroboration_summary(pipeline_payload)
    pipeline_runtime = _extract_consistency_runtime_summary(pipeline_payload)
    shadow_corroboration = _extract_corroboration_summary(pipeline_shadow_payload or {})
    shadow_runtime = _extract_consistency_runtime_summary(pipeline_shadow_payload or {})
    status, note = _classify_actionability(
        pipeline_runtime=pipeline_runtime,
        pipeline_lane=str(pipeline_corroboration.get("corroboration_lane") or ""),
        shadow_runtime=shadow_runtime,
        shadow_lane=str(shadow_corroboration.get("corroboration_lane") or ""),
    )
    return {
        "status": status,
        "note": note,
        "pipeline_claim_count_total": _as_int(pipeline_runtime.get("claim_count_total"), 0),
        "pipeline_unknown_count_total": _as_int(pipeline_runtime.get("unknown_count_total"), 0),
        "pipeline_unknown_rate": _as_float(pipeline_runtime.get("unknown_rate"), 0.0),
        "shadow_reference_present": pipeline_shadow_payload is not None,
        "shadow_reference_claim_count_total": _as_int(shadow_runtime.get("claim_count_total"), 0),
        "shadow_reference_unknown_count_total": _as_int(shadow_runtime.get("unknown_count_total"), 0),
        "shadow_reference_unknown_rate": _as_float(shadow_runtime.get("unknown_rate"), 0.0),
        "shadow_reference_unknown_reason_counts": dict(shadow_runtime.get("unknown_reason_counts") or {}),
        "shadow_reference_corroboration_lane": shadow_corroboration.get("corroboration_lane") or "",
    }


def _render_bool(value: bool) -> str:
    return "PASS" if value else "FAIL"


def _load_latest_summary_row(summary_payload: dict[str, Any] | None, pipeline_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary_payload, dict):
        return {}
    datasets = summary_payload.get("datasets")
    if not isinstance(datasets, dict):
        return {}
    dataset_key = _infer_dataset_key(pipeline_payload)
    row = datasets.get(dataset_key)
    return row if isinstance(row, dict) else {}


def _pipeline_report(
    payload: dict[str, Any],
    baseline: dict[str, Any] | None = None,
    pipeline_shadow: dict[str, Any] | None = None,
    latest_summary_row: dict[str, Any] | None = None,
) -> tuple[bool, bool, list[str]]:
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
    corroboration = _extract_corroboration_summary(payload)
    runtime_summary = _extract_consistency_runtime_summary(payload)
    actionability = _build_actionability_summary(payload, pipeline_shadow)

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
        "- pipeline_actionability_secondary_only: `true`",
        f"- pipeline_actionability_status: `{actionability.get('status')}`",
        f"- pipeline_actionability_note: `{actionability.get('note')}`",
        f"- pipeline_claim_count_total: `{actionability.get('pipeline_claim_count_total')}`",
        f"- pipeline_unknown_count_total: `{actionability.get('pipeline_unknown_count_total')}`",
        f"- pipeline_unknown_rate: `{_as_float(actionability.get('pipeline_unknown_rate')):.4f}`",
        f"- pipeline_slot_diagnostics_schema_status: `{runtime_summary.get('slot_diagnostics_schema_status')}`",
        f"- pipeline_slot_diagnostics_missing_jobs: `{runtime_summary.get('slot_diagnostics_missing_jobs')}`",
        f"- pipeline_slot_diagnostics_missing_with_claims_jobs: `{runtime_summary.get('slot_diagnostics_missing_with_claims_jobs')}`",
        f"- pipeline_shadow_reference_present: `{str(bool(actionability.get('shadow_reference_present'))).lower()}`",
        f"- pipeline_shadow_reference_corroboration_lane: `{actionability.get('shadow_reference_corroboration_lane')}`",
        f"- pipeline_shadow_reference_claim_count_total: `{actionability.get('shadow_reference_claim_count_total')}`",
        f"- pipeline_shadow_reference_unknown_count_total: `{actionability.get('shadow_reference_unknown_count_total')}`",
        f"- pipeline_shadow_reference_unknown_rate: `{_as_float(actionability.get('shadow_reference_unknown_rate')):.4f}`",
        f"- pipeline_shadow_reference_unknown_reason_counts: `{actionability.get('shadow_reference_unknown_reason_counts')}`",
    ]
    if latest_summary_row:
        lines.extend(
            [
                f"- pipeline_latest_successful_file: `{latest_summary_row.get('latest_successful_file')}`",
                f"- pipeline_latest_attempt_file: `{latest_summary_row.get('latest_attempt_file')}`",
                f"- pipeline_latest_attempt_status: `{latest_summary_row.get('latest_attempt_status')}`",
                f"- pipeline_latest_attempt_succeeded: `{str(bool(latest_summary_row.get('latest_attempt_succeeded'))).lower()}`",
            ]
        )
    if corroboration:
        lines.extend(
            [
                f"- pipeline_dataset_generation_version: `{corroboration.get('dataset_generation_version')}`",
                f"- pipeline_composite_source_policy: `{corroboration.get('composite_source_policy')}`",
                f"- pipeline_source_policy_registry_version: `{corroboration.get('source_policy_registry_version')}`",
                f"- pipeline_manual_review_source_count: `{corroboration.get('manual_review_source_count')}`",
                f"- pipeline_local_profile_only_record_count: `{corroboration.get('local_profile_only_record_count')}`",
                f"- pipeline_corroboration_lane: `{corroboration.get('corroboration_lane')}`",
                f"- pipeline_consistency_corroboration_policy_counts: `{corroboration.get('consistency_corroboration_policy_counts')}`",
                f"- pipeline_consistency_corroboration_filter: `{corroboration.get('consistency_corroboration_filter')}`",
                f"- pipeline_consistency_target_selection: `{corroboration.get('consistency_target_selection')}`",
            ]
        )
    for key, passed in goal_checks.items():
        lines.append(f"- {key}: `{_render_bool(passed)}`")
    return execution_complete, goal_achieved, lines


def _shadow_report(payload: dict[str, Any]) -> tuple[bool, bool, list[str]]:
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
    current_consistency = _as_float(timings.get("consistency_p95"))
    current_retrieval = _as_float(timings.get("retrieval_fts_p95"))
    graph_mode = str(consistency_runtime.get("graph_mode") or "off")
    graph_expand_applied_count = _as_int(consistency_runtime.get("graph_expand_applied_count"), 0)
    graph_auto_trigger_count = _as_int(consistency_runtime.get("graph_auto_trigger_count"), 0)
    graph_auto_skip_count = _as_int(consistency_runtime.get("graph_auto_skip_count"), 0)
    auto_total = graph_auto_trigger_count + graph_auto_skip_count
    auto_apply_rate = _safe_ratio(float(graph_auto_trigger_count), float(auto_total))
    corroboration = _extract_corroboration_summary(payload)

    goal_checks = {
        "shadow_index_jobs_succeeded": status.get("index_fts") == "SUCCEEDED" and status.get("index_vec") == "SUCCEEDED",
        "shadow_ingest_failures_zero": _as_int(status.get("ingest_failures")) == 0,
        "shadow_consistency_failures_zero": _as_int(status.get("consistency_failures")) == 0,
        "shadow_retrieve_vec_failures_zero": _as_int(status.get("retrieve_vec_failures")) == 0,
        "shadow_retrieval_fts_p95_gate": current_retrieval <= retrieval_fts_target,
        "shadow_consistency_p95_gate": current_consistency <= consistency_target,
        "shadow_graph_off_applied_zero": graph_mode != "off" or graph_expand_applied_count == 0,
        "shadow_graph_auto_apply_rate_le_30pct": graph_mode != "auto" or auto_apply_rate <= 0.30,
    }
    goal_achieved = all(goal_checks.values())

    lines = [
        "- shadow_secondary_only: `true`",
        "- shadow_goal_in_overall_gate: `false`",
        f"- shadow_execution_complete: `{_render_bool(execution_complete)}`",
        f"- shadow_goal_achieved: `{_render_bool(goal_achieved)}`",
        f"- shadow_doc_count: `{doc_count}`",
        f"- shadow_retrieval_fts_p95_ms: `{current_retrieval:.2f}` (target <= {retrieval_fts_target:.0f})",
        f"- shadow_consistency_p95_ms: `{current_consistency:.2f}` (target <= {consistency_target:.0f})",
        f"- shadow_claim_count_total: `{_as_int(consistency_runtime.get('claim_count_total'))}`",
        f"- shadow_unknown_count_total: `{_as_int(consistency_runtime.get('unknown_count_total'))}`",
        f"- shadow_violate_count_total: `{_as_int(consistency_runtime.get('violate_count_total'))}`",
        f"- shadow_unknown_rate: `{_as_float(consistency_runtime.get('unknown_rate')):.4f}`",
        f"- shadow_unknown_reason_counts: `{consistency_runtime.get('unknown_reason_counts')}`",
        f"- shadow_graph: `{payload.get('graph')}`",
        f"- shadow_graph_runtime: `{payload.get('graph_runtime')}`",
    ]
    if corroboration:
        lines.extend(
            [
                f"- shadow_dataset_generation_version: `{corroboration.get('dataset_generation_version')}`",
                f"- shadow_corroboration_lane: `{corroboration.get('corroboration_lane')}`",
                f"- shadow_local_profile_only_record_count: `{corroboration.get('local_profile_only_record_count')}`",
                f"- shadow_consistency_corroboration_filter: `{corroboration.get('consistency_corroboration_filter')}`",
                f"- shadow_consistency_target_selection: `{corroboration.get('consistency_target_selection')}`",
            ]
        )
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
    parser.add_argument("--pipeline-shadow", type=Path, default=None)
    parser.add_argument("--pipeline-baseline", type=Path, default=None)
    parser.add_argument("--soak", type=Path, default=None)
    parser.add_argument("--latest-summary", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    pipeline = _load_json(args.pipeline)
    pipeline_shadow = _load_json(args.pipeline_shadow)
    pipeline_baseline = _load_json(args.pipeline_baseline)
    soak = _load_json(args.soak)
    latest_summary = _load_json(args.latest_summary)
    if pipeline is None and pipeline_shadow is None and soak is None:
        raise SystemExit("at least one of --pipeline, --pipeline-shadow or --soak is required")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    git_sha = (
        (((pipeline or {}).get("repro") or {}).get("run_manifest") or {}).get("git_sha")
        or (((pipeline_shadow or {}).get("repro") or {}).get("run_manifest") or {}).get("git_sha")
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
    if args.pipeline_shadow is not None:
        lines.append(f"- pipeline_shadow_artifact: `{args.pipeline_shadow}`")
    if args.pipeline_baseline is not None:
        lines.append(f"- pipeline_baseline_artifact: `{args.pipeline_baseline}`")
    if args.soak is not None:
        lines.append(f"- soak_artifact: `{args.soak}`")
    lines.append("")

    overall_execution = True
    overall_goal = True
    if pipeline is not None:
        latest_summary_row = _load_latest_summary_row(latest_summary, pipeline)
        execution_ok, goal_ok, report_lines = _pipeline_report(
            pipeline,
            pipeline_baseline,
            pipeline_shadow,
            latest_summary_row=latest_summary_row,
        )
        overall_execution = overall_execution and execution_ok
        overall_goal = overall_goal and goal_ok
        lines.append("## Pipeline")
        lines.extend(report_lines)
        lines.append("")
    if pipeline_shadow is not None:
        _shadow_execution_ok, _shadow_goal_ok, report_lines = _shadow_report(pipeline_shadow)
        lines.append("## Shadow Lane")
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
