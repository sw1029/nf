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

from common import (  # noqa: E402
    build_run_manifest,
    coefficient_of_variation,
    metrics_hash as compute_metrics_hash,
    normalize_semantic,
    now_ts,
    sha256_obj,
)
from http_client import (  # noqa: E402
    ApiClient as SharedApiClient,
    JobRun as SharedJobRun,
    submit_and_wait as shared_submit_and_wait,
    wait_for_job as shared_wait_for_job,
)
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


def _pick_consistency_targets(doc_ids: list[str], *, sample_count: int, seed: int) -> list[str]:
    pool = list(doc_ids)
    rng = random.Random(seed)
    rng.shuffle(pool)
    return pool[: max(1, min(sample_count, len(pool)))]


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


def _compact_query_text(text: str, *, limit: int = 120) -> str:
    compact = " ".join((text or "").split()).strip()
    return compact[:limit].strip()


def _graph_signal_span(text: str) -> tuple[int, int] | None:
    for token in _GRAPH_TIME_SIGNAL_TOKENS:
        idx = text.find(token)
        if idx >= 0:
            return idx, idx + len(token)
    match = _GRAPH_TIME_SIGNAL_RE.search(text)
    if match is not None:
        return match.start(), match.end()
    return None


def _extract_graph_signal_query(text: str, *, limit: int = 120) -> str:
    signal_span = _graph_signal_span(text)
    if signal_span is None:
        return _compact_query_text(text, limit=limit)
    compact_source = " ".join((text or "").split()).strip()
    if not compact_source:
        return ""
    start_idx = max(0, signal_span[0] - 40)
    end_idx = min(len(compact_source), start_idx + limit)
    snippet = compact_source[start_idx:end_idx].strip()
    return snippet[:limit].strip()


def _has_graph_query_signal(text: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    if _graph_signal_span(text) is not None:
        return True
    return False


def _pick_retrieval_queries(records: list[dict[str, Any]], *, limit: int, seed: int, graph_enabled: bool = False) -> list[str]:
    indices = list(range(len(records)))
    rng = random.Random(seed + 17)
    rng.shuffle(indices)
    preferred: list[str] = []
    picked: list[str] = []
    seen: set[str] = set()
    for idx in indices:
        raw_text = str(records[idx].get("content") or "")
        if not raw_text.strip():
            continue
        query_text = (
            _extract_graph_signal_query(raw_text, limit=120)
            if graph_enabled
            else _compact_query_text(raw_text, limit=120)
        )
        if not query_text or query_text in seen:
            continue
        seen.add(query_text)
        if graph_enabled and _has_graph_query_signal(raw_text):
            preferred.append(query_text)
        else:
            picked.append(query_text)
        if len(preferred) + len(picked) >= limit:
            break
    return [*preferred, *picked][:limit]


def _build_index_fts_params(*, graph_enabled: bool) -> dict[str, Any]:
    if not graph_enabled:
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
        "graph_expand_applied_count": 0,
        "graph_auto_trigger_count": 0,
        "graph_auto_skip_count": 0,
        "layer3_rerank_applied_count": 0,
        "layer3_model_fallback_count": 0,
        "layer3_model_enabled_jobs": 0,
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
        "layer3_promoted_ok_count": 0,
        "vid_count_total": 0,
        "violate_count_total": 0,
        "unknown_count_total": 0,
        "unknown_reason_counts": {},
    }


