from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
_REPO_ROOT = _THIS_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common import (  # noqa: E402
    build_run_manifest,
    coefficient_of_variation,
    metrics_hash as compute_metrics_hash,
    normalize_semantic,
    now_ts,
    sha256_obj,
)
from http_client import (  # noqa: E402
    ApiRequestError as SharedApiRequestError,
    ApiClient as SharedApiClient,
    JobRun as SharedJobRun,
    submit_and_wait as shared_submit_and_wait,
    wait_for_job as shared_wait_for_job,
)
from modules.nf_consistency.engine_parts.claims import _extract_claims as extract_consistency_claims  # noqa: E402
from modules.nf_consistency.extractors.pipeline import ExtractionPipeline  # noqa: E402
from source_policy_profile import record_consistency_corroboration_policy  # noqa: E402
from sse import parse_sse_events as shared_parse_sse_events, read_job_events as shared_read_job_events  # noqa: E402
from stats import percentile as shared_percentile  # noqa: E402


def percentile(values: list[float], p: float) -> float:
    return shared_percentile(values, p)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ApiClient(SharedApiClient):
    pass


ApiRequestError = SharedApiRequestError
JobRun = SharedJobRun


def parse_sse_events(raw: str) -> list[tuple[int, dict[str, Any]]]:
    return shared_parse_sse_events(raw)


def get_job_events(client: ApiClient, job_id: str, *, after_seq: int = 0) -> list[tuple[int, dict[str, Any]]]:
    return shared_read_job_events(
        base_url=client.base_url,
        job_id=job_id,
        after_seq=after_seq,
        timeout=client.timeout,
    )


@dataclass
class BenchRunResult:
    started_at: str
    finished_at: str
    base_url: str
    dataset_path: str
    dataset_hash: str
    project_id: str
    doc_count: int
    rss_mb_process: float
    timings_ms: dict[str, float]
    status: dict[str, Any]
    semantic: dict[str, Any]
    semantic_hash: str
    metrics_hash: str


class BenchStageError(RuntimeError):
    def __init__(self, stage: str, cause: Exception) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"{stage}: {cause}")


def wait_for_job(client: ApiClient, job_id: str, *, poll_sec: float = 0.5, timeout_sec: float = 7200.0) -> JobRun:
    return shared_wait_for_job(client, job_id, poll_sec=poll_sec, timeout_sec=timeout_sec)


def submit_and_wait(
    client: ApiClient,
    *,
    project_id: str,
    job_type: str,
    inputs: dict[str, Any],
    params: dict[str, Any] | None = None,
    timeout_sec: float = 7200.0,
) -> JobRun:
    return shared_submit_and_wait(
        client,
        project_id=project_id,
        job_type=job_type,
        inputs=inputs,
        params=params,
        timeout_sec=timeout_sec,
    )


def load_dataset(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
            if limit is not None and len(items) >= limit:
                break
    return items


def _filter_records_for_shadow_track(
    records: list[dict[str, Any]],
    *,
    only_local_profile_only: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not only_local_profile_only:
        return list(records), {
            "filter_mode": "all",
            "input_record_count": len(records),
            "selected_record_count": len(records),
            "local_profile_only_selected_count": sum(
                1
                for item in records
                if str((record_consistency_corroboration_policy(item) or {}).get("policy") or "") == "local_profile_only"
            ),
        }
    selected = [
        item
        for item in records
        if str((record_consistency_corroboration_policy(item) or {}).get("policy") or "") == "local_profile_only"
    ]
    return selected, {
        "filter_mode": "only_local_profile_only",
        "input_record_count": len(records),
        "selected_record_count": len(selected),
        "local_profile_only_selected_count": len(selected),
    }


def _load_dataset_manifest_entry(dataset_path: Path) -> dict[str, Any]:
    manifest_path = dataset_path.parent / "dataset_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    datasets = payload.get("datasets")
    if not isinstance(datasets, dict):
        return {}
    target = str(dataset_path)
    target_name = dataset_path.name
    for value in datasets.values():
        if not isinstance(value, dict):
            continue
        candidate_path = str(value.get("path") or "")
        candidate_name = Path(candidate_path).name if candidate_path else ""
        if candidate_path == target or candidate_name == target_name:
            entry = dict(value)
            generation_version = payload.get("dataset_generation_version")
            if isinstance(generation_version, str) and generation_version:
                entry.setdefault("dataset_generation_version", generation_version)
            composite_policy = payload.get("composite_source_policy")
            if isinstance(composite_policy, str) and composite_policy:
                entry.setdefault("composite_source_policy", composite_policy)
            registry_version = payload.get("source_policy_registry_version")
            if isinstance(registry_version, str) and registry_version:
                entry.setdefault("source_policy_registry_version", registry_version)
            try:
                entry.setdefault("manual_review_source_count", int(payload.get("manual_review_source_count") or 0))
            except (TypeError, ValueError):
                entry.setdefault("manual_review_source_count", 0)
            reason_counts = payload.get("manual_review_reason_counts")
            if isinstance(reason_counts, dict):
                entry.setdefault("manual_review_reason_counts", dict(reason_counts))
            return entry
    return {}


def _summarize_dataset_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    source_counter: dict[str, int] = {}
    segmentation_counter: dict[str, int] = {}
    boundary_counter: dict[str, int] = {}
    injected_kind_counter: dict[str, int] = {}
    inject_strategy_counter: dict[str, int] = {}
    inject_quality_counter: dict[str, int] = {}
    judge_backend_counter: dict[str, int] = {}
    requested_backend_counter: dict[str, int] = {}
    effective_backend_counter: dict[str, int] = {}
    prompt_version_counter: dict[str, int] = {}
    corroboration_policy_counter: dict[str, int] = {}
    fallback_used_count = 0
    for item in records:
        source_id = str(item.get("source_id") or "")
        if source_id:
            source_counter[source_id] = int(source_counter.get(source_id, 0)) + 1
        segmentation_mode = str(item.get("source_segmentation_mode") or "")
        if segmentation_mode:
            segmentation_counter[segmentation_mode] = int(segmentation_counter.get(segmentation_mode, 0)) + 1
        boundary_pattern = str(item.get("source_boundary_pattern") or "")
        if boundary_pattern:
            boundary_counter[boundary_pattern] = int(boundary_counter.get(boundary_pattern, 0)) + 1
        injected_kind = str(item.get("injected_kind") or "")
        if injected_kind:
            injected_kind_counter[injected_kind] = int(injected_kind_counter.get(injected_kind, 0)) + 1
        inject_strategy = str(item.get("inject_strategy") or "")
        if inject_strategy:
            inject_strategy_counter[inject_strategy] = int(inject_strategy_counter.get(inject_strategy, 0)) + 1
        inject_quality_label = str(item.get("inject_quality_label") or "")
        if inject_quality_label:
            inject_quality_counter[inject_quality_label] = int(inject_quality_counter.get(inject_quality_label, 0)) + 1
        inject_judge_backend = str(item.get("inject_judge_backend") or "")
        if inject_judge_backend:
            judge_backend_counter[inject_judge_backend] = int(judge_backend_counter.get(inject_judge_backend, 0)) + 1
        judge_requested_backend = str(item.get("judge_requested_backend") or "")
        if judge_requested_backend:
            requested_backend_counter[judge_requested_backend] = (
                int(requested_backend_counter.get(judge_requested_backend, 0)) + 1
            )
        judge_effective_backend = str(item.get("judge_effective_backend") or "")
        if judge_effective_backend:
            effective_backend_counter[judge_effective_backend] = (
                int(effective_backend_counter.get(judge_effective_backend, 0)) + 1
            )
        judge_prompt_version = str(item.get("judge_prompt_version") or "")
        if judge_prompt_version:
            prompt_version_counter[judge_prompt_version] = int(prompt_version_counter.get(judge_prompt_version, 0)) + 1
        corroboration_policy = str((record_consistency_corroboration_policy(item) or {}).get("policy") or "")
        if corroboration_policy:
            corroboration_policy_counter[corroboration_policy] = (
                int(corroboration_policy_counter.get(corroboration_policy, 0)) + 1
            )
        if bool(item.get("judge_fallback_used")):
            fallback_used_count += 1

    return {
        "record_count": len(records),
        "unique_source_files": len(source_counter),
        "source_segmentation_mode_counts": segmentation_counter,
        "source_boundary_pattern_counts": boundary_counter,
        "injected_kind_counts": injected_kind_counter,
        "inject_strategy_counts": inject_strategy_counter,
        "inject_quality_distribution": inject_quality_counter,
        "judge_backend": next(iter(judge_backend_counter.keys()), ""),
        "requested_backend_counts": requested_backend_counter,
        "effective_backend_counts": effective_backend_counter,
        "prompt_version_counts": prompt_version_counter,
        "consistency_corroboration_policy_counts": corroboration_policy_counter,
        "local_profile_only_record_count": int(corroboration_policy_counter.get("local_profile_only", 0)),
        "fallback_used_count": fallback_used_count,
        "inject_record_count": int(sum(injected_kind_counter.values())),
        "generic_append_inject_present": bool(inject_strategy_counter.get("append_marker_statement", 0)),
        "growth_prefix_dataset": bool(records and str((records[0].get("dataset") or "")).startswith("DS-GROWTH-")),
    }


def get_rss_mb() -> float:
    if os.name != "nt":
        return 0.0
    try:
        import ctypes
        import ctypes.wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.wintypes.SIZE_T),
                ("WorkingSetSize", ctypes.wintypes.SIZE_T),
                ("QuotaPeakPagedPoolUsage", ctypes.wintypes.SIZE_T),
                ("QuotaPagedPoolUsage", ctypes.wintypes.SIZE_T),
                ("QuotaPeakNonPagedPoolUsage", ctypes.wintypes.SIZE_T),
                ("QuotaNonPagedPoolUsage", ctypes.wintypes.SIZE_T),
                ("PagefileUsage", ctypes.wintypes.SIZE_T),
                ("PeakPagefileUsage", ctypes.wintypes.SIZE_T),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if ok:
            return float(counters.WorkingSetSize) / (1024 * 1024)
    except Exception:
        return 0.0
    return 0.0


def _submit_wait_task(task: dict[str, Any]) -> dict[str, Any]:
    client = ApiClient(task["base_url"])
    run = submit_and_wait(
        client,
        project_id=task["project_id"],
        job_type=task["job_type"],
        inputs=task["inputs"],
        params=task.get("params") or {},
        timeout_sec=float(task.get("timeout_sec", 7200.0)),
    )
    return {"job_id": run.job_id, "status": run.status, "elapsed_ms": run.elapsed_ms}


def _call_with_stage(stage: str, func, /, *args, **kwargs):  # noqa: ANN001
    try:
        return func(*args, **kwargs)
    except BenchStageError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BenchStageError(stage, exc) from exc


def run_parallel_jobs(tasks: list[dict[str, Any]], *, parallelism: int) -> list[JobRun]:
    if not tasks:
        return []
    max_workers = max(1, min(parallelism, len(tasks)))
    if max_workers == 1:
        return [JobRun(**_submit_wait_task(task)) for task in tasks]

    results: list[JobRun] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_submit_wait_task, task) for task in tasks]
        for fut in concurrent.futures.as_completed(futures):
            results.append(JobRun(**fut.result()))
    return results


