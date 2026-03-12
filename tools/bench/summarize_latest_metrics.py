from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import now_ts

DEFAULT_DATASETS = ("DS-200", "DS-400", "DS-800")
TARGET_METRICS = ("consistency_p95", "retrieval_fts_p95")
_ABSOLUTE_CONSISTENCY_TARGET_MS = 2500.0
_LABEL_MODE_OPERATIONAL = "operational"
_LABEL_MODE_CUSTOM = "custom"
_LABEL_MODE_ALL = "all_artifacts"
_LABEL_FILTER_PRESETS: dict[str, dict[str, Any]] = {
    _LABEL_MODE_OPERATIONAL: {
        "prefixes": ("operational-main:", "operational-diversity-main:"),
        "strict_label_filter": True,
        "preferred_artifact_cohort": "operational_closeout",
        "description": "Only operational mainline/diversity-main artifacts are eligible for trend baselines.",
    }
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _infer_dataset_key(payload: dict[str, Any]) -> str | None:
    dataset_path = str(payload.get("dataset_path") or "")
    if dataset_path:
        diverse_match = re.search(r"(?:DS[-_]?DIVERSE[-_]?)(\d+)", dataset_path, re.IGNORECASE)
        if diverse_match:
            count = int(diverse_match.group(1))
            if count in (200, 400, 800):
                return f"DS-DIVERSE-{count}"
            return None

        growth_match = re.search(r"(?:DS[-_]?GROWTH[-_]?)(\d+)", dataset_path, re.IGNORECASE)
        if growth_match:
            count = int(growth_match.group(1))
            if count in (200, 400, 800):
                return f"DS-{count}"
            return None
        return None

    try:
        doc_count = int(payload.get("doc_count"))
    except (TypeError, ValueError):
        return None
    if doc_count in (200, 400, 800):
        return f"DS-{doc_count}"
    return None


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_time(payload: dict[str, Any], path: Path) -> datetime:
    for key in ("finished_at", "started_at"):
        parsed = _parse_utc(payload.get(key))
        if parsed is not None:
            return parsed
    name_match = re.search(r"(\d{8}T\d{6}Z)", path.name)
    if name_match:
        return datetime.strptime(name_match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _metric_status(delta_pct: float | None) -> str:
    if delta_pct is None:
        return "N/A"
    if delta_pct > 20.0:
        return "HARD_FAIL"
    if delta_pct > 5.0:
        return "SOFT_WARNING"
    return "PASS"


def _absolute_thresholds(doc_count: int | None) -> dict[str, float]:
    normalized_doc_count = int(doc_count or 0)
    retrieval_fts_target = 300.0 if normalized_doc_count <= 200 else 450.0
    return {
        "consistency_p95": _ABSOLUTE_CONSISTENCY_TARGET_MS,
        "retrieval_fts_p95": retrieval_fts_target,
    }


def _absolute_metric_status(metric: str, value: float | None, *, doc_count: int | None) -> str:
    if value is None:
        return "N/A"
    threshold = _absolute_thresholds(doc_count).get(metric)
    if threshold is None:
        return "N/A"
    return "PASS" if value <= threshold else "FAIL"


def _absolute_dataset_status(metric_status: dict[str, str]) -> str:
    if not metric_status:
        return "WARN"
    values = list(metric_status.values())
    if any(value == "FAIL" for value in values):
        return "FAIL"
    if all(value == "PASS" for value in values):
        return "PASS"
    return "WARN"


def _parse_label_prefixes(text: str | None) -> tuple[str, ...]:
    if text is None or not text.strip():
        return ()
    out: list[str] = []
    for token in text.split(","):
        label = token.strip()
        if label and label not in out:
            out.append(label)
    return tuple(out)


def _label_matches(bench_label: str, label_prefixes: tuple[str, ...]) -> bool:
    if not label_prefixes:
        return True
    for prefix in label_prefixes:
        if bench_label.startswith(prefix):
            return True
    return False


def _artifact_execution_failed(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    if not isinstance(status, dict):
        return False
    index_fts = str(status.get("index_fts") or "").strip().upper()
    if index_fts and index_fts != "SUCCEEDED":
        return True
    index_vec = str(status.get("index_vec") or "").strip().upper()
    if index_vec and index_vec != "SUCCEEDED":
        return True
    for key in ("ingest_failures", "consistency_failures", "retrieve_vec_failures"):
        if key not in status:
            continue
        try:
            if int(status.get(key) or 0) != 0:
                return True
        except (TypeError, ValueError):
            return True
    return False


def _artifact_attempt_status(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    if not isinstance(status, dict):
        stage = str(payload.get("attempt_stage") or "").strip()
        error_class = str(payload.get("error_class") or "").strip()
        if stage and error_class:
            return f"{stage}:{error_class}"
        if stage:
            return stage
        if error_class:
            return error_class
        return "UNKNOWN"
    failures: list[str] = []
    index_fts = str(status.get("index_fts") or "").strip().upper()
    if index_fts and index_fts != "SUCCEEDED":
        failures.append(f"index_fts:{index_fts}")
    index_vec = str(status.get("index_vec") or "").strip().upper()
    if index_vec and index_vec != "SUCCEEDED":
        failures.append(f"index_vec:{index_vec}")
    for key in ("ingest_failures", "consistency_failures", "retrieve_vec_failures"):
        if key not in status:
            continue
        try:
            parsed = int(status.get(key) or 0)
        except (TypeError, ValueError):
            failures.append(f"{key}:INVALID")
            continue
        if parsed != 0:
            failures.append(f"{key}:{parsed}")
    if not failures:
        return "SUCCEEDED"
    return ",".join(failures)


def _artifact_cohort(payload: dict[str, Any]) -> str:
    return str(payload.get("artifact_cohort") or "").strip()


def _extract_dataset_profile_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = payload.get("semantic")
    if not isinstance(semantic, dict):
        return {}
    dataset_profile = semantic.get("dataset_profile")
    if not isinstance(dataset_profile, dict):
        return {}
    manifest_entry = dataset_profile.get("dataset_manifest_entry")
    if not isinstance(manifest_entry, dict):
        manifest_entry = {}
    corroboration_filter = dataset_profile.get("consistency_corroboration_filter")
    if not isinstance(corroboration_filter, dict):
        corroboration_filter = {}
    target_selection = semantic.get("consistency_target_selection")
    if not isinstance(target_selection, dict):
        target_selection = {}
    corroboration_policy_counts = dataset_profile.get("consistency_corroboration_policy_counts")
    if not isinstance(corroboration_policy_counts, dict):
        corroboration_policy_counts = manifest_entry.get("consistency_corroboration_policy_counts")
    if not isinstance(corroboration_policy_counts, dict):
        corroboration_policy_counts = {}

    local_profile_only_record_count = dataset_profile.get("local_profile_only_record_count")
    try:
        if local_profile_only_record_count is None:
            local_profile_only_record_count = int(manifest_entry.get("local_profile_only_record_count") or 0)
        else:
            local_profile_only_record_count = int(local_profile_only_record_count)
    except (TypeError, ValueError):
        local_profile_only_record_count = 0

    lane = ""
    filter_mode = str(corroboration_filter.get("filter_mode") or "")
    if filter_mode == "only_local_profile_only":
        lane = "shadow_local_profile_only"
    else:
        try:
            local_profile_only_docs_total = int(target_selection.get("local_profile_only_docs_total") or 0)
            skipped_local_profile_only_docs = int(target_selection.get("skipped_local_profile_only_docs") or 0)
        except (TypeError, ValueError):
            local_profile_only_docs_total = 0
            skipped_local_profile_only_docs = 0
        if local_profile_only_docs_total > 0 and skipped_local_profile_only_docs > 0:
            lane = "mainline_excludes_local_profile_only"
        elif local_profile_only_record_count > 0:
            lane = "dataset_contains_local_profile_only"

    return {
        "dataset_generation_version": str(manifest_entry.get("dataset_generation_version") or ""),
        "composite_source_policy": str(manifest_entry.get("composite_source_policy") or ""),
        "source_policy_registry_version": str(manifest_entry.get("source_policy_registry_version") or ""),
        "manual_review_source_count": int(manifest_entry.get("manual_review_source_count") or 0),
        "local_profile_only_record_count": local_profile_only_record_count,
        "consistency_corroboration_policy_counts": {
            str(key): int(value)
            for key, value in corroboration_policy_counts.items()
            if isinstance(key, str)
        },
        "consistency_corroboration_filter": dict(corroboration_filter),
        "consistency_target_selection": dict(target_selection),
        "corroboration_lane": lane,
    }


def _extract_consistency_runtime_summary(payload: dict[str, Any]) -> dict[str, Any]:
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
    anchor_filtered_slot_counts = runtime.get("anchor_filtered_slot_counts")
    if not isinstance(anchor_filtered_slot_counts, dict):
        anchor_filtered_slot_counts = {}
    return {
        "claim_count_total": int(runtime.get("claim_count_total") or 0),
        "unknown_count_total": int(runtime.get("unknown_count_total") or 0),
        "violate_count_total": int(runtime.get("violate_count_total") or 0),
        "unknown_rate": float(runtime.get("unknown_rate") or 0.0),
        "violate_rate": float(runtime.get("violate_rate") or 0.0),
        "slot_detection_rate": float(runtime.get("slot_detection_rate") or 0.0),
        "claims_skipped_low_confidence_rate": float(runtime.get("claims_skipped_low_confidence_rate") or 0.0),
        "triage_selection_rate": float(runtime.get("triage_selection_rate") or 0.0),
        "jobs_with_claims_total": int(runtime.get("jobs_with_claims_total") or 0),
        "slot_diagnostics_schema_status": str(runtime.get("slot_diagnostics_schema_status") or ""),
        "slot_diagnostics_present_jobs": int(runtime.get("slot_diagnostics_present_jobs") or 0),
        "slot_diagnostics_partial_jobs": int(runtime.get("slot_diagnostics_partial_jobs") or 0),
        "slot_diagnostics_missing_jobs": int(runtime.get("slot_diagnostics_missing_jobs") or 0),
        "slot_diagnostics_missing_with_claims_jobs": int(
            runtime.get("slot_diagnostics_missing_with_claims_jobs") or 0
        ),
        "slot_diagnostics_complete_job_rate": float(runtime.get("slot_diagnostics_complete_job_rate") or 0.0),
        "slot_diagnostics_missing_with_claims_rate": float(
            runtime.get("slot_diagnostics_missing_with_claims_rate") or 0.0
        ),
        "claim_slot_counts": {str(key): int(value) for key, value in claim_slot_counts.items() if isinstance(key, str)},
        "unknown_slot_counts": {
            str(key): int(value) for key, value in unknown_slot_counts.items() if isinstance(key, str)
        },
        "no_evidence_slot_counts": {
            str(key): int(value) for key, value in no_evidence_slot_counts.items() if isinstance(key, str)
        },
        "anchor_filtered_slot_counts": {
            str(key): int(value) for key, value in anchor_filtered_slot_counts.items() if isinstance(key, str)
        },
        "unknown_reason_counts": {
            str(key): int(value)
            for key, value in unknown_reason_counts.items()
            if isinstance(key, str)
        },
    }


def _is_shadow_artifact(payload: dict[str, Any]) -> bool:
    bench_label = str(payload.get("bench_label") or "").strip()
    if bench_label.startswith("operational-shadow:"):
        return True
    dataset_profile_meta = _extract_dataset_profile_metadata(payload)
    return str(dataset_profile_meta.get("corroboration_lane") or "") == "shadow_local_profile_only"


def _shadow_reference(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {
            "run_utc": None,
            "file": None,
            "bench_label": None,
            "corroboration_lane": None,
            "consistency_runtime": {
                "claim_count_total": 0,
                "unknown_count_total": 0,
                "violate_count_total": 0,
                "unknown_rate": 0.0,
                "violate_rate": 0.0,
                "slot_detection_rate": 0.0,
                "claims_skipped_low_confidence_rate": 0.0,
                "triage_selection_rate": 0.0,
                "jobs_with_claims_total": 0,
                "slot_diagnostics_schema_status": "",
                "slot_diagnostics_present_jobs": 0,
                "slot_diagnostics_partial_jobs": 0,
                "slot_diagnostics_missing_jobs": 0,
                "slot_diagnostics_missing_with_claims_jobs": 0,
                "slot_diagnostics_complete_job_rate": 0.0,
                "slot_diagnostics_missing_with_claims_rate": 0.0,
                "claim_slot_counts": {},
                "unknown_slot_counts": {},
                "no_evidence_slot_counts": {},
                "anchor_filtered_slot_counts": {},
                "unknown_reason_counts": {},
            },
        }
    dataset_profile_meta = _extract_dataset_profile_metadata(row["payload"])
    return {
        "run_utc": row["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": row["path"].name,
        "bench_label": str(row.get("bench_label") or ""),
        "corroboration_lane": dataset_profile_meta.get("corroboration_lane") or None,
        "consistency_runtime": _extract_consistency_runtime_summary(row["payload"]),
    }


def _classify_actionability(
    *,
    latest_runtime: dict[str, Any],
    latest_corroboration_lane: str,
    shadow_reference: dict[str, Any],
) -> tuple[str, str]:
    claim_count_total = int(latest_runtime.get("claim_count_total") or 0)
    unknown_count_total = int(latest_runtime.get("unknown_count_total") or 0)
    violate_count_total = int(latest_runtime.get("violate_count_total") or 0)
    shadow_runtime = shadow_reference.get("consistency_runtime") or {}
    shadow_claim_count_total = int(shadow_runtime.get("claim_count_total") or 0)
    shadow_lane = str(shadow_reference.get("corroboration_lane") or "")

    if claim_count_total > 0:
        if unknown_count_total >= claim_count_total and violate_count_total == 0:
            return (
                "MAINLINE_ALL_UNKNOWN",
                "mainline claims are present but still unresolved; investigate unknown_reason_counts before treating the lane as actionable",
            )
        return ("MAINLINE_ACTIVE", "mainline actionable claims are present")
    if latest_corroboration_lane == "mainline_excludes_local_profile_only":
        if shadow_claim_count_total > 0 and shadow_lane == "shadow_local_profile_only":
            return (
                "SEPARATED_TO_SHADOW",
                "mainline excludes local-profile-only claims; the secondary shadow lane carries the corroboration-only workload",
            )
        return (
            "MAINLINE_EMPTY_AFTER_SEPARATION",
            "mainline excludes local-profile-only claims and no shadow corroboration workload was observed in the latest shadow reference",
        )
    return ("NO_MAINLINE_CLAIMS", "mainline produced no actionable claims")


def _resolve_label_filter(
    *,
    label_mode: str | None,
    label_prefixes: tuple[str, ...],
    strict_label_filter: bool,
) -> dict[str, Any]:
    normalized_mode = str(label_mode or "").strip().lower()
    preset = _LABEL_FILTER_PRESETS.get(normalized_mode)
    resolved_prefixes = label_prefixes
    resolved_strict = bool(strict_label_filter)
    mode = _LABEL_MODE_CUSTOM if (resolved_prefixes or resolved_strict) else _LABEL_MODE_ALL
    note = "Includes all benchmark artifacts matching the dataset selection."
    preferred_artifact_cohort = ""
    if preset is not None:
        if not resolved_prefixes:
            resolved_prefixes = tuple(str(item) for item in preset.get("prefixes") or ())
        resolved_strict = bool(resolved_strict or preset.get("strict_label_filter", False))
        mode = normalized_mode
        note = str(preset.get("description") or note)
        preferred_artifact_cohort = str(preset.get("preferred_artifact_cohort") or "")
    elif mode == _LABEL_MODE_CUSTOM:
        note = "Uses caller-specified label prefixes and/or strict unlabeled exclusion."
    return {
        "mode": mode,
        "note": note,
        "prefixes": resolved_prefixes,
        "strict_label_filter": resolved_strict,
        "preferred_artifact_cohort": preferred_artifact_cohort,
    }


def _prefer_artifact_cohort(
    rows: list[dict[str, Any]],
    *,
    preferred_artifact_cohort: str,
) -> tuple[list[dict[str, Any]], int, bool]:
    token = str(preferred_artifact_cohort or "").strip()
    if not token or not rows:
        return list(rows), 0, False
    ordered_rows = sorted(rows, key=lambda item: item["event_time"], reverse=True)
    matching = [row for row in ordered_rows if str(row.get("artifact_cohort") or "") == token]
    if not matching:
        return list(rows), 0, False
    latest_matching_time = matching[0]["event_time"]
    kept = [
        row
        for row in ordered_rows
        if str(row.get("artifact_cohort") or "") == token or row["event_time"] < latest_matching_time
    ]
    excluded = len(rows) - len(kept)
    return kept, excluded, True


def _dataset_summary(
    dataset_key: str,
    successful_rows: list[dict[str, Any]],
    attempt_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered_successful = sorted(successful_rows, key=lambda item: item["event_time"], reverse=True)
    ordered_attempts = sorted(attempt_rows, key=lambda item: item["event_time"], reverse=True)
    ordered_shadow = sorted(shadow_rows, key=lambda item: item["event_time"], reverse=True)
    latest_successful = ordered_successful[0] if ordered_successful else None
    previous_successful = ordered_successful[1] if len(ordered_successful) > 1 else None
    latest_attempt = ordered_attempts[0] if ordered_attempts else None
    latest_shadow = ordered_shadow[0] if ordered_shadow else None

    if latest_successful is None:
        shadow_reference = _shadow_reference(latest_shadow)
        return {
            "dataset": dataset_key,
            "status": "MISSING",
            "absolute_status": "MISSING",
            "latest_run_utc": None,
            "latest_file": None,
            "latest_doc_count": None,
            "latest_metrics": {metric: None for metric in TARGET_METRICS},
            "previous_run_utc": None,
            "previous_file": None,
            "delta_pct": {metric: None for metric in TARGET_METRICS},
            "metric_status": {metric: "N/A" for metric in TARGET_METRICS},
            "absolute_metric_status": {metric: "N/A" for metric in TARGET_METRICS},
            "absolute_thresholds": {metric: None for metric in TARGET_METRICS},
            "improved_or_same_metric_count": 0,
            "latest_successful_run_utc": None,
            "latest_successful_file": None,
            "latest_successful_bench_label": None,
            "latest_attempt_run_utc": None
            if latest_attempt is None
            else latest_attempt["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latest_attempt_file": None if latest_attempt is None else latest_attempt["path"].name,
            "latest_attempt_bench_label": None if latest_attempt is None else str(latest_attempt.get("bench_label") or ""),
            "latest_attempt_status": None
            if latest_attempt is None
            else str(latest_attempt.get("attempt_status") or "UNKNOWN"),
            "latest_attempt_succeeded": None
            if latest_attempt is None
            else bool(latest_attempt.get("attempt_status") == "SUCCEEDED"),
            "latest_consistency_runtime": shadow_reference["consistency_runtime"],
            "latest_shadow_reference": shadow_reference,
            "latest_actionability_status": "NO_MAINLINE_DATA",
            "latest_actionability_note": "no mainline successful artifact is available for actionability classification",
        }

    latest_metrics = latest_successful["metrics"]
    latest_doc_count = latest_successful.get("doc_count")
    dataset_profile_meta = _extract_dataset_profile_metadata(latest_successful["payload"])
    latest_runtime = _extract_consistency_runtime_summary(latest_successful["payload"])
    shadow_reference = _shadow_reference(latest_shadow)
    actionability_status, actionability_note = _classify_actionability(
        latest_runtime=latest_runtime,
        latest_corroboration_lane=str(dataset_profile_meta.get("corroboration_lane") or ""),
        shadow_reference=shadow_reference,
    )
    previous_metrics = previous_successful["metrics"] if previous_successful is not None else {}
    delta_pct: dict[str, float | None] = {}
    metric_status: dict[str, str] = {}
    improved_or_same = 0
    for metric in TARGET_METRICS:
        current = latest_metrics.get(metric)
        baseline = previous_metrics.get(metric)
        if current is None or baseline is None or baseline <= 0:
            delta = None
        else:
            delta = ((current - baseline) / baseline) * 100.0
        delta_pct[metric] = delta
        metric_status[metric] = _metric_status(delta)
        if delta is not None and delta <= 0.0:
            improved_or_same += 1

    status = "PASS"
    if any(state == "HARD_FAIL" for state in metric_status.values()):
        status = "FAIL"
    elif any(state == "SOFT_WARNING" for state in metric_status.values()):
        status = "WARN"
    elif previous_successful is None:
        status = "NO_BASELINE"

    absolute_thresholds = _absolute_thresholds(latest_doc_count)
    absolute_metric_status = {
        metric: _absolute_metric_status(metric, latest_metrics.get(metric), doc_count=latest_doc_count)
        for metric in TARGET_METRICS
    }
    absolute_status = _absolute_dataset_status(absolute_metric_status)

    return {
        "dataset": dataset_key,
        "status": status,
        "absolute_status": absolute_status,
        "latest_run_utc": latest_successful["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_file": latest_successful["path"].name,
        "latest_bench_label": str(latest_successful.get("bench_label") or ""),
        "latest_doc_count": latest_doc_count,
        "latest_metrics": latest_metrics,
        "latest_dataset_generation_version": dataset_profile_meta.get("dataset_generation_version") or None,
        "latest_composite_source_policy": dataset_profile_meta.get("composite_source_policy") or None,
        "latest_source_policy_registry_version": dataset_profile_meta.get("source_policy_registry_version") or None,
        "latest_manual_review_source_count": int(dataset_profile_meta.get("manual_review_source_count") or 0),
        "latest_local_profile_only_record_count": int(dataset_profile_meta.get("local_profile_only_record_count") or 0),
        "latest_consistency_corroboration_policy_counts": dict(
            dataset_profile_meta.get("consistency_corroboration_policy_counts") or {}
        ),
        "latest_consistency_corroboration_filter": dict(
            dataset_profile_meta.get("consistency_corroboration_filter") or {}
        ),
        "latest_consistency_target_selection": dict(
            dataset_profile_meta.get("consistency_target_selection") or {}
        ),
        "latest_corroboration_lane": dataset_profile_meta.get("corroboration_lane") or None,
        "latest_consistency_runtime": latest_runtime,
        "latest_shadow_reference": shadow_reference,
        "latest_actionability_status": actionability_status,
        "latest_actionability_note": actionability_note,
        "previous_run_utc": None
        if previous_successful is None
        else previous_successful["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous_file": None if previous_successful is None else previous_successful["path"].name,
        "previous_bench_label": None
        if previous_successful is None
        else str(previous_successful.get("bench_label") or ""),
        "delta_pct": delta_pct,
        "metric_status": metric_status,
        "absolute_metric_status": absolute_metric_status,
        "absolute_thresholds": absolute_thresholds,
        "improved_or_same_metric_count": improved_or_same,
        "latest_successful_run_utc": latest_successful["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_successful_file": latest_successful["path"].name,
        "latest_successful_bench_label": str(latest_successful.get("bench_label") or ""),
        "latest_attempt_run_utc": None
        if latest_attempt is None
        else latest_attempt["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_attempt_file": None if latest_attempt is None else latest_attempt["path"].name,
        "latest_attempt_bench_label": None if latest_attempt is None else str(latest_attempt.get("bench_label") or ""),
        "latest_attempt_status": None if latest_attempt is None else str(latest_attempt.get("attempt_status") or "UNKNOWN"),
        "latest_attempt_succeeded": None if latest_attempt is None else bool(latest_attempt.get("attempt_status") == "SUCCEEDED"),
    }


def summarize_benchmarks(
    bench_dir: Path,
    *,
    datasets: tuple[str, ...] = DEFAULT_DATASETS,
    label_mode: str | None = None,
    label_prefixes: tuple[str, ...] = (),
    strict_label_filter: bool = False,
) -> dict[str, Any]:
    resolved_label_filter = _resolve_label_filter(
        label_mode=label_mode,
        label_prefixes=label_prefixes,
        strict_label_filter=strict_label_filter,
    )
    resolved_prefixes = tuple(str(item) for item in resolved_label_filter["prefixes"])
    resolved_strict = bool(resolved_label_filter["strict_label_filter"])
    preferred_artifact_cohort = str(resolved_label_filter.get("preferred_artifact_cohort") or "")
    successful_rows_by_dataset: dict[str, list[dict[str, Any]]] = {dataset: [] for dataset in datasets}
    attempt_rows_by_dataset: dict[str, list[dict[str, Any]]] = {dataset: [] for dataset in datasets}
    shadow_rows_by_dataset: dict[str, list[dict[str, Any]]] = {dataset: [] for dataset in datasets}
    scanned_count = 0
    considered_count = 0
    considered_attempt_count = 0
    excluded_unlabeled = 0
    excluded_prefix_mismatch = 0
    excluded_unsuccessful_status = 0
    for path in sorted(bench_dir.glob("*.json")):
        if path.name.startswith(("soak_", "graphrag_probe_", "latest_metrics_summary", "consistency_strict_gate")):
            continue
        payload = _read_json(path)
        if payload is None:
            continue
        scanned_count += 1
        bench_label = str(payload.get("bench_label") or "").strip()
        dataset_key = _infer_dataset_key(payload)
        if dataset_key in successful_rows_by_dataset and _is_shadow_artifact(payload):
            timings = payload.get("timings_ms") or {}
            shadow_rows_by_dataset[dataset_key].append(
                {
                    "path": path,
                    "payload": payload,
                    "event_time": _event_time(payload, path),
                    "metrics": {
                        "consistency_p95": _as_float(timings.get("consistency_p95")),
                        "retrieval_fts_p95": _as_float(timings.get("retrieval_fts_p95")),
                    },
                    "doc_count": int(payload.get("doc_count") or 0),
                    "bench_label": bench_label,
                    "artifact_cohort": _artifact_cohort(payload),
                    "attempt_status": _artifact_attempt_status(payload),
                }
            )
        if resolved_strict and not bench_label:
            excluded_unlabeled += 1
            continue
        if not _label_matches(bench_label, resolved_prefixes):
            excluded_prefix_mismatch += 1
            continue
        if dataset_key not in successful_rows_by_dataset:
            continue
        attempt_status = _artifact_attempt_status(payload)
        timings = payload.get("timings_ms") or {}
        attempt_row = {
            "path": path,
            "payload": payload,
            "event_time": _event_time(payload, path),
            "metrics": {
                "consistency_p95": _as_float(timings.get("consistency_p95")),
                "retrieval_fts_p95": _as_float(timings.get("retrieval_fts_p95")),
            },
            "doc_count": int(payload.get("doc_count") or 0),
            "bench_label": bench_label,
            "artifact_cohort": _artifact_cohort(payload),
            "attempt_status": attempt_status,
        }
        attempt_rows_by_dataset[dataset_key].append(attempt_row)
        considered_attempt_count += 1
        if not isinstance(payload.get("timings_ms"), dict):
            continue
        if _artifact_execution_failed(payload):
            excluded_unsuccessful_status += 1
            continue
        considered_count += 1
        metrics = {
            "consistency_p95": _as_float(timings.get("consistency_p95")),
            "retrieval_fts_p95": _as_float(timings.get("retrieval_fts_p95")),
        }
        successful_rows_by_dataset[dataset_key].append(
            {
                "path": path,
                "payload": payload,
                "event_time": attempt_row["event_time"],
                "metrics": metrics,
                "doc_count": int(payload.get("doc_count") or 0),
                "bench_label": bench_label,
                "artifact_cohort": _artifact_cohort(payload),
            }
        )

    excluded_artifact_cohort_mismatch = 0
    artifact_cohort_filter_applied_datasets: list[str] = []
    for dataset in datasets:
        filtered_successful, excluded_successful, successful_applied = _prefer_artifact_cohort(
            successful_rows_by_dataset.get(dataset, []),
            preferred_artifact_cohort=preferred_artifact_cohort,
        )
        successful_rows_by_dataset[dataset] = filtered_successful
        excluded_artifact_cohort_mismatch += excluded_successful
        if successful_applied:
            artifact_cohort_filter_applied_datasets.append(dataset)

    dataset_summaries = {
        dataset: _dataset_summary(
            dataset,
            successful_rows_by_dataset.get(dataset, []),
            attempt_rows_by_dataset.get(dataset, []),
            shadow_rows_by_dataset.get(dataset, []),
        )
        for dataset in datasets
    }

    hard_fail = any(summary["status"] == "FAIL" for summary in dataset_summaries.values())
    soft_warning = any(summary["status"] == "WARN" for summary in dataset_summaries.values())
    no_baseline = any(summary["status"] == "NO_BASELINE" for summary in dataset_summaries.values())

    all_have_improve_or_same = True
    for summary in dataset_summaries.values():
        if summary["status"] in {"MISSING", "NO_BASELINE"}:
            all_have_improve_or_same = False
            continue
        if int(summary.get("improved_or_same_metric_count", 0)) <= 0:
            all_have_improve_or_same = False

    overall_status = "PASS"
    if hard_fail:
        overall_status = "FAIL"
    elif soft_warning or no_baseline or not all_have_improve_or_same:
        overall_status = "WARN"

    absolute_fail = any(summary.get("absolute_status") == "FAIL" for summary in dataset_summaries.values())
    absolute_missing = any(summary.get("absolute_status") == "MISSING" for summary in dataset_summaries.values())
    absolute_warn = any(summary.get("absolute_status") == "WARN" for summary in dataset_summaries.values())
    absolute_goal_status = "PASS"
    if absolute_fail:
        absolute_goal_status = "FAIL"
    elif absolute_warn or absolute_missing:
        absolute_goal_status = "WARN"

    return {
        "generated_at_utc": now_ts(),
        "bench_dir": str(bench_dir),
        "dataset_order": list(datasets),
        "datasets": dataset_summaries,
        "status_semantics": {
            "overall_status": "trend_relative",
            "overall_status_note": "Compares latest artifact against the previous artifact for the same dataset selection.",
            "absolute_goal_status": "absolute_thresholds",
            "absolute_goal_status_note": "Informational absolute goal view only. Release gating still comes from final gate report artifacts.",
        },
        "label_filter": {
            "mode": str(resolved_label_filter["mode"]),
            "note": str(resolved_label_filter["note"]),
            "prefixes": list(resolved_prefixes),
            "strict_label_filter": bool(resolved_strict),
            "preferred_artifact_cohort": preferred_artifact_cohort or None,
            "scanned_artifacts": scanned_count,
            "considered_attempt_artifacts": considered_attempt_count,
            "considered_artifacts": considered_count,
            "excluded_unlabeled": excluded_unlabeled,
            "excluded_prefix_mismatch": excluded_prefix_mismatch,
            "excluded_unsuccessful_status": excluded_unsuccessful_status,
            "excluded_artifact_cohort_mismatch": excluded_artifact_cohort_mismatch,
            "artifact_cohort_filter_applied_datasets": artifact_cohort_filter_applied_datasets,
        },
        "rule_evaluation": {
            "hard_fail": hard_fail,
            "soft_warning": soft_warning,
            "no_baseline": no_baseline,
            "all_datasets_have_improved_or_same_metric": all_have_improve_or_same,
        },
        "overall_status": overall_status,
        "absolute_goal_status": absolute_goal_status,
    }


def _format_metric(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _format_delta(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%"


def _parse_dataset_arg(text: str | None) -> tuple[str, ...]:
    if text is None or not text.strip():
        return DEFAULT_DATASETS
    out: list[str] = []
    for token in text.split(","):
        key = token.strip()
        if key and key not in out:
            out.append(key)
    return tuple(out) if out else DEFAULT_DATASETS


def render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Latest Metrics Summary",
        "",
        f"- generated_at_utc: `{summary.get('generated_at_utc')}`",
        f"- overall_status (trend_relative): `{summary.get('overall_status')}`",
        f"- absolute_goal_status: `{summary.get('absolute_goal_status')}`",
        f"- status_semantics: `{summary.get('status_semantics')}`",
        f"- label_filter: `{summary.get('label_filter')}`",
        "",
        "| dataset | latest_successful_run_utc | latest_attempt | consistency_p95(ms) | retrieval_fts_p95(ms) | delta_consistency | delta_retrieval_fts | trend_status | absolute_status |",
        "|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    datasets = summary.get("datasets") or {}
    dataset_order = summary.get("dataset_order") or list(DEFAULT_DATASETS)
    for dataset_key in dataset_order:
        row = datasets.get(dataset_key) or {}
        latest_metrics = row.get("latest_metrics") or {}
        delta_pct = row.get("delta_pct") or {}
        lines.append(
            "| {dataset} | {run} | {attempt} | {cons} | {retr} | {d_cons} | {d_retr} | {trend_status} | {absolute_status} |".format(
                dataset=dataset_key,
                run=row.get("latest_run_utc") or "-",
                attempt="-"
                if not row.get("latest_attempt_file")
                else f"{row.get('latest_attempt_file')} ({row.get('latest_attempt_status')})",
                cons=_format_metric(_as_float(latest_metrics.get("consistency_p95"))),
                retr=_format_metric(_as_float(latest_metrics.get("retrieval_fts_p95"))),
                d_cons=_format_delta(_as_float(delta_pct.get("consistency_p95"))),
                d_retr=_format_delta(_as_float(delta_pct.get("retrieval_fts_p95"))),
                trend_status=row.get("status") or "MISSING",
                absolute_status=row.get("absolute_status") or "MISSING",
            )
        )
    lane_rows = []
    for dataset_key in dataset_order:
        row = datasets.get(dataset_key) or {}
        local_profile_count = int(row.get("latest_local_profile_only_record_count") or 0)
        lane = str(row.get("latest_corroboration_lane") or "")
        generation = str(row.get("latest_dataset_generation_version") or "")
        if not local_profile_count and not lane and not generation:
            continue
        lane_rows.append(
            "- {dataset}: generation=`{generation}`, lane=`{lane}`, local_profile_only=`{count}`, filter=`{filter}`".format(
                dataset=dataset_key,
                generation=generation or "-",
                lane=lane or "-",
                count=local_profile_count,
                filter=(row.get("latest_consistency_corroboration_filter") or {}).get("filter_mode") or "-",
            )
        )
    if lane_rows:
        lines.extend(["", "## Corroboration Lane", *lane_rows])
    actionability_rows = []
    for dataset_key in dataset_order:
        row = datasets.get(dataset_key) or {}
        runtime = row.get("latest_consistency_runtime") or {}
        shadow_reference = row.get("latest_shadow_reference") or {}
        shadow_runtime = shadow_reference.get("consistency_runtime") or {}
        actionability_status = str(row.get("latest_actionability_status") or "")
        actionability_note = str(row.get("latest_actionability_note") or "")
        if not actionability_status:
            continue
        actionability_rows.append(
            "- {dataset}: status=`{status}`, mainline_claims=`{main_claims}`, mainline_unknown=`{main_unknown}`, lane=`{lane}`, slot_diag=`{slot_diag}`, shadow_claims=`{shadow_claims}`, shadow_unknown_rate=`{shadow_unknown_rate}`, note=`{note}`".format(
                dataset=dataset_key,
                status=actionability_status,
                main_claims=int(runtime.get("claim_count_total") or 0),
                main_unknown=int(runtime.get("unknown_count_total") or 0),
                lane=str(row.get("latest_corroboration_lane") or "-"),
                slot_diag=str(runtime.get("slot_diagnostics_schema_status") or "-"),
                shadow_claims=int(shadow_runtime.get("claim_count_total") or 0),
                shadow_unknown_rate=f"{float(shadow_runtime.get('unknown_rate') or 0.0):.4f}",
                note=actionability_note or "-",
            )
        )
    if actionability_rows:
        lines.extend(["", "## Actionability View", *actionability_rows])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize latest benchmark metrics by dataset.")
    parser.add_argument("--bench-dir", type=Path, default=Path("verify/benchmarks"))
    parser.add_argument("--output-json", type=Path, default=Path("verify/benchmarks/latest_metrics_summary.json"))
    parser.add_argument("--output-md", type=Path, default=Path("verify/benchmarks/latest_metrics_summary.md"))
    parser.add_argument("--datasets", type=str, default="")
    parser.add_argument("--label-mode", type=str, default="")
    parser.add_argument("--label-prefixes", type=str, default="")
    parser.add_argument("--strict-label-filter", action="store_true")
    args = parser.parse_args()

    summary = summarize_benchmarks(
        args.bench_dir,
        datasets=_parse_dataset_arg(args.datasets),
        label_mode=args.label_mode,
        label_prefixes=_parse_label_prefixes(args.label_prefixes),
        strict_label_filter=bool(args.strict_label_filter),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"ok": True, "output_json": str(args.output_json), "output_md": str(args.output_md)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