def _accumulate_consistency_runtime(runtime: dict[str, Any], payload: dict[str, Any]) -> None:
    runtime["jobs_sampled"] = _as_int(runtime.get("jobs_sampled"), 0) + 1
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
    if vid_total > 0:
        runtime_out["violate_rate"] = float(violate_total) / float(vid_total)
        runtime_out["unknown_rate"] = float(unknown_total) / float(vid_total)
    else:
        runtime_out["violate_rate"] = 0.0
        runtime_out["unknown_rate"] = 0.0
    attempted_rounds_total = max(0, _as_int(runtime_out.get("verification_loop_attempted_rounds_total"), 0))
    round_elapsed_sum = _as_float(runtime_out.get("verification_loop_round_elapsed_ms_sum"), 0.0)
    candidate_growth_total = max(0, _as_int(runtime_out.get("verification_loop_candidate_growth_total"), 0))
    jobs_sampled = max(1, _as_int(runtime_out.get("jobs_sampled"), 0))
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
) -> BenchRunResult:
    client = ApiClient(base_url)
    records = load_dataset(dataset_path, limit=limit_docs)
    if not records:
        raise RuntimeError(f"dataset is empty: {dataset_path}")

    dataset_hash = sha256_obj(records)
    started = now_ts()
    bench_start = time.perf_counter()

    unique_project_name = f"{project_name}-{run_label}-{int(time.time() * 1000)}"
    project = client.post("/projects", {"name": unique_project_name, "settings": {"mode": "bench", "seed": seed}})
    project_id = str((project.get("project") or {}).get("project_id"))
    if not project_id:
        raise RuntimeError("project creation failed")

    create_doc_ms: list[float] = []
    doc_ids: list[str] = []
    for idx, item in enumerate(records, start=1):
        title = str(item.get("header") or f"Episode {idx}")
        content = str(item.get("content") or "")
        t0 = time.perf_counter()
        created = client.post(
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
    ingest_runs = run_parallel_jobs(ingest_tasks, parallelism=ingest_parallelism)

    index_fts_params = _build_index_fts_params(graph_enabled=bool(graph_enabled))
    index_fts = submit_and_wait(
        client,
        project_id=project_id,
        job_type="INDEX_FTS",
        inputs={"scope": "global"},
        params=index_fts_params,
        timeout_sec=7200.0,
    )
    index_vec = submit_and_wait(
        client,
        project_id=project_id,
        job_type="INDEX_VEC",
        inputs={"scope": "global", "shard_policy": {"mode": "doc"}},
        timeout_sec=7200.0,
    )

    index_fts_graph_runtime = {}
    if index_fts.status == "SUCCEEDED":
        index_fts_graph_runtime = _extract_index_fts_graph_runtime(get_job_events(client, index_fts.job_id))

    sample_doc_ids = _pick_consistency_targets(doc_ids, sample_count=consistency_samples, seed=seed)
    consistency_params, resolved_consistency_level = _build_consistency_params(
        consistency_level=consistency_level,
        evidence_link_policy=consistency_evidence_link_policy,
        evidence_link_cap=consistency_evidence_link_cap,
    )
    consistency_tasks = [
        {
            "base_url": base_url,
            "project_id": project_id,
            "job_type": "CONSISTENCY",
            "inputs": {
                "input_doc_id": doc_id,
                "input_snapshot_id": "latest",
                "range": {"start": 0, "end": 5000},
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
        for doc_id in sample_doc_ids
    ]
    consistency_runs = run_parallel_jobs(consistency_tasks, parallelism=consistency_parallelism)
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
    graph_applied = 0
    graph_total = 0
    for query in _pick_retrieval_queries(
        records,
        limit=min(30, len(records)),
        seed=seed,
        graph_enabled=bool(graph_enabled),
    ):
        t0 = time.perf_counter()
        client.post("/query/retrieval", {"project_id": project_id, "query": query, "k": 10, "filters": {}})
        retrieval_ms.append((time.perf_counter() - t0) * 1000.0)

        retrieve_vec = submit_and_wait(
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
            graph_total += 1
            if bool(graph.get("applied")):
                graph_applied += 1
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
            "applied_count": graph_applied,
            "sampled_jobs": graph_total,
            "index_runtime": dict(index_fts_graph_runtime),
        },
        "consistency_runtime": {
            "graph_mode": consistency_graph_mode_observed,
            **consistency_runtime,
        },
        "consistency_level": resolved_consistency_level,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run API-based E2E benchmark over novel datasets.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8085")
    parser.add_argument("--dataset", default="verify/datasets/DS-GROWTH-200.jsonl")
    parser.add_argument("--project-name", default="bench-project")
    parser.add_argument("--bench-label", default="")
    parser.add_argument("--limit-docs", type=int, default=200)
    parser.add_argument("--consistency-samples", type=int, default=100)
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
    parser.add_argument("--graph-max-hops", type=int, default=1)
    parser.add_argument("--graph-rerank-weight", type=float, default=0.25)
    parser.add_argument(
        "--consistency-evidence-link-policy",
        choices=("full", "cap", "contradict_only"),
        default="full",
    )
    parser.add_argument("--consistency-evidence-link-cap", type=int, default=20)
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

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

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
            "graph_max_hops": args.graph_max_hops,
            "graph_rerank_weight": args.graph_rerank_weight,
            "consistency_evidence_link_policy": args.consistency_evidence_link_policy,
            "consistency_evidence_link_cap": args.consistency_evidence_link_cap,
        },
        extra={
            "base_url": args.base_url,
            "dataset_path": main_run.dataset_path,
        },
    )

    output = {
        "started_at": main_run.started_at,
        "finished_at": main_run.finished_at,
        "base_url": main_run.base_url,
        "dataset_path": main_run.dataset_path,
        "bench_label": str(args.bench_label or ""),
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
        },
        "graph": {
            "enabled": bool(args.graph_enabled),
            "max_hops": max(1, min(2, int(args.graph_max_hops))),
            "rerank_weight": max(0.0, min(0.5, float(args.graph_rerank_weight))),
            "applied_path": "retrieve_vec_async_only",
            "normal_path_grouping_enabled": bool(args.graph_enabled),
        },
        "graph_index_runtime": dict(((main_run.semantic.get("graph") or {}).get("index_runtime") or {})),
        "graph_runtime": {
            "applied_count": int((main_run.semantic.get("graph") or {}).get("applied_count", 0)),
            "sampled_jobs": int((main_run.semantic.get("graph") or {}).get("sampled_jobs", 0)),
        },
        "consistency_runtime": dict((main_run.semantic.get("consistency_runtime") or {})),
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


if __name__ == "__main__":
    raise SystemExit(main())