def _build_failure_payload(*, args: argparse.Namespace, stage_error: BenchStageError) -> dict[str, Any]:
    cause = stage_error.cause
    transport: dict[str, Any] | None = None
    request_path = ""
    error_class = type(cause).__name__
    error_message = str(cause)
    if isinstance(cause, ApiRequestError):
        transport = cause.to_dict()
        request_path = str(transport.get("request_path") or "")
        error_class = str(transport.get("error_class") or error_class)
        error_message = str(transport.get("detail") or error_message)
    return {
        "generated_at_utc": now_ts(),
        "ok": False,
        "failure_kind": "bench_transport_or_frontdoor",
        "attempt_stage": stage_error.stage,
        "attempt_index": 1 + int((transport or {}).get("retry_count") or 0),
        "base_url": args.base_url,
        "dataset_path": str(args.dataset),
        "bench_label": str(args.bench_label or ""),
        "profile": str(args.profile),
        "consistency_level": str(args.consistency_level),
        "request_method": str((transport or {}).get("method") or ""),
        "request_path": request_path,
        "request_body_shape": (transport or {}).get("request_body_shape"),
        "error_class": error_class,
        "error_message": error_message,
        "retry_count": int((transport or {}).get("retry_count") or 0),
        "retryable": bool((transport or {}).get("retryable", False)),
        "backoff_total_sec": float((transport or {}).get("backoff_total_sec") or 0.0),
        "transport": transport,
    }


def _render_failure_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Pipeline Benchmark Failure",
        "",
        f"- generated_at_utc: `{payload.get('generated_at_utc')}`",
        f"- attempt_stage: `{payload.get('attempt_stage')}`",
        f"- attempt_index: `{payload.get('attempt_index')}`",
        f"- base_url: `{payload.get('base_url')}`",
        f"- dataset_path: `{payload.get('dataset_path')}`",
        f"- bench_label: `{payload.get('bench_label')}`",
        f"- profile: `{payload.get('profile')}`",
        f"- consistency_level: `{payload.get('consistency_level')}`",
        f"- request_method: `{payload.get('request_method')}`",
        f"- request_path: `{payload.get('request_path')}`",
        f"- request_body_shape: `{payload.get('request_body_shape')}`",
        f"- error_class: `{payload.get('error_class')}`",
        f"- error_message: `{payload.get('error_message')}`",
        f"- retry_count: `{payload.get('retry_count')}`",
        f"- retryable: `{payload.get('retryable')}`",
        f"- backoff_total_sec: `{payload.get('backoff_total_sec')}`",
        f"- transport: `{payload.get('transport')}`",
        "",
    ]
    return "\n".join(lines)


def _probe_frontdoor(client: ApiClient) -> dict[str, Any]:
    started = time.perf_counter()
    response = client.get("/health")
    return {
        "request_path": "/health",
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "response": response,
    }


_CONSISTENCY_SIGNAL_EXCERPT_CHARS = 20000
_CONSISTENCY_SIGNAL_SCORE_CAP_PER_SLOT = 2
_CONSISTENCY_SIGNAL_PIPELINE: ExtractionPipeline | None = None


def _get_consistency_signal_pipeline() -> ExtractionPipeline:
    global _CONSISTENCY_SIGNAL_PIPELINE
    if _CONSISTENCY_SIGNAL_PIPELINE is None:
        _CONSISTENCY_SIGNAL_PIPELINE = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)
    return _CONSISTENCY_SIGNAL_PIPELINE


def _consistency_signal_summary(text: str) -> dict[str, Any]:
    excerpt = str(text or "")[:_CONSISTENCY_SIGNAL_EXCERPT_CHARS]
    if not excerpt.strip():
        return {"score": 0, "signal_counts": {}, "first_signal_offset": None}
    claims = extract_consistency_claims(excerpt, pipeline=_get_consistency_signal_pipeline(), stats={})
    signal_counts: dict[str, int] = {}
    score = 0
    first_signal_offset: int | None = None
    for claim in claims:
        slot_key = str(claim.get("slot_key") or "").strip().lower()
        if not slot_key:
            continue
        signal_counts[slot_key] = int(signal_counts.get(slot_key, 0)) + 1
        claim_start = claim.get("claim_start")
        try:
            candidate_offset = int(claim_start)
        except (TypeError, ValueError):
            candidate_offset = None
        if candidate_offset is None:
            continue
        if first_signal_offset is None or candidate_offset < first_signal_offset:
            first_signal_offset = max(0, candidate_offset)
    for matched in signal_counts.values():
        score += min(int(matched), _CONSISTENCY_SIGNAL_SCORE_CAP_PER_SLOT)
    return {"score": score, "signal_counts": signal_counts, "first_signal_offset": first_signal_offset}


def _pick_consistency_targets(
    doc_ids: list[str],
    *,
    records: list[dict[str, Any]] | None = None,
    sample_count: int,
    seed: int,
    range_chars: int = 5000,
    include_local_profile_only: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    limit = max(1, min(sample_count, len(doc_ids)))
    rng = random.Random(seed)
    indexed = list(range(len(doc_ids)))
    rng.shuffle(indexed)
    score_by_index: dict[int, int] = {}
    signal_counts_by_index: dict[int, dict[str, int]] = {}
    first_signal_offset_by_index: dict[int, int | None] = {}
    text_len_by_index: dict[int, int] = {}
    corroboration_policy_by_index: dict[int, str] = {}
    local_profile_only_indices: set[int] = set()
    if isinstance(records, list) and len(records) == len(doc_ids):
        for idx, item in enumerate(records):
            text = str(item.get("content") or "")
            summary = _consistency_signal_summary(text)
            score_by_index[idx] = int(summary.get("score", 0))
            signal_counts_by_index[idx] = dict(summary.get("signal_counts") or {})
            first_signal_offset_by_index[idx] = summary.get("first_signal_offset")
            text_len_by_index[idx] = len(text)
            corroboration_policy = str((record_consistency_corroboration_policy(item) or {}).get("policy") or "default")
            corroboration_policy_by_index[idx] = corroboration_policy
            if corroboration_policy == "local_profile_only":
                local_profile_only_indices.add(idx)
    eligible_index_pool = list(indexed)
    local_profile_policy_fallback = False
    if local_profile_only_indices and not include_local_profile_only:
        filtered_pool = [idx for idx in indexed if idx not in local_profile_only_indices]
        if filtered_pool:
            eligible_index_pool = filtered_pool
        else:
            local_profile_policy_fallback = True
    prioritized = sorted(
        eligible_index_pool,
        key=lambda idx: (int(score_by_index.get(idx, 0)) <= 0, -int(score_by_index.get(idx, 0))),
    )
    chosen = prioritized[:limit]

    selected_targets: list[dict[str, Any]] = []
    selected_score_counts: dict[str, int] = {}
    selected_signal_type_counts: dict[str, int] = {}
    signal_positive_docs_total = sum(1 for idx in eligible_index_pool if int(score_by_index.get(idx, 0)) > 0)
    selected_signal_positive_docs = 0
    selected_window_sample: list[dict[str, Any]] = []
    selected_local_profile_only_docs = 0
    for idx in chosen:
        score = int(score_by_index.get(idx, 0))
        selected_score_counts[str(score)] = int(selected_score_counts.get(str(score), 0)) + 1
        if score > 0:
            selected_signal_positive_docs += 1
        if corroboration_policy_by_index.get(idx) == "local_profile_only":
            selected_local_profile_only_docs += 1
        for key, value in signal_counts_by_index.get(idx, {}).items():
            selected_signal_type_counts[key] = int(selected_signal_type_counts.get(key, 0)) + int(value)
        text_len = max(0, int(text_len_by_index.get(idx, 0)))
        first_offset = first_signal_offset_by_index.get(idx)
        if isinstance(first_offset, int):
            start = max(0, first_offset - min(250, first_offset))
        else:
            start = 0
        end = min(text_len, start + max(1, int(range_chars)))
        target = {
            "doc_id": doc_ids[idx],
            "range": {"start": start, "end": end},
            "signal_score": score,
            "first_signal_offset": first_offset,
        }
        selected_targets.append(target)
        if len(selected_window_sample) < 8:
            selected_window_sample.append(
                {
                    "doc_id": doc_ids[idx],
                    "range_start": start,
                    "range_end": end,
                    "signal_score": score,
                    "first_signal_offset": first_offset,
                }
            )
    summary = {
        "mode": "signal_priority_then_signal_window",
        "sample_count": len(chosen),
        "signal_positive_docs_total": signal_positive_docs_total,
        "selected_signal_positive_docs": selected_signal_positive_docs,
        "include_local_profile_only": bool(include_local_profile_only),
        "local_profile_policy_fallback": bool(local_profile_policy_fallback),
        "local_profile_only_docs_total": len(local_profile_only_indices),
        "skipped_local_profile_only_docs": (
            len(local_profile_only_indices) if local_profile_only_indices and not local_profile_policy_fallback and not include_local_profile_only else 0
        ),
        "selected_local_profile_only_docs": selected_local_profile_only_docs,
        "selected_score_counts": selected_score_counts,
        "selected_signal_type_counts": selected_signal_type_counts,
        "selected_window_sample": selected_window_sample,
    }
    return selected_targets, summary


_GRAPH_TIME_SIGNAL_RE = re.compile(r"\d+\s*(?:일|달|개월|년)\s*(?:후|뒤|전)")
_GRAPH_TIME_SIGNAL_TOKENS = (
    "다음 날",
    "그날",
    "이튿날",
    "며칠 후",
    "며칠 뒤",
    "첫날",
    "둘째 날",
    "셋째 날",
)
_GRAPH_TIMELINE_SIGNAL_TOKENS = (
    "연회",
    "회의",
    "축제",
    "결투",
    "전투",
    "재판",
    "원정",
    "즉위식",
    "장례식",
    "혼인",
    "약혼",
)
_GRAPH_ENTITY_ALIAS_RE = re.compile(
    r"[가-힣]{2,5}\s*(?:님|군|씨|공|왕|황제|대공|공작|후작|백작|영애|아가씨|공주|황녀|전하|폐하)"
)
_GRAPH_QUERY_SAMPLE_LIMIT = 8
_CONSISTENCY_SLOT_DIAGNOSTIC_KEYS = (
    "claim_slot_counts",
    "anchor_filtered_slot_counts",
    "unknown_slot_counts",
    "no_evidence_slot_counts",
)
_GRAPH_SIGNAL_PRIORITY = {
    "entity_alias": 0,
    "timeline_signal": 1,
    "time_anchor": 2,
}


def _compact_query_text(text: str, *, limit: int = 120) -> str:
    compact = " ".join((text or "").split()).strip()
    return compact[:limit].strip()


def _graph_time_signal_span(text: str) -> tuple[int, int] | None:
    for token in _GRAPH_TIME_SIGNAL_TOKENS:
        idx = text.find(token)
        if idx >= 0:
            return idx, idx + len(token)
    match = _GRAPH_TIME_SIGNAL_RE.search(text)
    if match is not None:
        return match.start(), match.end()
    return None


def _graph_timeline_signal_span(text: str) -> tuple[int, int] | None:
    for token in _GRAPH_TIMELINE_SIGNAL_TOKENS:
        idx = text.find(token)
        if idx >= 0:
            return idx, idx + len(token)
    return None


def _graph_entity_alias_span(text: str) -> tuple[int, int] | None:
    match = _GRAPH_ENTITY_ALIAS_RE.search(text)
    if match is None:
        return None
    return match.start(), match.end()


def _classify_graph_query_signal_types(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    compact = _compact_query_text(text, limit=400)
    signal_types: list[str] = []
    if _graph_entity_alias_span(compact) is not None:
        signal_types.append("entity_alias")
    if _graph_timeline_signal_span(compact) is not None:
        signal_types.append("timeline_signal")
    if _graph_time_signal_span(compact) is not None:
        signal_types.append("time_anchor")
    return signal_types


def _best_graph_signal_span(text: str) -> tuple[int, int] | None:
    compact = _compact_query_text(text, limit=400)
    spans: list[tuple[int, int, int]] = []
    for signal_type, span in (
        ("entity_alias", _graph_entity_alias_span(compact)),
        ("timeline_signal", _graph_timeline_signal_span(compact)),
        ("time_anchor", _graph_time_signal_span(compact)),
    ):
        if span is None:
            continue
        spans.append((_GRAPH_SIGNAL_PRIORITY[signal_type], span[0], span[1]))
    if not spans:
        return None
    _priority, start, end = min(spans)
    return start, end


def _extract_graph_signal_query(text: str, *, limit: int = 120) -> str:
    compact_source = " ".join((text or "").split()).strip()
    if not compact_source:
        return ""
    signal_span = _best_graph_signal_span(compact_source)
    if signal_span is None:
        return compact_source[:limit].strip()
    start_idx = max(0, signal_span[0] - 40)
    end_idx = min(len(compact_source), start_idx + limit)
    snippet = compact_source[start_idx:end_idx].strip()
    return snippet[:limit].strip()


def _has_graph_query_signal(text: str) -> bool:
    return bool(_classify_graph_query_signal_types(text))


def _pick_retrieval_query_candidates(
    records: list[dict[str, Any]],
    *,
    limit: int,
    seed: int,
    graph_enabled: bool = False,
    index_runtime: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    def _graph_seed_capabilities(raw: dict[str, Any] | None) -> dict[str, bool]:
        if not isinstance(raw, dict):
            return {"entity_alias": True, "timeline_signal": True, "time_anchor": True}
        graph_index = raw.get("graph_index")
        if not isinstance(graph_index, dict):
            graph_index = {}
        return {
            "entity_alias": _as_int(raw.get("entity_mentions_created"), 0) > 0
            or _as_int(graph_index.get("nodes_entity"), 0) > 0,
            "timeline_signal": _as_int(raw.get("timeline_events_created"), 0) > 0
            or _as_int(graph_index.get("nodes_timeline"), 0) > 0,
            "time_anchor": _as_int(raw.get("time_anchors_created"), 0) > 0
            or _as_int(graph_index.get("nodes_time"), 0) > 0,
        }

    def _preferred_bucket(signal_types: list[str], capabilities: dict[str, bool]) -> str | None:
        if "time_anchor" in signal_types and capabilities.get("time_anchor", False):
            return "time_anchor"
        if "timeline_signal" in signal_types and capabilities.get("timeline_signal", False):
            return "timeline_signal"
        if "entity_alias" in signal_types and capabilities.get("entity_alias", False):
            return "entity_alias"
        return None

    indices = list(range(len(records)))
    rng = random.Random(seed + 17)
    rng.shuffle(indices)
    preferred_buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in _GRAPH_SIGNAL_PRIORITY}
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    seed_capabilities = _graph_seed_capabilities(index_runtime) if graph_enabled else {}
    for idx in indices:
        record = records[idx]
        raw_text = str(record.get("content") or "")
        if not raw_text.strip():
            continue
        signal_types = _classify_graph_query_signal_types(raw_text)
        query_text = (
            _extract_graph_signal_query(raw_text, limit=120)
            if graph_enabled
            else _compact_query_text(raw_text, limit=120)
        )
        if not query_text or query_text in seen:
            continue
        seen.add(query_text)
        candidate = {
            "query": query_text,
            "signal_types": list(signal_types),
            "source_id": str(record.get("source_id") or ""),
            "episode_no": _as_int(record.get("episode_no"), 0),
        }
        preferred_bucket = _preferred_bucket(signal_types, seed_capabilities) if graph_enabled else None
        if preferred_bucket is not None:
            preferred_buckets[preferred_bucket].append(candidate)
        else:
            picked.append(candidate)
    ordered: list[dict[str, Any]] = []
    for key in ("time_anchor", "timeline_signal", "entity_alias"):
        ordered.extend(preferred_buckets[key])
    ordered.extend(picked)
    return ordered[:limit]


def _pick_retrieval_queries(records: list[dict[str, Any]], *, limit: int, seed: int, graph_enabled: bool = False) -> list[str]:
    return [
        str(item.get("query") or "")
        for item in _pick_retrieval_query_candidates(
            records,
            limit=limit,
            seed=seed,
            graph_enabled=graph_enabled,
        )
        if isinstance(item, dict) and str(item.get("query") or "")
    ]


def _build_index_fts_params(*, graph_enabled: bool, index_grouping_enabled: bool = False) -> dict[str, Any]:
    if not graph_enabled and not index_grouping_enabled:
        return {}
    return {
        "grouping": {
            "entity_mentions": True,
            "time_anchors": True,
            "graph_extract": True,
        }
    }


def _extract_index_fts_graph_runtime(events: list[tuple[int, dict[str, Any]]]) -> dict[str, Any]:
    for _seq, event in reversed(events):
        message = str((event.get("message") or "")).strip().lower()
        if message != "fts indexed":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        graph_info = payload.get("graph")
        graph_index = payload.get("graph_index")
        return {
            "graph_extract_enabled": bool(payload.get("graph_extract_enabled", False)),
            "entity_mentions_created": _as_int(payload.get("entity_mentions_created"), 0),
            "time_anchors_created": _as_int(payload.get("time_anchors_created"), 0),
            "timeline_events_created": _as_int(payload.get("timeline_events_created"), 0),
            "graph_index": dict(graph_index) if isinstance(graph_index, dict) else {},
            "graph": dict(graph_info) if isinstance(graph_info, dict) else {},
        }
    return {
        "graph_extract_enabled": False,
        "entity_mentions_created": 0,
        "time_anchors_created": 0,
        "timeline_events_created": 0,
        "graph_index": {},
        "graph": {},
    }


def _build_consistency_params(
    *,
    consistency_level: str,
    evidence_link_policy: str,
    evidence_link_cap: int,
    graph_mode_override: str | None = None,
    metadata_grouping_override: bool | None = None,
    layer3_verdict_promotion_override: bool | None = None,
    verifier_mode_override: str | None = None,
    triage_mode_override: str | None = None,
    triage_anomaly_threshold_override: float | None = None,
    triage_max_segments_override: int | None = None,
    verification_loop_enabled_override: bool | None = None,
    verification_loop_max_rounds_override: int | None = None,
    verification_loop_timeout_ms_override: int | None = None,
) -> tuple[dict[str, Any], str]:
    level = str(consistency_level or "quick").strip().lower()
    if level not in {"quick", "deep", "strict"}:
        level = "quick"

    consistency_params: dict[str, Any] = {
        "evidence_link_policy": evidence_link_policy,
        "evidence_link_cap": evidence_link_cap,
        "graph_mode": "off",
        "graph_expand_enabled": False,
        "metadata_grouping_enabled": False,
        "layer3_verdict_promotion": False,
        "verifier": {
            "mode": "off",
            "promote_ok_threshold": 0.95,
            "contradict_alert_threshold": 0.70,
            "max_claim_chars": 220,
        },
        "triage": {
            "mode": "off",
            "anomaly_threshold": 0.65,
            "max_segments_per_run": 8,
        },
        "verification_loop": {
            "enabled": False,
            "max_rounds": 2,
            "round_timeout_ms": 250,
        },
    }
    if level in {"deep", "strict"}:
        consistency_params["graph_mode"] = "auto"
        consistency_params["graph_expand_enabled"] = True
        consistency_params["metadata_grouping_enabled"] = True
        consistency_params["layer3_verdict_promotion"] = True
        consistency_params["triage"] = {
            "mode": "embedding_anomaly",
            "anomaly_threshold": 0.65,
            "max_segments_per_run": 8,
        }
    if level == "strict":
        consistency_params["verifier"] = {
            "mode": "conservative_nli",
            "promote_ok_threshold": 0.95,
            "contradict_alert_threshold": 0.70,
            "max_claim_chars": 220,
        }
        consistency_params["verification_loop"] = {
            "enabled": True,
            "max_rounds": 2,
            "round_timeout_ms": 800,
        }
    if graph_mode_override in {"off", "manual", "auto"}:
        consistency_params["graph_mode"] = graph_mode_override
    if metadata_grouping_override is not None:
        consistency_params["metadata_grouping_enabled"] = bool(metadata_grouping_override)
    if layer3_verdict_promotion_override is not None:
        consistency_params["layer3_verdict_promotion"] = bool(layer3_verdict_promotion_override)
    verifier = dict(consistency_params.get("verifier") or {})
    if verifier_mode_override in {"off", "conservative_nli"}:
        verifier["mode"] = verifier_mode_override
    consistency_params["verifier"] = verifier
    triage = dict(consistency_params.get("triage") or {})
    if triage_mode_override in {"off", "embedding_anomaly"}:
        triage["mode"] = triage_mode_override
    if triage_anomaly_threshold_override is not None:
        triage["anomaly_threshold"] = max(0.0, min(1.0, float(triage_anomaly_threshold_override)))
    if triage_max_segments_override is not None:
        triage["max_segments_per_run"] = max(1, int(triage_max_segments_override))
    consistency_params["triage"] = triage
    verification_loop = dict(consistency_params.get("verification_loop") or {})
    if verification_loop_enabled_override is not None:
        verification_loop["enabled"] = bool(verification_loop_enabled_override)
    if verification_loop_max_rounds_override is not None:
        verification_loop["max_rounds"] = max(1, int(verification_loop_max_rounds_override))
    if verification_loop_timeout_ms_override is not None:
        verification_loop["round_timeout_ms"] = max(1, int(verification_loop_timeout_ms_override))
    consistency_params["verification_loop"] = verification_loop
    return {"consistency": consistency_params}, level


def _accumulate_unknown_reason_counts(target: dict[str, int], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            continue
        target[key] = int(target.get(key, 0)) + _as_int(value, 0)


def _accumulate_reason_list_counts(target: dict[str, int], raw: Any) -> None:
    if not isinstance(raw, list):
        return
    for item in raw:
        if not isinstance(item, str) or not item:
            continue
        target[item] = int(target.get(item, 0)) + 1


def _choice_to_bool(value: str | None) -> bool | None:
    if value == "on":
        return True
    if value == "off":
        return False
    return None


def _accumulate_numeric_samples(target: list[float], raw: Any, *, limit: int = 512) -> None:
    if not isinstance(target, list) or not isinstance(raw, list):
        return
    remaining = max(0, int(limit) - len(target))
    if remaining <= 0:
        return
    for item in raw:
        if remaining <= 0:
            break
        try:
            parsed = float(item)
        except (TypeError, ValueError):
            continue
        target.append(parsed)
        remaining -= 1


def _new_consistency_runtime(*, graph_mode: str) -> dict[str, Any]:
    return {
        "graph_mode": graph_mode,
        "jobs_sampled": 0,
        "jobs_with_claims_total": 0,
        "segment_count_total": 0,
        "segments_with_claims_count_total": 0,
        "claim_count_total": 0,
        "claims_processed_total": 0,
        "claims_skipped_low_confidence_total": 0,
        "claim_slot_counts": {},
        "slot_matches_total": 0,
        "slot_candidate_count_total": 0,
        "slot_candidate_selected_total": 0,
        "avg_slot_confidence_sum": 0.0,
        "avg_slot_confidence_samples": 0,
        "triage_total_claims_total": 0,
        "triage_selected_claims_total": 0,
        "triage_skipped_claims_total": 0,
        "graph_expand_applied_count": 0,
        "graph_auto_trigger_count": 0,
        "graph_auto_skip_count": 0,
        "layer3_rerank_applied_count": 0,
        "layer3_model_fallback_count": 0,
        "layer3_model_enabled_jobs": 0,
        "layer3_local_nli_enabled_jobs": 0,
        "layer3_remote_api_enabled_jobs": 0,
        "layer3_local_reranker_enabled_jobs": 0,
        "layer3_nli_capable_jobs": 0,
        "layer3_reranker_capable_jobs": 0,
        "layer3_effective_capable_jobs": 0,
        "layer3_promotion_enabled_jobs": 0,
        "layer3_inactive_reason_counts": {},
        "verification_loop_trigger_count": 0,
        "verification_loop_attempted_rounds_total": 0,
        "verification_loop_rounds_total": 0,
        "verification_loop_timeout_count": 0,
        "verification_loop_stagnation_break_count": 0,
        "verification_loop_round_elapsed_ms_sum": 0.0,
        "verification_loop_round_elapsed_ms_max": 0.0,
        "verification_loop_round_elapsed_ms_samples": [],
        "verification_loop_candidate_growth_total": 0,
        "verification_loop_candidate_growth_samples": [],
        "verification_loop_exit_reason_counts": {},
        "verification_loop_reason_transition_counts": {},
        "self_evidence_filtered_count": 0,
        "retrieval_anchor_filtered_count": 0,
        "anchor_filtered_slot_counts": {},
        "snippet_slot_cache_hit_count": 0,
        "snippet_slot_cache_miss_count": 0,
        "anchor_rescue_attempt_count": 0,
        "anchor_rescue_ok_count": 0,
        "snippet_corroborated_count": 0,
        "slot_diagnostics_present_jobs": 0,
        "slot_diagnostics_partial_jobs": 0,
        "slot_diagnostics_missing_jobs": 0,
        "slot_diagnostics_missing_with_claims_jobs": 0,
        "layer3_promoted_ok_count": 0,
        "vid_count_total": 0,
        "violate_count_total": 0,
        "unknown_count_total": 0,
        "unknown_reason_counts": {},
        "unknown_slot_counts": {},
        "no_evidence_slot_counts": {},
    }


def _accumulate_consistency_runtime(runtime: dict[str, Any], payload: dict[str, Any]) -> None:
    runtime["jobs_sampled"] = _as_int(runtime.get("jobs_sampled"), 0) + 1
    claim_count = _as_int(payload.get("claim_count"))
    if claim_count > 0:
        runtime["jobs_with_claims_total"] = _as_int(runtime.get("jobs_with_claims_total"), 0) + 1
    slot_diagnostic_fields_present = 0
    for field_name in _CONSISTENCY_SLOT_DIAGNOSTIC_KEYS:
        if field_name in payload and isinstance(payload.get(field_name), dict):
            slot_diagnostic_fields_present += 1
    if slot_diagnostic_fields_present >= len(_CONSISTENCY_SLOT_DIAGNOSTIC_KEYS):
        runtime["slot_diagnostics_present_jobs"] = _as_int(runtime.get("slot_diagnostics_present_jobs"), 0) + 1
    elif slot_diagnostic_fields_present > 0:
        runtime["slot_diagnostics_partial_jobs"] = _as_int(runtime.get("slot_diagnostics_partial_jobs"), 0) + 1
    else:
        runtime["slot_diagnostics_missing_jobs"] = _as_int(runtime.get("slot_diagnostics_missing_jobs"), 0) + 1
    if claim_count > 0 and slot_diagnostic_fields_present < len(_CONSISTENCY_SLOT_DIAGNOSTIC_KEYS):
        runtime["slot_diagnostics_missing_with_claims_jobs"] = _as_int(
            runtime.get("slot_diagnostics_missing_with_claims_jobs"),
            0,
        ) + 1
    runtime["segment_count_total"] = _as_int(runtime.get("segment_count_total"), 0) + _as_int(payload.get("segment_count"))
    runtime["segments_with_claims_count_total"] = _as_int(
        runtime.get("segments_with_claims_count_total"),
        0,
    ) + _as_int(payload.get("segments_with_claims_count"))
    runtime["claim_count_total"] = _as_int(runtime.get("claim_count_total"), 0) + claim_count
    runtime["claims_processed_total"] = _as_int(
        runtime.get("claims_processed_total"),
        0,
    ) + _as_int(payload.get("claims_processed"))
    runtime["claims_skipped_low_confidence_total"] = _as_int(
        runtime.get("claims_skipped_low_confidence_total"),
        0,
    ) + _as_int(payload.get("claims_skipped_low_confidence"))
    claim_slot_counts = runtime.get("claim_slot_counts")
    if not isinstance(claim_slot_counts, dict):
        claim_slot_counts = {}
        runtime["claim_slot_counts"] = claim_slot_counts
    _accumulate_unknown_reason_counts(claim_slot_counts, payload.get("claim_slot_counts"))
    runtime["slot_matches_total"] = _as_int(runtime.get("slot_matches_total"), 0) + _as_int(payload.get("slot_matches"))
    runtime["slot_candidate_count_total"] = _as_int(
        runtime.get("slot_candidate_count_total"),
        0,
    ) + _as_int(payload.get("slot_candidate_count"))
    runtime["slot_candidate_selected_total"] = _as_int(
        runtime.get("slot_candidate_selected_total"),
        0,
    ) + _as_int(payload.get("slot_candidate_selected"))
    avg_slot_confidence = payload.get("avg_slot_confidence")
    if avg_slot_confidence is not None:
        runtime["avg_slot_confidence_sum"] = _as_float(runtime.get("avg_slot_confidence_sum"), 0.0) + _as_float(
            avg_slot_confidence,
            0.0,
        )
        runtime["avg_slot_confidence_samples"] = _as_int(runtime.get("avg_slot_confidence_samples"), 0) + 1
    runtime["triage_total_claims_total"] = _as_int(
        runtime.get("triage_total_claims_total"),
        0,
    ) + _as_int(payload.get("triage_total_claims"))
    runtime["triage_selected_claims_total"] = _as_int(
        runtime.get("triage_selected_claims_total"),
        0,
    ) + _as_int(payload.get("triage_selected_claims"))
    runtime["triage_skipped_claims_total"] = _as_int(
        runtime.get("triage_skipped_claims_total"),
        0,
    ) + _as_int(payload.get("triage_skipped_claims"))
    runtime["graph_expand_applied_count"] = _as_int(runtime.get("graph_expand_applied_count"), 0) + _as_int(
        payload.get("graph_expand_applied_count")
    )
    runtime["graph_auto_trigger_count"] = _as_int(runtime.get("graph_auto_trigger_count"), 0) + _as_int(
        payload.get("graph_auto_trigger_count")
    )
    runtime["graph_auto_skip_count"] = _as_int(runtime.get("graph_auto_skip_count"), 0) + _as_int(
        payload.get("graph_auto_skip_count")
    )
    runtime["layer3_rerank_applied_count"] = _as_int(runtime.get("layer3_rerank_applied_count"), 0) + _as_int(
        payload.get("layer3_rerank_applied_count")
    )
    runtime["layer3_model_fallback_count"] = _as_int(runtime.get("layer3_model_fallback_count"), 0) + _as_int(
        payload.get("layer3_model_fallback_count")
    )
    runtime["layer3_model_enabled_jobs"] = _as_int(runtime.get("layer3_model_enabled_jobs"), 0) + (
        1 if bool(payload.get("layer3_model_enabled")) else 0
    )
    runtime["layer3_local_nli_enabled_jobs"] = _as_int(runtime.get("layer3_local_nli_enabled_jobs"), 0) + (
        1 if bool(payload.get("layer3_local_nli_enabled")) else 0
    )
    runtime["layer3_remote_api_enabled_jobs"] = _as_int(runtime.get("layer3_remote_api_enabled_jobs"), 0) + (
        1 if bool(payload.get("layer3_remote_api_enabled")) else 0
    )
    runtime["layer3_local_reranker_enabled_jobs"] = _as_int(runtime.get("layer3_local_reranker_enabled_jobs"), 0) + (
        1 if bool(payload.get("layer3_local_reranker_enabled")) else 0
    )
    runtime["layer3_nli_capable_jobs"] = _as_int(runtime.get("layer3_nli_capable_jobs"), 0) + (
        1 if bool(payload.get("layer3_nli_capable")) else 0
    )
    runtime["layer3_reranker_capable_jobs"] = _as_int(runtime.get("layer3_reranker_capable_jobs"), 0) + (
        1 if bool(payload.get("layer3_reranker_capable")) else 0
    )
    runtime["layer3_effective_capable_jobs"] = _as_int(runtime.get("layer3_effective_capable_jobs"), 0) + (
        1 if bool(payload.get("layer3_effective_capable")) else 0
    )
    runtime["layer3_promotion_enabled_jobs"] = _as_int(runtime.get("layer3_promotion_enabled_jobs"), 0) + (
        1 if bool(payload.get("layer3_promotion_enabled")) else 0
    )
    inactive_reason_counts = runtime.get("layer3_inactive_reason_counts")
    if not isinstance(inactive_reason_counts, dict):
        inactive_reason_counts = {}
        runtime["layer3_inactive_reason_counts"] = inactive_reason_counts
    _accumulate_reason_list_counts(inactive_reason_counts, payload.get("layer3_inactive_reasons"))
    runtime["verification_loop_trigger_count"] = _as_int(runtime.get("verification_loop_trigger_count"), 0) + _as_int(
        payload.get("verification_loop_trigger_count")
    )
    runtime["verification_loop_attempted_rounds_total"] = _as_int(
        runtime.get("verification_loop_attempted_rounds_total"),
        0,
    ) + _as_int(payload.get("verification_loop_attempted_rounds_total"))
    runtime["verification_loop_rounds_total"] = _as_int(runtime.get("verification_loop_rounds_total"), 0) + _as_int(
        payload.get("verification_loop_rounds_total")
    )
    runtime["verification_loop_timeout_count"] = _as_int(runtime.get("verification_loop_timeout_count"), 0) + _as_int(
        payload.get("verification_loop_timeout_count")
    )
    runtime["verification_loop_stagnation_break_count"] = _as_int(
        runtime.get("verification_loop_stagnation_break_count"),
        0,
    ) + _as_int(payload.get("verification_loop_stagnation_break_count"))
    runtime["verification_loop_round_elapsed_ms_sum"] = float(
        runtime.get("verification_loop_round_elapsed_ms_sum", 0.0)
    ) + _as_float(payload.get("verification_loop_round_elapsed_ms_sum"), 0.0)
    runtime["verification_loop_round_elapsed_ms_max"] = max(
        _as_float(runtime.get("verification_loop_round_elapsed_ms_max"), 0.0),
        _as_float(payload.get("verification_loop_round_elapsed_ms_max"), 0.0),
    )
    round_elapsed_samples = runtime.get("verification_loop_round_elapsed_ms_samples")
    if not isinstance(round_elapsed_samples, list):
        round_elapsed_samples = []
        runtime["verification_loop_round_elapsed_ms_samples"] = round_elapsed_samples
    _accumulate_numeric_samples(round_elapsed_samples, payload.get("verification_loop_round_elapsed_ms_samples"))
    runtime["verification_loop_candidate_growth_total"] = _as_int(
        runtime.get("verification_loop_candidate_growth_total"),
        0,
    ) + _as_int(payload.get("verification_loop_candidate_growth_total"))
    candidate_growth_samples = runtime.get("verification_loop_candidate_growth_samples")
    if not isinstance(candidate_growth_samples, list):
        candidate_growth_samples = []
        runtime["verification_loop_candidate_growth_samples"] = candidate_growth_samples
    _accumulate_numeric_samples(candidate_growth_samples, payload.get("verification_loop_candidate_growth_samples"))
    runtime["self_evidence_filtered_count"] = _as_int(runtime.get("self_evidence_filtered_count"), 0) + _as_int(
        payload.get("self_evidence_filtered_count")
    )
    runtime["retrieval_anchor_filtered_count"] = _as_int(
        runtime.get("retrieval_anchor_filtered_count"),
        0,
    ) + _as_int(payload.get("retrieval_anchor_filtered_count"))
    anchor_filtered_slot_counts = runtime.get("anchor_filtered_slot_counts")
    if not isinstance(anchor_filtered_slot_counts, dict):
        anchor_filtered_slot_counts = {}
        runtime["anchor_filtered_slot_counts"] = anchor_filtered_slot_counts
    _accumulate_unknown_reason_counts(anchor_filtered_slot_counts, payload.get("anchor_filtered_slot_counts"))
    runtime["snippet_slot_cache_hit_count"] = _as_int(runtime.get("snippet_slot_cache_hit_count"), 0) + _as_int(
        payload.get("snippet_slot_cache_hit_count")
    )
    runtime["snippet_slot_cache_miss_count"] = _as_int(runtime.get("snippet_slot_cache_miss_count"), 0) + _as_int(
        payload.get("snippet_slot_cache_miss_count")
    )
    runtime["anchor_rescue_attempt_count"] = _as_int(runtime.get("anchor_rescue_attempt_count"), 0) + _as_int(
        payload.get("anchor_rescue_attempt_count")
    )
    runtime["anchor_rescue_ok_count"] = _as_int(runtime.get("anchor_rescue_ok_count"), 0) + _as_int(
        payload.get("anchor_rescue_ok_count")
    )
    runtime["snippet_corroborated_count"] = _as_int(runtime.get("snippet_corroborated_count"), 0) + _as_int(
        payload.get("snippet_corroborated_count")
    )
    runtime["layer3_promoted_ok_count"] = _as_int(runtime.get("layer3_promoted_ok_count"), 0) + _as_int(
        payload.get("layer3_promoted_ok_count")
    )
    runtime["vid_count_total"] = _as_int(runtime.get("vid_count_total"), 0) + _as_int(payload.get("vid_count"))
    runtime["violate_count_total"] = _as_int(runtime.get("violate_count_total"), 0) + _as_int(payload.get("violate_count"))
    runtime["unknown_count_total"] = _as_int(runtime.get("unknown_count_total"), 0) + _as_int(payload.get("unknown_count"))
    reason_counts = runtime.get("unknown_reason_counts")
    if not isinstance(reason_counts, dict):
        reason_counts = {}
        runtime["unknown_reason_counts"] = reason_counts
    _accumulate_unknown_reason_counts(reason_counts, payload.get("unknown_reason_counts"))
    unknown_slot_counts = runtime.get("unknown_slot_counts")
    if not isinstance(unknown_slot_counts, dict):
        unknown_slot_counts = {}
        runtime["unknown_slot_counts"] = unknown_slot_counts
    _accumulate_unknown_reason_counts(unknown_slot_counts, payload.get("unknown_slot_counts"))
    no_evidence_slot_counts = runtime.get("no_evidence_slot_counts")
    if not isinstance(no_evidence_slot_counts, dict):
        no_evidence_slot_counts = {}
        runtime["no_evidence_slot_counts"] = no_evidence_slot_counts
    _accumulate_unknown_reason_counts(no_evidence_slot_counts, payload.get("no_evidence_slot_counts"))
    exit_reason_counts = runtime.get("verification_loop_exit_reason_counts")
    if not isinstance(exit_reason_counts, dict):
        exit_reason_counts = {}
        runtime["verification_loop_exit_reason_counts"] = exit_reason_counts
    _accumulate_unknown_reason_counts(exit_reason_counts, payload.get("verification_loop_exit_reason_counts"))
    transition_counts = runtime.get("verification_loop_reason_transition_counts")
    if not isinstance(transition_counts, dict):
        transition_counts = {}
        runtime["verification_loop_reason_transition_counts"] = transition_counts
    _accumulate_unknown_reason_counts(transition_counts, payload.get("verification_loop_reason_transition_counts"))
    mode = payload.get("graph_mode")
    if isinstance(mode, str) and mode:
        runtime["graph_mode"] = mode


def _finalize_consistency_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    runtime_out = dict(runtime)
    vid_total = max(0, _as_int(runtime_out.get("vid_count_total"), 0))
    violate_total = max(0, _as_int(runtime_out.get("violate_count_total"), 0))
    unknown_total = max(0, _as_int(runtime_out.get("unknown_count_total"), 0))
    segment_count_total = max(0, _as_int(runtime_out.get("segment_count_total"), 0))
    segments_with_claims_total = max(0, _as_int(runtime_out.get("segments_with_claims_count_total"), 0))
    claim_count_total = max(0, _as_int(runtime_out.get("claim_count_total"), 0))
    claims_processed_total = max(0, _as_int(runtime_out.get("claims_processed_total"), 0))
    claims_skipped_low_confidence_total = max(0, _as_int(runtime_out.get("claims_skipped_low_confidence_total"), 0))
    triage_total_claims_total = max(0, _as_int(runtime_out.get("triage_total_claims_total"), 0))
    avg_slot_confidence_samples = max(0, _as_int(runtime_out.get("avg_slot_confidence_samples"), 0))
    if vid_total > 0:
        runtime_out["violate_rate"] = float(violate_total) / float(vid_total)
        runtime_out["unknown_rate"] = float(unknown_total) / float(vid_total)
    else:
        runtime_out["violate_rate"] = 0.0
        runtime_out["unknown_rate"] = 0.0
    runtime_out["slot_detection_rate"] = (
        float(segments_with_claims_total) / float(segment_count_total) if segment_count_total > 0 else 0.0
    )
    runtime_out["claims_skipped_low_confidence_rate"] = (
        float(claims_skipped_low_confidence_total) / float(claims_processed_total)
        if claims_processed_total > 0
        else 0.0
    )
    runtime_out["triage_selection_rate"] = (
        float(_as_int(runtime_out.get("triage_selected_claims_total"), 0)) / float(triage_total_claims_total)
        if triage_total_claims_total > 0
        else 0.0
    )
    runtime_out["avg_slot_confidence"] = (
        _as_float(runtime_out.get("avg_slot_confidence_sum"), 0.0) / float(avg_slot_confidence_samples)
        if avg_slot_confidence_samples > 0
        else 0.0
    )
    attempted_rounds_total = max(0, _as_int(runtime_out.get("verification_loop_attempted_rounds_total"), 0))
    round_elapsed_sum = _as_float(runtime_out.get("verification_loop_round_elapsed_ms_sum"), 0.0)
    candidate_growth_total = max(0, _as_int(runtime_out.get("verification_loop_candidate_growth_total"), 0))
    jobs_sampled = max(1, _as_int(runtime_out.get("jobs_sampled"), 0))
    slot_diagnostics_present_jobs = max(0, _as_int(runtime_out.get("slot_diagnostics_present_jobs"), 0))
    slot_diagnostics_partial_jobs = max(0, _as_int(runtime_out.get("slot_diagnostics_partial_jobs"), 0))
    slot_diagnostics_missing_jobs = max(0, _as_int(runtime_out.get("slot_diagnostics_missing_jobs"), 0))
    slot_diagnostics_observed_jobs = (
        slot_diagnostics_present_jobs + slot_diagnostics_partial_jobs + slot_diagnostics_missing_jobs
    )
    if slot_diagnostics_observed_jobs <= 0:
        runtime_out["slot_diagnostics_schema_status"] = "NOT_OBSERVED"
    elif slot_diagnostics_partial_jobs > 0:
        runtime_out["slot_diagnostics_schema_status"] = "PARTIAL"
    elif slot_diagnostics_present_jobs > 0 and slot_diagnostics_missing_jobs > 0:
        runtime_out["slot_diagnostics_schema_status"] = "MIXED"
    elif slot_diagnostics_present_jobs > 0:
        runtime_out["slot_diagnostics_schema_status"] = "COMPLETE"
    else:
        runtime_out["slot_diagnostics_schema_status"] = "MISSING"
    runtime_out["slot_diagnostics_complete_job_rate"] = (
        float(slot_diagnostics_present_jobs) / float(slot_diagnostics_observed_jobs)
        if slot_diagnostics_observed_jobs > 0
        else 0.0
    )
    jobs_with_claims_total = max(0, _as_int(runtime_out.get("jobs_with_claims_total"), 0))
    runtime_out["slot_diagnostics_missing_with_claims_rate"] = (
        float(_as_int(runtime_out.get("slot_diagnostics_missing_with_claims_jobs"), 0)) / float(jobs_with_claims_total)
        if jobs_with_claims_total > 0
        else 0.0
    )
    snippet_slot_cache_total = max(
        0,
        _as_int(runtime_out.get("snippet_slot_cache_hit_count"), 0)
        + _as_int(runtime_out.get("snippet_slot_cache_miss_count"), 0),
    )
    runtime_out["snippet_slot_cache_hit_rate"] = (
        float(_as_int(runtime_out.get("snippet_slot_cache_hit_count"), 0)) / float(snippet_slot_cache_total)
        if snippet_slot_cache_total > 0
        else 0.0
    )
    runtime_out["anchor_rescue_ok_rate"] = (
        float(_as_int(runtime_out.get("anchor_rescue_ok_count"), 0))
        / float(max(1, _as_int(runtime_out.get("anchor_rescue_attempt_count"), 0)))
        if _as_int(runtime_out.get("anchor_rescue_attempt_count"), 0) > 0
        else 0.0
    )
    if attempted_rounds_total > 0:
        runtime_out["verification_loop_round_elapsed_ms_avg"] = round_elapsed_sum / float(attempted_rounds_total)
        runtime_out["verification_loop_candidate_growth_avg"] = (
            float(candidate_growth_total) / float(attempted_rounds_total)
        )
    else:
        runtime_out["verification_loop_round_elapsed_ms_avg"] = 0.0
        runtime_out["verification_loop_candidate_growth_avg"] = 0.0
    runtime_out["verification_loop_round_elapsed_ms_p95"] = percentile(
        [float(item) for item in (runtime_out.get("verification_loop_round_elapsed_ms_samples") or [])],
        95,
    )
    runtime_out["verification_loop_candidate_growth_p95"] = percentile(
        [float(item) for item in (runtime_out.get("verification_loop_candidate_growth_samples") or [])],
        95,
    )
    runtime_out["layer3_model_enabled_ratio"] = (
        float(_as_int(runtime_out.get("layer3_model_enabled_jobs"), 0)) / float(jobs_sampled)
    )
    runtime_out["layer3_local_nli_enabled_ratio"] = (
        float(_as_int(runtime_out.get("layer3_local_nli_enabled_jobs"), 0)) / float(jobs_sampled)
    )
    runtime_out["layer3_remote_api_enabled_ratio"] = (
        float(_as_int(runtime_out.get("layer3_remote_api_enabled_jobs"), 0)) / float(jobs_sampled)
    )
    runtime_out["layer3_local_reranker_enabled_ratio"] = (
        float(_as_int(runtime_out.get("layer3_local_reranker_enabled_jobs"), 0)) / float(jobs_sampled)
    )
    runtime_out["layer3_nli_capable_ratio"] = (
        float(_as_int(runtime_out.get("layer3_nli_capable_jobs"), 0)) / float(jobs_sampled)
    )
    runtime_out["layer3_reranker_capable_ratio"] = (
        float(_as_int(runtime_out.get("layer3_reranker_capable_jobs"), 0)) / float(jobs_sampled)
    )
    runtime_out["layer3_effective_capable_ratio"] = (
        float(_as_int(runtime_out.get("layer3_effective_capable_jobs"), 0)) / float(jobs_sampled)
    )
    runtime_out["layer3_promotion_enabled_ratio"] = (
        float(_as_int(runtime_out.get("layer3_promotion_enabled_jobs"), 0)) / float(jobs_sampled)
    )
    return runtime_out


def _new_graph_runtime(*, index_runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "applied_count": 0,
        "sampled_jobs": 0,
        "index_runtime": dict(index_runtime or {}),
        "applied_queries_sample": [],
        "skipped_queries_sample": [],
        "skipped_reason_counts": {},
        "seed_signal_type_counts": {},
    }


def _append_graph_query_sample(
    target: list[dict[str, Any]],
    *,
    candidate: dict[str, Any],
    graph_payload: dict[str, Any],
    applied: bool,
    limit: int = _GRAPH_QUERY_SAMPLE_LIMIT,
) -> None:
    if len(target) >= max(1, int(limit)):
        return
    sample = {
        "query": _compact_query_text(str(candidate.get("query") or ""), limit=120),
        "signal_types": [
            str(item)
            for item in (candidate.get("signal_types") or [])
            if isinstance(item, str) and item
        ],
        "source_id": str(candidate.get("source_id") or ""),
        "episode_no": _as_int(candidate.get("episode_no"), 0),
        "applied": bool(applied),
        "reason": str(graph_payload.get("reason") or ""),
        "seed_doc_count": _as_int(graph_payload.get("seed_doc_count"), 0),
        "expanded_doc_count": _as_int(graph_payload.get("expanded_doc_count"), 0),
        "boosted_result_count": _as_int(
            graph_payload.get("boosted_result_count", graph_payload.get("boosted_results")),
            0,
        ),
    }
    target.append(sample)


def _accumulate_graph_runtime(
    runtime: dict[str, Any],
    *,
    candidate: dict[str, Any],
    graph_payload: dict[str, Any],
) -> None:
    runtime["sampled_jobs"] = _as_int(runtime.get("sampled_jobs"), 0) + 1
    signal_type_counts = runtime.get("seed_signal_type_counts")
    if not isinstance(signal_type_counts, dict):
        signal_type_counts = {}
        runtime["seed_signal_type_counts"] = signal_type_counts
    for signal_type in candidate.get("signal_types") or []:
        if not isinstance(signal_type, str) or not signal_type:
            continue
        signal_type_counts[signal_type] = int(signal_type_counts.get(signal_type, 0)) + 1
    applied = bool(graph_payload.get("applied"))
    if applied:
        runtime["applied_count"] = _as_int(runtime.get("applied_count"), 0) + 1
        applied_samples = runtime.get("applied_queries_sample")
        if not isinstance(applied_samples, list):
            applied_samples = []
            runtime["applied_queries_sample"] = applied_samples
        _append_graph_query_sample(applied_samples, candidate=candidate, graph_payload=graph_payload, applied=True)
        return
    reason = str(graph_payload.get("reason") or "unknown")
    reason_counts = runtime.get("skipped_reason_counts")
    if not isinstance(reason_counts, dict):
        reason_counts = {}
        runtime["skipped_reason_counts"] = reason_counts
    reason_counts[reason] = int(reason_counts.get(reason, 0)) + 1
    skipped_samples = runtime.get("skipped_queries_sample")
    if not isinstance(skipped_samples, list):
        skipped_samples = []
        runtime["skipped_queries_sample"] = skipped_samples
    _append_graph_query_sample(skipped_samples, candidate=candidate, graph_payload=graph_payload, applied=False)


def run_pipeline_once(
    *,
    base_url: str,
    dataset_path: Path,
    project_name: str,
    limit_docs: int,
    consistency_samples: int,
    ingest_parallelism: int,
    consistency_parallelism: int,
    consistency_level: str,
    consistency_graph_mode: str,
    graph_enabled: bool,
    graph_max_hops: int,
    graph_rerank_weight: float,
    consistency_evidence_link_policy: str,
    consistency_evidence_link_cap: int,
    seed: int,
    run_label: str,
    index_grouping_enabled: bool = False,
    include_local_profile_only: bool = False,
    only_local_profile_only: bool = False,
    consistency_overrides: dict[str, Any] | None = None,
) -> BenchRunResult:
    client = ApiClient(base_url)
    frontdoor_probe = _call_with_stage("frontdoor_probe", _probe_frontdoor, client)
    loaded_records = _call_with_stage("load_dataset", load_dataset, dataset_path, limit=limit_docs)
    records, shadow_filter_summary = _filter_records_for_shadow_track(
        loaded_records,
        only_local_profile_only=only_local_profile_only,
    )
    if not records:
        raise RuntimeError(
            f"dataset is empty after corroboration filter ({shadow_filter_summary.get('filter_mode')}): {dataset_path}"
        )

    dataset_hash = sha256_obj(records)
    dataset_profile = _summarize_dataset_records(records)
    dataset_profile["consistency_corroboration_filter"] = dict(shadow_filter_summary)
    dataset_manifest_entry = _load_dataset_manifest_entry(dataset_path)
    if dataset_manifest_entry:
        dataset_profile["dataset_manifest_entry"] = dataset_manifest_entry
    started = now_ts()
    bench_start = time.perf_counter()

    unique_project_name = f"{project_name}-{run_label}-{int(time.time() * 1000)}"
    project = _call_with_stage(
        "project_create",
        client.post,
        "/projects",
        {"name": unique_project_name, "settings": {"mode": "bench", "seed": seed}},
    )
    project_id = str((project.get("project") or {}).get("project_id"))
    if not project_id:
        raise RuntimeError("project creation failed")

    create_doc_ms: list[float] = []
    doc_ids: list[str] = []
    for idx, item in enumerate(records, start=1):
        title = str(item.get("header") or f"Episode {idx}")
        content = str(item.get("content") or "")
        t0 = time.perf_counter()
        created = _call_with_stage(
            "document_create",
            client.post,
            f"/projects/{parse.quote(project_id)}/documents",
            {"title": title, "type": "EPISODE", "content": content, "metadata": {"episode_no": item.get("episode_no")}},
        )
        create_doc_ms.append((time.perf_counter() - t0) * 1000.0)
        doc_id = str((created.get("document") or {}).get("doc_id"))
        if not doc_id:
            raise RuntimeError("document creation failed")
        doc_ids.append(doc_id)

    ingest_tasks = [
        {
            "base_url": base_url,
            "project_id": project_id,
            "job_type": "INGEST",
            "inputs": {"doc_id": doc_id},
            "timeout_sec": 3600.0,
        }
        for doc_id in doc_ids
    ]
    ingest_runs = _call_with_stage("ingest_jobs", run_parallel_jobs, ingest_tasks, parallelism=ingest_parallelism)

    index_fts_params = _build_index_fts_params(
        graph_enabled=bool(graph_enabled),
        index_grouping_enabled=bool(index_grouping_enabled),
    )
    index_fts = _call_with_stage(
        "index_fts",
        submit_and_wait,
        client,
        project_id=project_id,
        job_type="INDEX_FTS",
        inputs={"scope": "global"},
        params=index_fts_params,
        timeout_sec=7200.0,
    )
    index_vec = _call_with_stage(
        "index_vec",
        submit_and_wait,
        client,
        project_id=project_id,
        job_type="INDEX_VEC",
        inputs={"scope": "global", "shard_policy": {"mode": "doc"}},
        timeout_sec=7200.0,
    )

    index_fts_graph_runtime = {}
    if index_fts.status == "SUCCEEDED":
        index_fts_graph_runtime = _extract_index_fts_graph_runtime(get_job_events(client, index_fts.job_id))

    sample_targets, consistency_target_selection = _pick_consistency_targets(
        doc_ids,
        records=records,
        sample_count=consistency_samples,
        seed=seed,
        include_local_profile_only=(include_local_profile_only or only_local_profile_only),
    )
    consistency_params, resolved_consistency_level = _build_consistency_params(
        consistency_level=consistency_level,
        evidence_link_policy=consistency_evidence_link_policy,
        evidence_link_cap=consistency_evidence_link_cap,
        graph_mode_override=str((consistency_overrides or {}).get("graph_mode") or "") or None,
        metadata_grouping_override=(consistency_overrides or {}).get("metadata_grouping_enabled"),
        layer3_verdict_promotion_override=(consistency_overrides or {}).get("layer3_verdict_promotion"),
        verifier_mode_override=str((consistency_overrides or {}).get("verifier_mode") or "") or None,
        triage_mode_override=str((consistency_overrides or {}).get("triage_mode") or "") or None,
        triage_anomaly_threshold_override=(consistency_overrides or {}).get("triage_anomaly_threshold"),
        triage_max_segments_override=(consistency_overrides or {}).get("triage_max_segments_per_run"),
        verification_loop_enabled_override=(consistency_overrides or {}).get("verification_loop_enabled"),
        verification_loop_max_rounds_override=(consistency_overrides or {}).get("verification_loop_max_rounds"),
        verification_loop_timeout_ms_override=(consistency_overrides or {}).get("verification_loop_timeout_ms"),
    )
    consistency_tasks = [
        {
            "base_url": base_url,
            "project_id": project_id,
            "job_type": "CONSISTENCY",
            "inputs": {
                "input_doc_id": str(target.get("doc_id") or ""),
                "input_snapshot_id": "latest",
                "range": dict(target.get("range") or {"start": 0, "end": 5000}),
                "preflight": {
                    "ensure_ingest": True,
                    "ensure_index_fts": True,
                    "schema_scope": "explicit_only",
                },
                "schema_scope": "explicit_only",
            },
            "params": consistency_params,
            "timeout_sec": 7200.0,
        }
        for target in sample_targets
    ]
    consistency_runs = _call_with_stage(
        "consistency_jobs",
        run_parallel_jobs,
        consistency_tasks,
        parallelism=consistency_parallelism,
    )
    consistency_graph_mode_observed = str((consistency_params.get("consistency") or {}).get("graph_mode") or "off")
    consistency_runtime = _new_consistency_runtime(graph_mode=consistency_graph_mode_observed)
    for run in consistency_runs:
        if run.status != "SUCCEEDED":
            continue
        for _seq, event in get_job_events(client, run.job_id):
            message = str((event.get("message") or "")).strip().lower()
            if message != "consistency complete":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            _accumulate_consistency_runtime(consistency_runtime, payload)
            consistency_graph_mode_observed = str(consistency_runtime.get("graph_mode") or consistency_graph_mode_observed)
            break
    consistency_runtime = _finalize_consistency_runtime(consistency_runtime)

    retrieval_ms: list[float] = []
    retrieval_vec_ms: list[float] = []
    retrieve_vec_failures = 0
    graph_runtime = _new_graph_runtime(index_runtime=index_fts_graph_runtime)
    for query_candidate in _pick_retrieval_query_candidates(
        records,
        limit=min(30, len(records)),
        seed=seed,
        graph_enabled=bool(graph_enabled),
        index_runtime=index_fts_graph_runtime,
    ):
        query = str(query_candidate.get("query") or "")
        if not query:
            continue
        t0 = time.perf_counter()
        _call_with_stage(
            "retrieval_fts_query",
            client.post,
            "/query/retrieval",
            {"project_id": project_id, "query": query, "k": 10, "filters": {}},
        )
        retrieval_ms.append((time.perf_counter() - t0) * 1000.0)

        retrieve_vec = _call_with_stage(
            "retrieve_vec_job",
            submit_and_wait,
            client,
            project_id=project_id,
            job_type="RETRIEVE_VEC",
            inputs={"query": query, "filters": {}, "k": 10},
            params={
                "graph": {
                    "enabled": bool(graph_enabled),
                    "max_hops": max(1, min(2, int(graph_max_hops))),
                    "rerank_weight": max(0.0, min(0.5, float(graph_rerank_weight))),
                }
            },
            timeout_sec=7200.0,
        )
        retrieval_vec_ms.append(retrieve_vec.elapsed_ms)
        if retrieve_vec.status != "SUCCEEDED":
            retrieve_vec_failures += 1
            continue
        for _seq, event in get_job_events(client, retrieve_vec.job_id):
            message = str((event.get("message") or "")).strip().lower()
            if message != "retrieve_vec complete":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            graph = payload.get("graph")
            if not isinstance(graph, dict):
                continue
            _accumulate_graph_runtime(graph_runtime, candidate=query_candidate, graph_payload=graph)
            break

    finished = now_ts()
    total_elapsed_ms = (time.perf_counter() - bench_start) * 1000.0
    timings_ms = {
        "create_doc_p95": percentile(create_doc_ms, 95),
        "ingest_p95": percentile([r.elapsed_ms for r in ingest_runs], 95),
        "index_fts": index_fts.elapsed_ms,
        "index_vec": index_vec.elapsed_ms,
        "consistency_p95": percentile([r.elapsed_ms for r in consistency_runs], 95),
        "retrieval_fts_p95": percentile(retrieval_ms, 95),
        "retrieval_fts_p99": percentile(retrieval_ms, 99),
        "retrieval_vec_p95": percentile(retrieval_vec_ms, 95),
        "retrieval_vec_p99": percentile(retrieval_vec_ms, 99),
        "total": total_elapsed_ms,
    }
    status = {
        "index_fts": index_fts.status,
        "index_vec": index_vec.status,
        "ingest_failures": len([r for r in ingest_runs if r.status != "SUCCEEDED"]),
        "consistency_failures": len([r for r in consistency_runs if r.status != "SUCCEEDED"]),
        "retrieve_vec_failures": retrieve_vec_failures,
    }

    semantic = {
        "doc_count": len(doc_ids),
        "status": status,
        "graph": {
            "enabled": bool(graph_enabled),
            **graph_runtime,
        },
        "consistency_runtime": {
            "graph_mode": consistency_graph_mode_observed,
            **consistency_runtime,
        },
        "consistency_level": resolved_consistency_level,
        "consistency_target_selection": consistency_target_selection,
        "consistency_overrides": dict(consistency_overrides or {}),
        "dataset_profile": dataset_profile,
        "frontdoor_probe": frontdoor_probe,
        "guards": {
            "index_jobs_succeeded": status["index_fts"] == "SUCCEEDED" and status["index_vec"] == "SUCCEEDED",
            "ingest_failures_zero": status["ingest_failures"] == 0,
            "consistency_failures_zero": status["consistency_failures"] == 0,
            "retrieve_vec_failures_zero": status["retrieve_vec_failures"] == 0,
        },
    }
    semantic_hash = sha256_obj(normalize_semantic(semantic))
    metrics_hash = compute_metrics_hash(timings_ms)

    return BenchRunResult(
        started_at=started,
        finished_at=finished,
        base_url=base_url,
        dataset_path=str(dataset_path),
        dataset_hash=dataset_hash,
        project_id=project_id,
        doc_count=len(doc_ids),
        rss_mb_process=round(get_rss_mb(), 2),
        timings_ms=timings_ms,
        status=status,
        semantic=semantic,
        semantic_hash=semantic_hash,
        metrics_hash=metrics_hash,
    )


def _write_repro_diff(path: Path, runs: list[BenchRunResult]) -> None:
    payload = {
        "created_at": now_ts(),
        "runs": [
            {
                "dataset_path": run.dataset_path,
                "project_id": run.project_id,
                "semantic": run.semantic,
                "semantic_hash": run.semantic_hash,
            }
            for run in runs
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_dict(run: BenchRunResult) -> dict[str, Any]:
    return {
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "base_url": run.base_url,
        "dataset_path": run.dataset_path,
        "dataset_hash": run.dataset_hash,
        "project_id": run.project_id,
        "doc_count": run.doc_count,
        "rss_mb_process": run.rss_mb_process,
        "timings_ms": run.timings_ms,
        "status": run.status,
        "semantic": run.semantic,
        "semantic_hash": run.semantic_hash,
        "metrics_hash": run.metrics_hash,
    }


def _normalize_artifact_cohort(value: Any) -> str:
    token = str(value or "").strip()
    return token


def _top_level_output_fields(run: BenchRunResult) -> dict[str, Any]:
    semantic = dict(run.semantic or {})
    graph = semantic.get("graph") or {}
    consistency_runtime = semantic.get("consistency_runtime") or {}
    guards = semantic.get("guards") or {}
    return {
        "semantic": semantic,
        "guards": dict(guards) if isinstance(guards, dict) else {},
        "frontdoor_probe": dict(semantic.get("frontdoor_probe") or {}),
        "graph_index_runtime": dict((graph.get("index_runtime") or {})) if isinstance(graph, dict) else {},
        "graph_runtime": {
            "applied_count": int((graph.get("applied_count") or 0)) if isinstance(graph, dict) else 0,
            "sampled_jobs": int((graph.get("sampled_jobs") or 0)) if isinstance(graph, dict) else 0,
            "applied_queries_sample": list((graph.get("applied_queries_sample") or [])) if isinstance(graph, dict) else [],
            "skipped_queries_sample": list((graph.get("skipped_queries_sample") or [])) if isinstance(graph, dict) else [],
            "skipped_reason_counts": dict((graph.get("skipped_reason_counts") or {})) if isinstance(graph, dict) else {},
            "seed_signal_type_counts": dict((graph.get("seed_signal_type_counts") or {})) if isinstance(graph, dict) else {},
        },
        "consistency_runtime": dict(consistency_runtime) if isinstance(consistency_runtime, dict) else {},
    }


def _build_consistency_override_summary(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.consistency_graph_mode in {"off", "manual", "auto"}:
        overrides["graph_mode"] = str(args.consistency_graph_mode)
    metadata_grouping_override = _choice_to_bool(args.consistency_metadata_grouping)
    if metadata_grouping_override is not None:
        overrides["metadata_grouping_enabled"] = metadata_grouping_override
    layer3_promotion_override = _choice_to_bool(args.consistency_layer3_promotion)
    if layer3_promotion_override is not None:
        overrides["layer3_verdict_promotion"] = layer3_promotion_override
    if args.consistency_verifier_mode:
        overrides["verifier_mode"] = str(args.consistency_verifier_mode)
    if args.consistency_triage_mode:
        overrides["triage_mode"] = str(args.consistency_triage_mode)
    if args.consistency_triage_anomaly_threshold is not None:
        overrides["triage_anomaly_threshold"] = float(args.consistency_triage_anomaly_threshold)
    if args.consistency_triage_max_segments is not None:
        overrides["triage_max_segments_per_run"] = int(args.consistency_triage_max_segments)
    verification_loop_override = _choice_to_bool(args.consistency_verification_loop)
    if verification_loop_override is not None:
        overrides["verification_loop_enabled"] = verification_loop_override
    if args.consistency_verification_loop_max_rounds is not None:
        overrides["verification_loop_max_rounds"] = int(args.consistency_verification_loop_max_rounds)
    if args.consistency_verification_loop_timeout_ms is not None:
        overrides["verification_loop_timeout_ms"] = int(args.consistency_verification_loop_timeout_ms)
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(description="Run API-based E2E benchmark over novel datasets.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8085")
    parser.add_argument("--dataset", default="verify/datasets/DS-GROWTH-200.jsonl")
    parser.add_argument("--project-name", default="bench-project")
    parser.add_argument("--bench-label", default="")
    parser.add_argument("--limit-docs", type=int, default=200)
    parser.add_argument("--consistency-samples", type=int, default=100)
    parser.add_argument("--include-local-profile-only", action="store_true")
    parser.add_argument("--only-local-profile-only", action="store_true")
    parser.add_argument("--output-dir", default="verify/benchmarks")
    parser.add_argument("--ingest-parallelism", type=int, default=1)
    parser.add_argument("--consistency-parallelism", type=int, default=1)
    parser.add_argument("--consistency-level", choices=("quick", "deep", "strict"), default="quick")
    parser.add_argument("--consistency-graph-mode", choices=("off", "manual", "auto"), default="off")
    parser.add_argument("--profile", choices=("throughput", "repro", "dual"), default="dual")
    parser.add_argument("--seed", type=int, default=20260207)
    parser.add_argument("--repro-runs", type=int, default=3)
    parser.add_argument("--repro-dataset", default="verify/datasets/DS-GROWTH-50.jsonl")
    parser.add_argument("--repro-limit-docs", type=int, default=50)
    parser.add_argument("--graph-enabled", action="store_true")
    parser.add_argument("--index-grouping-enabled", action="store_true")
    parser.add_argument("--graph-max-hops", type=int, default=1)
    parser.add_argument("--graph-rerank-weight", type=float, default=0.25)
    parser.add_argument("--consistency-metadata-grouping", choices=("on", "off"), default=None)
    parser.add_argument("--consistency-layer3-promotion", choices=("on", "off"), default=None)
    parser.add_argument("--consistency-verifier-mode", choices=("off", "conservative_nli"), default=None)
    parser.add_argument("--consistency-triage-mode", choices=("off", "embedding_anomaly"), default=None)
    parser.add_argument("--consistency-triage-anomaly-threshold", type=float, default=None)
    parser.add_argument("--consistency-triage-max-segments", type=int, default=None)
    parser.add_argument("--consistency-verification-loop", choices=("on", "off"), default=None)
    parser.add_argument("--consistency-verification-loop-max-rounds", type=int, default=None)
    parser.add_argument("--consistency-verification-loop-timeout-ms", type=int, default=None)
    parser.add_argument(
        "--consistency-evidence-link-policy",
        choices=("full", "cap", "contradict_only"),
        default="full",
    )
    parser.add_argument("--consistency-evidence-link-cap", type=int, default=20)
    parser.add_argument("--artifact-cohort", default="")
    parser.add_argument("--worker-procs", type=int, default=int(os.environ.get("NF_WORKER_PROCS", "1")))
    parser.add_argument("--max-heavy-jobs", type=int, default=int(os.environ.get("NF_MAX_HEAVY_JOBS", "1")))
    args = parser.parse_args()

    if args.limit_docs < 1:
        raise SystemExit("--limit-docs must be >= 1")
    if args.consistency_samples < 1:
        raise SystemExit("--consistency-samples must be >= 1")
    if args.ingest_parallelism < 1:
        raise SystemExit("--ingest-parallelism must be >= 1")
    if args.consistency_parallelism < 1:
        raise SystemExit("--consistency-parallelism must be >= 1")
    if args.consistency_level not in {"quick", "deep", "strict"}:
        raise SystemExit("--consistency-level must be quick, deep, or strict")
    if args.repro_runs < 1:
        raise SystemExit("--repro-runs must be >= 1")
    if args.graph_max_hops not in {1, 2}:
        raise SystemExit("--graph-max-hops must be 1 or 2")
    if not (0.0 <= args.graph_rerank_weight <= 0.5):
        raise SystemExit("--graph-rerank-weight must be between 0.0 and 0.5")
    if args.consistency_evidence_link_cap < 1:
        raise SystemExit("--consistency-evidence-link-cap must be >= 1")
    consistency_overrides = _build_consistency_override_summary(args)
    artifact_cohort = _normalize_artifact_cohort(args.artifact_cohort)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        throughput_run: BenchRunResult | None = None
        if args.profile in {"throughput", "dual"}:
            throughput_run = run_pipeline_once(
                base_url=args.base_url,
                dataset_path=Path(args.dataset),
                project_name=args.project_name,
                limit_docs=args.limit_docs,
                consistency_samples=args.consistency_samples,
                ingest_parallelism=args.ingest_parallelism,
                consistency_parallelism=args.consistency_parallelism,
                consistency_level=args.consistency_level,
                consistency_graph_mode=args.consistency_graph_mode,
                graph_enabled=args.graph_enabled,
                graph_max_hops=args.graph_max_hops,
                graph_rerank_weight=args.graph_rerank_weight,
                consistency_evidence_link_policy=args.consistency_evidence_link_policy,
                consistency_evidence_link_cap=args.consistency_evidence_link_cap,
                seed=args.seed,
                run_label="throughput",
                index_grouping_enabled=args.index_grouping_enabled,
                include_local_profile_only=args.include_local_profile_only,
                only_local_profile_only=args.only_local_profile_only,
                consistency_overrides=consistency_overrides,
            )

        repro_runs: list[BenchRunResult] = []
        if args.profile in {"repro", "dual"}:
            for idx in range(args.repro_runs):
                repro_runs.append(
                    run_pipeline_once(
                        base_url=args.base_url,
                        dataset_path=Path(args.repro_dataset),
                        project_name=args.project_name,
                        limit_docs=args.repro_limit_docs,
                        consistency_samples=min(args.consistency_samples, args.repro_limit_docs),
                        ingest_parallelism=args.ingest_parallelism,
                        consistency_parallelism=args.consistency_parallelism,
                        consistency_level=args.consistency_level,
                        consistency_graph_mode=args.consistency_graph_mode,
                        graph_enabled=args.graph_enabled,
                        graph_max_hops=args.graph_max_hops,
                        graph_rerank_weight=args.graph_rerank_weight,
                        consistency_evidence_link_policy=args.consistency_evidence_link_policy,
                        consistency_evidence_link_cap=args.consistency_evidence_link_cap,
                        seed=args.seed,
                        run_label=f"repro-{idx + 1}",
                        index_grouping_enabled=args.index_grouping_enabled,
                        include_local_profile_only=args.include_local_profile_only,
                        only_local_profile_only=args.only_local_profile_only,
                        consistency_overrides=consistency_overrides,
                    )
                )

        main_run = throughput_run or repro_runs[0]

        semantic_hashes = [run.semantic_hash for run in repro_runs]
        metrics_hashes = [run.metrics_hash for run in repro_runs]
        semantic_consistent = len(set(semantic_hashes)) <= 1 if repro_runs else True

        consistency_vals = [run.timings_ms.get("consistency_p95", 0.0) for run in repro_runs]
        retrieval_vals = [run.timings_ms.get("retrieval_fts_p95", 0.0) for run in repro_runs]
        retrieval_vec_vals = [run.timings_ms.get("retrieval_vec_p95", 0.0) for run in repro_runs]
        ingest_vals = [run.timings_ms.get("ingest_p95", 0.0) for run in repro_runs]
        metrics_cv = {
            "consistency_p95_cv": coefficient_of_variation(consistency_vals),
            "retrieval_fts_p95_cv": coefficient_of_variation(retrieval_vals),
            "retrieval_vec_p95_cv": coefficient_of_variation(retrieval_vec_vals),
            "ingest_p95_cv": coefficient_of_variation(ingest_vals),
        }

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        diff_path = None
        if repro_runs and not semantic_consistent:
            diff_path = out_dir / f"repro_diff_{stamp}.json"
            _write_repro_diff(diff_path, repro_runs)

        run_manifest = build_run_manifest(
            dataset_hash=main_run.dataset_hash,
            config_snapshot={
                "max_heavy_jobs": args.max_heavy_jobs,
                "worker_procs": args.worker_procs,
                "ingest_parallelism": args.ingest_parallelism,
                "consistency_parallelism": args.consistency_parallelism,
                "consistency_level": args.consistency_level,
                "consistency_graph_mode": args.consistency_graph_mode,
                "profile": args.profile,
                "graph_enabled": args.graph_enabled,
                "index_grouping_enabled": args.index_grouping_enabled,
                "graph_max_hops": args.graph_max_hops,
                "graph_rerank_weight": args.graph_rerank_weight,
                "consistency_evidence_link_policy": args.consistency_evidence_link_policy,
                "consistency_evidence_link_cap": args.consistency_evidence_link_cap,
                "consistency_overrides": consistency_overrides,
                "artifact_cohort": artifact_cohort,
            },
            extra={
                "base_url": args.base_url,
                "dataset_path": main_run.dataset_path,
                "artifact_cohort": artifact_cohort,
            },
        )

        output = {
            "started_at": main_run.started_at,
            "finished_at": main_run.finished_at,
            "base_url": main_run.base_url,
            "dataset_path": main_run.dataset_path,
            "bench_label": str(args.bench_label or ""),
            "artifact_cohort": artifact_cohort,
            "project_id": main_run.project_id,
            "doc_count": main_run.doc_count,
            "rss_mb_process": main_run.rss_mb_process,
            "timings_ms": main_run.timings_ms,
            "status": main_run.status,
            "parallel": {
                "profile": args.profile,
                "streams": max(args.ingest_parallelism, args.consistency_parallelism),
                "parallel_mode": "thread",
                "worker_procs": args.worker_procs,
                "max_heavy_jobs": args.max_heavy_jobs,
                "ingest_parallelism": args.ingest_parallelism,
                "consistency_parallelism": args.consistency_parallelism,
                "consistency_level": args.consistency_level,
                "consistency_graph_mode": args.consistency_graph_mode,
                "consistency_evidence_link_policy": args.consistency_evidence_link_policy,
                "consistency_evidence_link_cap": args.consistency_evidence_link_cap,
                "index_grouping_enabled": args.index_grouping_enabled,
                "consistency_overrides": consistency_overrides,
            },
            "graph": {
                "enabled": bool(args.graph_enabled),
                "max_hops": max(1, min(2, int(args.graph_max_hops))),
                "rerank_weight": max(0.0, min(0.5, float(args.graph_rerank_weight))),
                "applied_path": "retrieve_vec_async_only",
                "normal_path_grouping_enabled": bool(args.graph_enabled),
            },
            **_top_level_output_fields(main_run),
            "repro": {
                "seed": args.seed,
                "dataset_hash": main_run.dataset_hash,
                "semantic_hash": (semantic_hashes[0] if semantic_hashes else main_run.semantic_hash),
                "metrics_hash": (metrics_hashes[0] if metrics_hashes else main_run.metrics_hash),
                "semantic_consistent": semantic_consistent,
                "metrics_cv": metrics_cv,
                "run_manifest": run_manifest,
                "diff_artifact": str(diff_path) if diff_path is not None else None,
            },
            "runs": {
                "throughput": _as_dict(throughput_run) if throughput_run is not None else None,
                "repro": [_as_dict(run) for run in repro_runs],
            },
        }

        out_path = out_dir / f"{stamp}.json"
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_path = out_dir / f"{stamp}.md"
        summary_lines = [
            f"# Pipeline Benchmark Summary ({stamp})",
            "",
            f"- bench_label: `{str(args.bench_label or '')}`",
            f"- artifact_cohort: `{artifact_cohort}`",
            f"- profile: `{args.profile}`",
            f"- ingest_parallelism: `{args.ingest_parallelism}`",
            f"- consistency_parallelism: `{args.consistency_parallelism}`",
            f"- consistency_level: `{args.consistency_level}`",
            f"- consistency_graph_mode: `{args.consistency_graph_mode}`",
            f"- consistency_evidence_link_policy: `{args.consistency_evidence_link_policy}`",
            f"- consistency_evidence_link_cap: `{args.consistency_evidence_link_cap}`",
            f"- doc_count: `{main_run.doc_count}`",
            f"- ingest_p95_ms: `{main_run.timings_ms.get('ingest_p95', 0.0):.2f}`",
            f"- consistency_p95_ms: `{main_run.timings_ms.get('consistency_p95', 0.0):.2f}`",
            f"- retrieval_fts_p95_ms: `{main_run.timings_ms.get('retrieval_fts_p95', 0.0):.2f}`",
            f"- retrieval_vec_p95_ms: `{main_run.timings_ms.get('retrieval_vec_p95', 0.0):.2f}`",
            f"- graph_index_runtime: `{output['graph_index_runtime']}`",
            f"- graph_runtime: `{output['graph_runtime']}`",
            f"- consistency_runtime: `{output['consistency_runtime']}`",
            f"- semantic_hash: `{output['repro']['semantic_hash']}`",
            f"- metrics_hash: `{output['repro']['metrics_hash']}`",
            f"- graph: `{output['graph']}`",
            "",
            "## Repro",
            f"- semantic_consistent: `{output['repro']['semantic_consistent']}`",
            f"- metrics_cv: `{output['repro']['metrics_cv']}`",
            f"- diff_artifact: `{output['repro']['diff_artifact']}`",
        ]
        summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(out_path), "summary": str(summary_path)}, ensure_ascii=False))
        return 0
    except BenchStageError as exc:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        failure_payload = _build_failure_payload(args=args, stage_error=exc)
        failure_path = out_dir / f"failure_{stamp}.json"
        failure_md_path = out_dir / f"failure_{stamp}.md"
        failure_path.write_text(json.dumps(failure_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        failure_md_path.write_text(_render_failure_markdown(failure_payload), encoding="utf-8")
        print(json.dumps({"ok": False, "output": str(failure_path), "summary": str(failure_md_path)}, ensure_ascii=False))
        return 2
    except Exception as exc:  # noqa: BLE001
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        failure_payload = {
            "generated_at_utc": now_ts(),
            "ok": False,
            "failure_kind": "bench_unknown_failure",
            "attempt_stage": "unknown",
            "base_url": args.base_url,
            "dataset_path": str(args.dataset),
            "bench_label": str(args.bench_label or ""),
            "profile": str(args.profile),
            "consistency_level": str(args.consistency_level),
            "request_path": "",
            "error_class": type(exc).__name__,
            "error_message": str(exc),
            "transport": None,
        }
        failure_path = out_dir / f"failure_{stamp}.json"
        failure_md_path = out_dir / f"failure_{stamp}.md"
        failure_path.write_text(json.dumps(failure_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        failure_md_path.write_text(_render_failure_markdown(failure_payload), encoding="utf-8")
        print(json.dumps({"ok": False, "output": str(failure_path), "summary": str(failure_md_path)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
