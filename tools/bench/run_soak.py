from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover - optional dependency
    tqdm = None

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from common import (  # noqa: E402
    build_run_manifest,
    coefficient_of_variation,
    metrics_hash,
    normalize_semantic,
    now_ts,
    sha256_obj,
)
from http_client import ApiClient as SharedApiClient  # noqa: E402
from stats import format_duration as shared_format_duration, parse_ts as shared_parse_ts, percentile as shared_percentile  # noqa: E402

SEED_TEXT = "\uc2dc\uc791 \ud14d\uc2a4\ud2b8\n\ub098\uc774: 14\uc138\n\uc9c1\uc5c5: \ub178 \ud074\ub798\uc2a4\n\uc7ac\ub2a5: \uc7ac\ub2a5 \uc5c6\uc74c"
MARKER_TEMPLATES = [
    "\uc2dc\ub85c\ub294 50\uc138\uc774\uba70 9\uc11c\ud074 \ub9c8\ubc95\uc0ac\uc774\uc790 \ucc9c\uc7ac\ub2e4",
    "\uc2dc\ub85c\ub294 \ub2e4\uc2dc 14\uc138\ub85c \uae30\ub85d\ub418\uc5c8\uace0 \uc7ac\ub2a5\uc740 \uc5c6\ub2e4",
    "\uc2dc\ub85c\ub294 \ub3d9\ubd80 \ub9c8\ud0d1 \uc18c\uc18d\uc774\uba70 \uc2a4\uc2b9\uc740 \ub77c\uc774\uc5d8\uc774\ub2e4",
]
RETRIEVAL_QUERY = "\uc2dc\ub85c 50\uc138 9\uc11c\ud074 \ub9c8\ubc95\uc0ac"
_NETWORK_ERROR_HINTS = (
    "connection refused",
    "timed out",
    "name or service not known",
    "failed to establish a new connection",
    "winerror 10061",
    "urlopen error",
    "network_error",
)


def _is_cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event.is_set() if cancel_event is not None else False


def _sleep_with_cancel(seconds: float, *, cancel_event: threading.Event | None = None, tick_sec: float = 0.1) -> None:
    delay = max(0.0, float(seconds))
    if delay <= 0.0:
        return
    if cancel_event is None:
        time.sleep(delay)
        return
    deadline = time.perf_counter() + delay
    while time.perf_counter() < deadline:
        if _is_cancelled(cancel_event):
            return
        remaining = deadline - time.perf_counter()
        time.sleep(min(max(0.01, tick_sec), max(0.0, remaining)))


def parse_ts(text: str | None) -> datetime | None:
    return shared_parse_ts(text)


def percentile(values: list[float], p: float) -> float:
    return shared_percentile(values, p)


def format_duration(seconds: float) -> str:
    return shared_format_duration(seconds)


class ApiClient(SharedApiClient):
    pass


@dataclass
class JobRun:
    job_id: str
    status: str
    elapsed_ms: float
    job_type: str = ""


class ProgressReporter:
    def __init__(self, *, total_seconds: float, enabled: bool) -> None:
        self.total_seconds = max(1.0, total_seconds)
        self.enabled = enabled
        self._bar = None
        self._last_render = 0.0
        if not self.enabled:
            self.backend = "disabled"
        elif tqdm is not None:
            self.backend = "tqdm"
            self._bar = tqdm(total=self.total_seconds, unit="s", dynamic_ncols=True, desc="soak")
        else:
            self.backend = "text"

    def update(self, elapsed_seconds: float, **fields: Any) -> None:
        if not self.enabled:
            return
        clamped = min(self.total_seconds, max(0.0, elapsed_seconds))
        if self._bar is not None:
            delta = clamped - float(self._bar.n)
            if delta > 0:
                self._bar.update(delta)
            if fields:
                self._bar.set_postfix(**fields)
            return

        now = time.perf_counter()
        if clamped < self.total_seconds and (now - self._last_render) < 1.0:
            return
        self._last_render = now
        percent = (clamped / self.total_seconds) * 100.0
        extras = " ".join(f"{k}={v}" for k, v in sorted(fields.items()))
        print(
            "[progress] "
            f"{percent:6.2f}% "
            f"elapsed={format_duration(clamped)} "
            f"target={format_duration(self.total_seconds)}"
            + (f" {extras}" if extras else "")
        )

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()


def wait_for_job(
    client: ApiClient,
    job_id: str,
    *,
    poll_sec: float = 0.5,
    timeout_sec: float = 7200.0,
    cancel_event: threading.Event | None = None,
) -> JobRun:
    start = time.perf_counter()
    while True:
        if _is_cancelled(cancel_event):
            return JobRun(
                job_id=job_id,
                status="CANCELED_BY_INTERRUPT",
                elapsed_ms=(time.perf_counter() - start) * 1000.0,
            )
        res = client.get(f"/jobs/{parse.quote(job_id)}")
        job = res.get("job") or {}
        status = str(job.get("status") or "")
        if status in {"SUCCEEDED", "FAILED", "CANCELED"}:
            return JobRun(job_id=job_id, status=status, elapsed_ms=(time.perf_counter() - start) * 1000.0)
        if (time.perf_counter() - start) > timeout_sec:
            return JobRun(job_id=job_id, status="TIMEOUT", elapsed_ms=(time.perf_counter() - start) * 1000.0)
        _sleep_with_cancel(poll_sec, cancel_event=cancel_event)


def submit_and_wait(
    client: ApiClient,
    *,
    project_id: str,
    job_type: str,
    inputs: dict[str, Any],
    params: dict[str, Any] | None = None,
    timeout_sec: float = 7200.0,
    cancel_event: threading.Event | None = None,
) -> JobRun:
    created = client.post(
        "/jobs",
        {
            "type": job_type,
            "project_id": project_id,
            "inputs": inputs,
            "params": params or {},
        },
    )
    job_id = str((created.get("job") or {}).get("job_id"))
    if not job_id:
        raise RuntimeError(f"failed to submit job: {job_type}")
    run = wait_for_job(client, job_id, timeout_sec=timeout_sec, cancel_event=cancel_event)
    run.job_type = job_type
    return run


def get_local_rss_mb() -> float:
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


def is_policy_violation(exc: Exception) -> bool:
    text = str(exc).upper()
    return "POLICY_VIOLATION" in text


def is_network_error(exc: Exception) -> bool:
    if isinstance(exc, error.URLError):
        return True
    text = str(exc).lower()
    return any(hint in text for hint in _NETWORK_ERROR_HINTS)


def _to_positive_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value) if float(value) > 0 else 0.0
    return 0.0


def extract_job_payload_metrics(payloads: list[dict[str, Any]]) -> tuple[float, float, float, list[float]]:
    claims_processed = 0.0
    chunks_processed = 0.0
    rows_scanned = 0.0
    rss_values: list[float] = []
    for payload in payloads:
        claims_processed += _to_positive_float(payload.get("claims_processed"))
        chunks_processed += _to_positive_float(payload.get("chunks_processed"))
        rows_scanned += _to_positive_float(payload.get("rows_scanned"))
        rss = _to_positive_float(payload.get("rss_mb_peak"))
        if rss > 0:
            rss_values.append(rss)
    return claims_processed, chunks_processed, rows_scanned, rss_values


def get_job_queue_lag_ms(db_path: Path, job_id: str) -> float:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT queued_at, started_at FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return 0.0
    queued = parse_ts(row[0])
    started = parse_ts(row[1])
    if queued is None or started is None:
        return 0.0
    return max(0.0, (started - queued).total_seconds() * 1000.0)


def get_job_metric_payloads(db_path: Path, job_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM job_events WHERE job_id = ? AND payload_json IS NOT NULL",
            (job_id,),
        ).fetchall()
    payloads: list[dict[str, Any]] = []
    for row in rows:
        try:
            payloads.append(json.loads(row[0]))
        except json.JSONDecodeError:
            continue
    return payloads


def get_job_type_pressure(db_path: Path, job_type: str) -> tuple[int, int]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'RUNNING' THEN 1 ELSE 0 END) AS running_count,
                SUM(CASE WHEN status = 'QUEUED' THEN 1 ELSE 0 END) AS queued_count
            FROM jobs
            WHERE type = ? AND status IN ('RUNNING', 'QUEUED')
            """,
            (job_type,),
        ).fetchone()
    if row is None:
        return 0, 0
    running = int(row[0] or 0)
    queued = int(row[1] or 0)
    return running, queued


def wait_for_consistency_slot(
    db_path: Path,
    *,
    max_heavy_jobs: int,
    max_outstanding: int,
    max_wait_sec: float = 60.0,
    poll_sec: float = 0.25,
    cancel_event: threading.Event | None = None,
) -> float:
    start = time.perf_counter()
    while True:
        if _is_cancelled(cancel_event):
            return (time.perf_counter() - start) * 1000.0
        try:
            running, queued = get_job_type_pressure(db_path, "CONSISTENCY")
        except sqlite3.Error:
            running, queued = 0, 0
        outstanding = running + queued
        if running < max_heavy_jobs and outstanding < max_outstanding:
            return (time.perf_counter() - start) * 1000.0
        if (time.perf_counter() - start) >= max_wait_sec:
            return (time.perf_counter() - start) * 1000.0
        _sleep_with_cancel(max(0.05, poll_sec), cancel_event=cancel_event)


def create_project_and_doc(client: ApiClient, *, project_name: str, seed_text: str, profile: str) -> tuple[str, str]:
    project = client.post("/projects", {"name": project_name, "settings": {"mode": "soak", "profile": profile}})
    project_id = str((project.get("project") or {}).get("project_id"))
    if not project_id:
        raise RuntimeError("project creation failed")
    created_doc = client.post(
        f"/projects/{parse.quote(project_id)}/documents",
        {"title": "soak-doc", "type": "EPISODE", "content": seed_text},
    )
    doc_id = str((created_doc.get("document") or {}).get("doc_id"))
    if not doc_id:
        raise RuntimeError("document creation failed")
    return project_id, doc_id


def _build_marker(cycle: int, *, rng: random.Random) -> str:
    template = MARKER_TEMPLATES[(cycle + rng.randint(0, len(MARKER_TEMPLATES) - 1)) % len(MARKER_TEMPLATES)]
    return f"\n[cycle:{cycle}] {template}"


def _stream_worker(task: dict[str, Any]) -> dict[str, Any]:
    client = ApiClient(task["base_url"])
    db_path = Path(task["db_path"])
    hours = float(task["hours"])
    sleep_sec = float(task["sleep_sec"])
    stream_id = int(task["stream_id"])
    seed = int(task["seed"])
    profile = str(task["profile"])
    streams = max(1, int(task.get("streams", 1)))
    max_heavy_jobs = max(1, int(task.get("max_heavy_jobs", 1)))
    policy_retry_max = max(0, int(task.get("policy_retry_max", 5)))
    policy_retry_base_sec = max(0.01, float(task.get("policy_retry_base_sec", 0.5)))
    policy_retry_max_sec = max(policy_retry_base_sec, float(task.get("policy_retry_max_sec", 8.0)))
    adaptive_throttle = bool(task.get("adaptive_throttle", True))
    graph_enabled = bool(task.get("graph_enabled", False))
    graph_max_hops = max(1, min(2, int(task.get("graph_max_hops", 1))))
    graph_rerank_weight = max(0.0, min(0.5, float(task.get("graph_rerank_weight", 0.25))))
    consistency_evidence_link_policy = str(task.get("consistency_evidence_link_policy", "full")).strip().lower()
    if consistency_evidence_link_policy not in {"full", "cap", "contradict_only"}:
        consistency_evidence_link_policy = "full"
    try:
        consistency_evidence_link_cap = int(task.get("consistency_evidence_link_cap", 20))
    except (TypeError, ValueError):
        consistency_evidence_link_cap = 20
    consistency_evidence_link_cap = max(1, consistency_evidence_link_cap)
    cancel_event = task.get("cancel_event")
    if not isinstance(cancel_event, threading.Event):
        cancel_event = None

    rng = random.Random(seed + (stream_id * 9973))
    run_started = now_ts()
    run_start_perf = time.perf_counter()
    deadline = run_start_perf + max(0.001, hours) * 3600.0

    unique_suffix = f"{task['run_label']}-s{stream_id}-{int(time.time() * 1000)}"
    project_name = f"{task['project_name']}-{unique_suffix}"
    errors: list[str] = []

    try:
        project_id, doc_id = create_project_and_doc(client, project_name=project_name, seed_text=SEED_TEXT, profile=profile)
    except Exception as exc:  # noqa: BLE001
        status_breakdown = {
            "policy_violations": 1 if is_policy_violation(exc) else 0,
            "submit_retries": 0,
            "network_errors": 1 if is_network_error(exc) else 0,
            "unexpected_errors": 0 if is_network_error(exc) else 1,
        }
        if len(errors) < 5:
            errors.append(f"project_init: {exc}")
        return {
            "stream_id": stream_id,
            "project_id": "",
            "doc_id": "",
            "run_started": run_started,
            "run_finished": now_ts(),
            "cycles": 0,
            "jobs_total": 0,
            "jobs_failed": 0,
            "failed_ratio": 0.0,
            "orchestrator_crashes": status_breakdown["network_errors"] + status_breakdown["unexpected_errors"],
            "queue_lag_p95_ms": 0.0,
            "consistency_p95_ms": 0.0,
            "rss_mb_min": 0.0,
            "rss_mb_max": 0.0,
            "rss_drift_pct": 0.0,
            "elapsed_ms": (time.perf_counter() - run_start_perf) * 1000.0,
            "status_breakdown": status_breakdown,
            "timings_ms": {
                "queue_lag_all_p95": 0.0,
                "queue_lag_consistency_p95": 0.0,
                "consistency_p95": 0.0,
            },
            "workload": {
                "claims_processed": 0.0,
                "chunks_processed": 0.0,
                "rows_scanned": 0.0,
            },
            "graph": {
                "jobs_total": 0,
                "jobs_applied": 0,
            },
            "_queue_lags_all_ms": [],
            "_queue_lags_consistency_ms": [],
            "_consistency_elapsed_ms": [],
            "_rss_samples": [],
            "semantic": {
                "stream_id": stream_id,
                "cycles": 0,
                "no_crash": False,
                "failed_ratio_lt_1pct": True,
                "queue_lag_p95_lt_60s": True,
            },
            "semantic_hash": sha256_obj(
                normalize_semantic(
                    {
                        "stream_id": stream_id,
                        "cycles": 0,
                        "no_crash": False,
                        "failed_ratio_lt_1pct": True,
                        "queue_lag_p95_lt_60s": True,
                    }
                )
            ),
            "errors": errors,
        }

    cycles = 0
    total_jobs = 0
    failed_jobs = 0
    policy_violations = 0
    submit_retries = 0
    network_errors = 0
    unexpected_errors = 0
    queue_lags_all_ms: list[float] = []
    queue_lags_consistency_ms: list[float] = []
    consistency_elapsed_ms: list[float] = []
    rss_samples: list[float] = []
    consistency_claims_processed = 0.0
    consistency_chunks_processed = 0.0
    consistency_rows_scanned = 0.0
    throttle_wait_ms = 0.0
    graph_jobs_total = 0
    graph_jobs_applied = 0

    adaptive_delay_sec = 0.0
    if adaptive_throttle and streams > max_heavy_jobs:
        overflow_rank = max(0, stream_id - max_heavy_jobs)
        adaptive_delay_sec = min(policy_retry_max_sec, overflow_rank * policy_retry_base_sec)

    def record_error(label: str, exc: Exception) -> None:
        nonlocal policy_violations, network_errors, unexpected_errors
        if is_policy_violation(exc):
            policy_violations += 1
        elif is_network_error(exc):
            network_errors += 1
        else:
            unexpected_errors += 1
        if len(errors) < 5:
            errors.append(f"{label}: {exc}")

    def submit_with_retry(
        *,
        job_type: str,
        inputs: dict[str, Any],
        params: dict[str, Any] | None = None,
        timeout_sec: float,
    ) -> JobRun | None:
        nonlocal policy_violations, submit_retries, adaptive_delay_sec, network_errors, unexpected_errors
        attempt = 0
        while True:
            if _is_cancelled(cancel_event):
                return JobRun(job_id="", status="CANCELED_BY_INTERRUPT", elapsed_ms=0.0, job_type=job_type)
            if adaptive_throttle and adaptive_delay_sec > 0:
                _sleep_with_cancel(adaptive_delay_sec, cancel_event=cancel_event)
                if _is_cancelled(cancel_event):
                    return JobRun(job_id="", status="CANCELED_BY_INTERRUPT", elapsed_ms=0.0, job_type=job_type)
            try:
                run = submit_and_wait(
                    client,
                    project_id=project_id,
                    job_type=job_type,
                    inputs=inputs,
                    params=params,
                    timeout_sec=timeout_sec,
                    cancel_event=cancel_event,
                )
                if adaptive_throttle and adaptive_delay_sec > 0:
                    adaptive_delay_sec = max(0.0, adaptive_delay_sec * 0.7)
                return run
            except Exception as exc:  # noqa: BLE001
                if is_policy_violation(exc):
                    policy_violations += 1
                    if attempt >= policy_retry_max:
                        if len(errors) < 5:
                            errors.append(f"{job_type}: {exc}")
                        return None
                    submit_retries += 1
                    backoff = min(policy_retry_max_sec, policy_retry_base_sec * (2**attempt))
                    jitter = rng.uniform(0.0, min(0.25, backoff * 0.25))
                    _sleep_with_cancel(backoff + jitter, cancel_event=cancel_event)
                    if _is_cancelled(cancel_event):
                        return JobRun(job_id="", status="CANCELED_BY_INTERRUPT", elapsed_ms=0.0, job_type=job_type)
                    if adaptive_throttle:
                        adaptive_delay_sec = min(policy_retry_max_sec, max(adaptive_delay_sec, backoff))
                    attempt += 1
                    continue
                if is_network_error(exc):
                    network_errors += 1
                else:
                    unexpected_errors += 1
                if len(errors) < 5:
                    errors.append(f"{job_type}: {exc}")
                return None

    def run_stage(
        *,
        job_type: str,
        inputs: dict[str, Any],
        params: dict[str, Any] | None = None,
        timeout_sec: float,
    ) -> JobRun | None:
        nonlocal total_jobs, failed_jobs
        total_jobs += 1
        run = submit_with_retry(job_type=job_type, inputs=inputs, params=params, timeout_sec=timeout_sec)
        if run is None:
            failed_jobs += 1
            return None
        if run.status not in {"SUCCEEDED", "CANCELED_BY_INTERRUPT"}:
            failed_jobs += 1
        return run

    while time.perf_counter() < deadline and not _is_cancelled(cancel_event):
        cycles += 1
        marker = _build_marker(cycles, rng=rng)
        try:
            current = client.get(f"/projects/{parse.quote(project_id)}/documents/{parse.quote(doc_id)}")
            content = str((current.get("document") or {}).get("content") or "")
            client.patch(
                f"/projects/{parse.quote(project_id)}/documents/{parse.quote(doc_id)}",
                {"content": (content + marker), "title": "soak-doc"},
            )
        except Exception as exc:  # noqa: BLE001
            record_error("doc_update", exc)
            _sleep_with_cancel(max(0.0, sleep_sec), cancel_event=cancel_event)
            continue

        ingest = run_stage(job_type="INGEST", inputs={"doc_id": doc_id}, timeout_sec=600.0)
        if ingest is None or ingest.status == "CANCELED_BY_INTERRUPT":
            _sleep_with_cancel(max(0.0, sleep_sec), cancel_event=cancel_event)
            continue
        index_fts = run_stage(job_type="INDEX_FTS", inputs={"scope": doc_id}, timeout_sec=600.0)
        if index_fts is None or index_fts.status == "CANCELED_BY_INTERRUPT":
            _sleep_with_cancel(max(0.0, sleep_sec), cancel_event=cancel_event)
            continue
        if adaptive_throttle and streams > max_heavy_jobs:
            max_outstanding = max_heavy_jobs + 1
            throttle_wait_ms += wait_for_consistency_slot(
                db_path,
                max_heavy_jobs=max_heavy_jobs,
                max_outstanding=max_outstanding,
                cancel_event=cancel_event,
            )
            if _is_cancelled(cancel_event):
                break
        consistency = run_stage(
            job_type="CONSISTENCY",
            inputs={
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
            params={
                "consistency": {
                    "evidence_link_policy": consistency_evidence_link_policy,
                    "evidence_link_cap": consistency_evidence_link_cap,
                }
            },
            timeout_sec=1200.0,
        )
        if consistency is None or consistency.status == "CANCELED_BY_INTERRUPT":
            _sleep_with_cancel(max(0.0, sleep_sec), cancel_event=cancel_event)
            continue
        retrieve_vec = run_stage(
            job_type="RETRIEVE_VEC",
            inputs={
                "query": RETRIEVAL_QUERY,
                "k": 10,
                "filters": {},
            },
            params={
                "graph": {
                    "enabled": graph_enabled,
                    "max_hops": graph_max_hops,
                    "rerank_weight": graph_rerank_weight,
                }
            },
            timeout_sec=1200.0,
        )
        if retrieve_vec is None or retrieve_vec.status == "CANCELED_BY_INTERRUPT":
            _sleep_with_cancel(max(0.0, sleep_sec), cancel_event=cancel_event)
            continue

        try:
            client.post(
                "/query/retrieval",
                {
                    "project_id": project_id,
                    "query": RETRIEVAL_QUERY,
                    "k": 10,
                    "filters": {},
                },
            )
        except Exception as exc:  # noqa: BLE001
            record_error("retrieval", exc)

        runs = [ingest, index_fts, consistency, retrieve_vec]
        for run in runs:
            queue_lag_ms = get_job_queue_lag_ms(db_path, run.job_id)
            queue_lags_all_ms.append(queue_lag_ms)
            if run.job_type == "CONSISTENCY":
                queue_lags_consistency_ms.append(queue_lag_ms)
                consistency_elapsed_ms.append(run.elapsed_ms)

            payloads = get_job_metric_payloads(db_path, run.job_id)
            claims, chunks, rows, rss_values = extract_job_payload_metrics(payloads)
            if rss_values:
                rss_samples.extend(rss_values)
            else:
                fallback_rss = get_local_rss_mb()
                if fallback_rss > 0:
                    rss_samples.append(fallback_rss)
            if run.job_type == "CONSISTENCY":
                consistency_claims_processed += claims
                consistency_chunks_processed += chunks
                consistency_rows_scanned += rows
            if run.job_type == "RETRIEVE_VEC":
                graph_meta: dict[str, Any] | None = None
                for payload in reversed(payloads):
                    if not isinstance(payload, dict):
                        continue
                    maybe_graph = payload.get("graph")
                    if isinstance(maybe_graph, dict):
                        graph_meta = maybe_graph
                        break
                if graph_meta is not None:
                    graph_jobs_total += 1
                    if bool(graph_meta.get("applied")):
                        graph_jobs_applied += 1

        _sleep_with_cancel(max(0.0, sleep_sec), cancel_event=cancel_event)

    run_elapsed_ms = (time.perf_counter() - run_start_perf) * 1000.0
    failed_ratio = (failed_jobs / total_jobs) if total_jobs else 0.0
    queue_lag_all_p95 = percentile(queue_lags_all_ms, 95)
    queue_lag_consistency_p95 = percentile(queue_lags_consistency_ms, 95)
    consistency_p95 = percentile(consistency_elapsed_ms, 95)
    rss_drift_pct = 0.0
    positive_rss = [v for v in rss_samples if v > 0]
    if len(positive_rss) >= 2 and positive_rss[0] > 0:
        rss_drift_pct = ((max(positive_rss) - min(positive_rss)) / positive_rss[0]) * 100.0

    status_breakdown = {
        "policy_violations": policy_violations,
        "submit_retries": submit_retries,
        "network_errors": network_errors,
        "unexpected_errors": unexpected_errors,
    }
    orchestrator_crashes = network_errors + unexpected_errors

    semantic_payload = {
        "stream_id": stream_id,
        "cycles": cycles,
        "no_crash": orchestrator_crashes == 0,
        "failed_ratio_lt_1pct": failed_ratio < 0.01,
        "queue_lag_p95_lt_60s": queue_lag_all_p95 < 60000.0,
    }
    stream_interrupted = _is_cancelled(cancel_event)

    return {
        "stream_id": stream_id,
        "project_id": project_id,
        "doc_id": doc_id,
        "run_started": run_started,
        "run_finished": now_ts(),
        "cycles": cycles,
        "jobs_total": total_jobs,
        "jobs_failed": failed_jobs,
        "failed_ratio": failed_ratio,
        "orchestrator_crashes": orchestrator_crashes,
        "status_breakdown": status_breakdown,
        "queue_lag_p95_ms": queue_lag_all_p95,
        "consistency_p95_ms": consistency_p95,
        "timings_ms": {
            "queue_lag_all_p95": queue_lag_all_p95,
            "queue_lag_consistency_p95": queue_lag_consistency_p95,
            "consistency_p95": consistency_p95,
        },
        "workload": {
            "claims_processed": consistency_claims_processed,
            "chunks_processed": consistency_chunks_processed,
            "rows_scanned": consistency_rows_scanned,
            "throttle_wait_ms": throttle_wait_ms,
        },
        "graph": {
            "jobs_total": graph_jobs_total,
            "jobs_applied": graph_jobs_applied,
        },
        "rss_mb_min": min(positive_rss) if positive_rss else 0.0,
        "rss_mb_max": max(positive_rss) if positive_rss else 0.0,
        "rss_drift_pct": rss_drift_pct,
        "elapsed_ms": run_elapsed_ms,
        "_queue_lags_all_ms": queue_lags_all_ms,
        "_queue_lags_consistency_ms": queue_lags_consistency_ms,
        "_consistency_elapsed_ms": consistency_elapsed_ms,
        "_rss_samples": positive_rss,
        "semantic": semantic_payload,
        "semantic_hash": sha256_obj(normalize_semantic(semantic_payload)),
        "errors": errors,
        "interrupted": stream_interrupted,
        "interrupt_reason": "keyboard_interrupt" if stream_interrupted else None,
    }


def _aggregate_streams(stream_results: list[dict[str, Any]], *, hours: float) -> dict[str, Any]:
    total_jobs = sum(int(item.get("jobs_total", 0)) for item in stream_results)
    failed_jobs = sum(int(item.get("jobs_failed", 0)) for item in stream_results)
    cycles = sum(int(item.get("cycles", 0)) for item in stream_results)
    status_breakdown = {
        "policy_violations": sum(int((item.get("status_breakdown") or {}).get("policy_violations", 0)) for item in stream_results),
        "submit_retries": sum(int((item.get("status_breakdown") or {}).get("submit_retries", 0)) for item in stream_results),
        "network_errors": sum(int((item.get("status_breakdown") or {}).get("network_errors", 0)) for item in stream_results),
        "unexpected_errors": sum(int((item.get("status_breakdown") or {}).get("unexpected_errors", 0)) for item in stream_results),
    }
    crashes = status_breakdown["network_errors"] + status_breakdown["unexpected_errors"]

    queue_lags_all: list[float] = []
    queue_lags_consistency: list[float] = []
    consistency_elapsed: list[float] = []
    rss_samples: list[float] = []
    claims_processed = 0.0
    chunks_processed = 0.0
    rows_scanned = 0.0
    throttle_wait_ms = 0.0
    graph_jobs_total = 0
    graph_jobs_applied = 0
    for item in stream_results:
        queue_lags_all.extend(item.get("_queue_lags_all_ms") or [])
        queue_lags_consistency.extend(item.get("_queue_lags_consistency_ms") or [])
        consistency_elapsed.extend(item.get("_consistency_elapsed_ms") or [])
        rss_samples.extend(item.get("_rss_samples") or [])
        workload = item.get("workload") or {}
        claims_processed += _to_positive_float(workload.get("claims_processed"))
        chunks_processed += _to_positive_float(workload.get("chunks_processed"))
        rows_scanned += _to_positive_float(workload.get("rows_scanned"))
        throttle_wait_ms += _to_positive_float(workload.get("throttle_wait_ms"))
        graph_info = item.get("graph") or {}
        graph_jobs_total += int(graph_info.get("jobs_total", 0) or 0)
        graph_jobs_applied += int(graph_info.get("jobs_applied", 0) or 0)

    failed_ratio = (failed_jobs / total_jobs) if total_jobs else 0.0
    queue_lag_all_p95 = percentile(queue_lags_all, 95)
    queue_lag_consistency_p95 = percentile(queue_lags_consistency, 95)
    consistency_p95 = percentile(consistency_elapsed, 95)
    rss_drift_pct = 0.0
    positive_rss = [v for v in rss_samples if v > 0]
    if len(positive_rss) >= 2 and positive_rss[0] > 0:
        rss_drift_pct = ((max(positive_rss) - min(positive_rss)) / positive_rss[0]) * 100.0

    throughput_cycles_per_hour = cycles / max(hours, 1e-9)
    semantic_payload = {
        "streams": len(stream_results),
        "all_no_crash": all((item.get("orchestrator_crashes", 0) == 0) for item in stream_results),
        "all_failed_ratio_lt_1pct": all((float(item.get("failed_ratio", 1.0)) < 0.01) for item in stream_results),
        "all_queue_lag_p95_lt_60s": all((float(item.get("queue_lag_p95_ms", 999999.0)) < 60000.0) for item in stream_results),
    }

    metrics_payload = {
        "cycles": cycles,
        "failed_ratio": failed_ratio,
        "queue_lag_p95_ms": queue_lag_all_p95,
        "consistency_p95_ms": consistency_p95,
        "throughput_cycles_per_hour": throughput_cycles_per_hour,
    }

    return {
        "cycles": cycles,
        "jobs_total": total_jobs,
        "jobs_failed": failed_jobs,
        "failed_ratio": failed_ratio,
        "orchestrator_crashes": crashes,
        "status_breakdown": status_breakdown,
        "queue_lag_p95_ms": queue_lag_all_p95,
        "consistency_p95_ms": consistency_p95,
        "timings_ms": {
            "queue_lag_all_p95": queue_lag_all_p95,
            "queue_lag_consistency_p95": queue_lag_consistency_p95,
            "consistency_p95": consistency_p95,
        },
        "workload": {
            "claims_processed": claims_processed,
            "chunks_processed": chunks_processed,
            "rows_scanned": rows_scanned,
            "throttle_wait_ms": throttle_wait_ms,
        },
        "graph": {
            "jobs_total": graph_jobs_total,
            "jobs_applied": graph_jobs_applied,
            "applied_ratio": (graph_jobs_applied / graph_jobs_total) if graph_jobs_total > 0 else 0.0,
        },
        "rss_mb_min": min(positive_rss) if positive_rss else 0.0,
        "rss_mb_max": max(positive_rss) if positive_rss else 0.0,
        "rss_drift_pct": rss_drift_pct,
        "throughput_cycles_per_hour": throughput_cycles_per_hour,
        "semantic": semantic_payload,
        "semantic_hash": sha256_obj(normalize_semantic(semantic_payload)),
        "metrics_hash": metrics_hash(metrics_payload),
    }


def _run_parallel_once(
    *,
    base_url: str,
    db_path: str,
    hours: float,
    project_name: str,
    sleep_sec: float,
    streams: int,
    parallel_mode: str,
    seed: int,
    profile: str,
    run_label: str,
    show_progress: bool,
    policy_retry_max: int,
    policy_retry_base_sec: float,
    policy_retry_max_sec: float,
    adaptive_throttle: bool,
    max_heavy_jobs: int,
    graph_enabled: bool,
    graph_max_hops: int,
    graph_rerank_weight: float,
    consistency_evidence_link_policy: str,
    consistency_evidence_link_cap: int,
) -> dict[str, Any]:
    run_started = now_ts()
    run_start_perf = time.perf_counter()
    reporter = ProgressReporter(total_seconds=max(1.0, hours * 3600.0), enabled=show_progress)
    interrupted = False
    interrupt_reason: str | None = None
    cancel_event: threading.Event | None = None
    if parallel_mode == "thread":
        cancel_event = threading.Event()

    tasks = [
        {
            "base_url": base_url,
            "db_path": db_path,
            "hours": hours,
            "project_name": project_name,
            "sleep_sec": sleep_sec,
            "stream_id": stream_id,
            "seed": seed,
            "profile": profile,
            "run_label": run_label,
            "streams": streams,
            "max_heavy_jobs": max_heavy_jobs,
            "policy_retry_max": policy_retry_max,
            "policy_retry_base_sec": policy_retry_base_sec,
            "policy_retry_max_sec": policy_retry_max_sec,
            "adaptive_throttle": adaptive_throttle,
            "graph_enabled": graph_enabled,
            "graph_max_hops": graph_max_hops,
            "graph_rerank_weight": graph_rerank_weight,
            "consistency_evidence_link_policy": consistency_evidence_link_policy,
            "consistency_evidence_link_cap": consistency_evidence_link_cap,
            "cancel_event": cancel_event,
        }
        for stream_id in range(1, streams + 1)
    ]

    executor_cls: type[concurrent.futures.Executor]
    if parallel_mode == "process":
        executor_cls = concurrent.futures.ProcessPoolExecutor
    else:
        executor_cls = concurrent.futures.ThreadPoolExecutor

    stream_results: list[dict[str, Any]] = []
    executor = executor_cls(max_workers=streams)
    futures: list[concurrent.futures.Future] = []
    done_count = 0
    try:
        futures = [executor.submit(_stream_worker, task) for task in tasks]
        while True:
            done_count = sum(1 for fut in futures if fut.done())
            reporter.update(time.perf_counter() - run_start_perf, done=done_count, streams=streams)
            if done_count >= len(futures):
                break
            try:
                _sleep_with_cancel(0.5, cancel_event=cancel_event)
            except KeyboardInterrupt:
                interrupted = True
                interrupt_reason = "keyboard_interrupt"
                if cancel_event is not None:
                    cancel_event.set()
                break

        if interrupted:
            grace_deadline = time.perf_counter() + 5.0
            while time.perf_counter() < grace_deadline:
                done_count = sum(1 for fut in futures if fut.done())
                reporter.update(time.perf_counter() - run_start_perf, done=done_count, streams=streams)
                if done_count >= len(futures):
                    break
                _sleep_with_cancel(0.2, cancel_event=cancel_event)

        for fut in futures:
            if not fut.done():
                fut.cancel()
                continue
            try:
                stream_results.append(fut.result())
            except KeyboardInterrupt:
                interrupted = True
                interrupt_reason = "keyboard_interrupt"
                if cancel_event is not None:
                    cancel_event.set()
            except Exception:  # noqa: BLE001
                if interrupted:
                    continue
                raise
    except KeyboardInterrupt:
        interrupted = True
        interrupt_reason = "keyboard_interrupt"
        if cancel_event is not None:
            cancel_event.set()
    finally:
        try:
            if interrupted:
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True, cancel_futures=False)
        finally:
            done_count = sum(1 for fut in futures if fut.done()) if futures else 0
            reporter.update(time.perf_counter() - run_start_perf, done=done_count, streams=streams)
            reporter.close()

    aggregate = _aggregate_streams(stream_results, hours=hours)
    for item in stream_results:
        item.pop("_queue_lags_all_ms", None)
        item.pop("_queue_lags_consistency_ms", None)
        item.pop("_consistency_elapsed_ms", None)
        item.pop("_rss_samples", None)

    return {
        "run_label": run_label,
        "run_started": run_started,
        "run_finished": now_ts(),
        "elapsed_ms": (time.perf_counter() - run_start_perf) * 1000.0,
        "hours": hours,
        "aggregate": aggregate,
        "streams": stream_results,
        "progress_backend": reporter.backend,
        "semantic_hash": aggregate["semantic_hash"],
        "metrics_hash": aggregate["metrics_hash"],
        "interrupted": interrupted,
        "interrupt_reason": interrupt_reason,
        "partial": interrupted,
        "streams_expected": streams,
        "streams_completed": len(stream_results),
    }


def _write_repro_diff(path: Path, repro_runs: list[dict[str, Any]]) -> None:
    semantic_items = [
        {
            "run_label": run.get("run_label"),
            "semantic": run.get("aggregate", {}).get("semantic"),
            "semantic_hash": run.get("semantic_hash"),
        }
        for run in repro_runs
    ]
    payload = {
        "created_at": now_ts(),
        "runs": semantic_items,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Long soak test runner for edit/index/consistency/search loop.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8085")
    parser.add_argument("--db-path", default="nf_orchestrator.sqlite3")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--project-name", default="soak-project")
    parser.add_argument("--sleep-sec", type=float, default=1.0)
    parser.add_argument("--output-dir", default="verify/benchmarks")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress output.")
    parser.add_argument("--streams", type=int, default=1, help="Number of concurrent soak streams.")
    parser.add_argument("--parallel-mode", choices=("thread", "process"), default="thread")
    parser.add_argument("--profile", choices=("throughput", "repro", "dual"), default="dual")
    parser.add_argument("--seed", type=int, default=20260207)
    parser.add_argument("--repro-runs", type=int, default=3)
    parser.add_argument("--repro-hours", type=float, default=0.05)
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
    parser.add_argument("--policy-retry-max", type=int, default=5)
    parser.add_argument("--policy-retry-base-sec", type=float, default=0.5)
    parser.add_argument("--policy-retry-max-sec", type=float, default=8.0)
    parser.add_argument(
        "--adaptive-throttle",
        action="store_true",
        default=True,
        help="Enable adaptive throttling when streams exceed heavy job capacity (default: on).",
    )
    parser.add_argument(
        "--no-adaptive-throttle",
        action="store_false",
        dest="adaptive_throttle",
        help="Disable adaptive throttling.",
    )
    parser.add_argument(
        "--on-interrupt",
        choices=("write_partial", "fail"),
        default="write_partial",
        help="Behavior when interrupted by user (Ctrl+C).",
    )
    parser.add_argument(
        "--interrupt-exit-code",
        type=int,
        default=130,
        help="Exit code used when interrupted.",
    )
    args = parser.parse_args()

    if args.streams < 1:
        raise SystemExit("--streams must be >= 1")
    if args.hours <= 0:
        raise SystemExit("--hours must be > 0")
    if args.repro_runs < 1:
        raise SystemExit("--repro-runs must be >= 1")
    if args.policy_retry_max < 0:
        raise SystemExit("--policy-retry-max must be >= 0")
    if args.policy_retry_base_sec <= 0:
        raise SystemExit("--policy-retry-base-sec must be > 0")
    if args.policy_retry_max_sec < args.policy_retry_base_sec:
        raise SystemExit("--policy-retry-max-sec must be >= --policy-retry-base-sec")
    if args.graph_max_hops not in {1, 2}:
        raise SystemExit("--graph-max-hops must be 1 or 2")
    if not (0.0 <= args.graph_rerank_weight <= 0.5):
        raise SystemExit("--graph-rerank-weight must be between 0.0 and 0.5")
    if args.consistency_evidence_link_cap < 1:
        raise SystemExit("--consistency-evidence-link-cap must be >= 1")
    if args.interrupt_exit_code < 0 or args.interrupt_exit_code > 255:
        raise SystemExit("--interrupt-exit-code must be between 0 and 255")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_descriptor = {
        "seed_text": SEED_TEXT,
        "marker_templates": MARKER_TEMPLATES,
        "seed": args.seed,
        "streams": args.streams,
    }
    dataset_hash = sha256_obj(dataset_descriptor)
    config_snapshot = {
        "max_heavy_jobs": args.max_heavy_jobs,
        "worker_procs": args.worker_procs,
        "parallel_mode": args.parallel_mode,
        "streams": args.streams,
        "profile": args.profile,
        "policy_retry_max": args.policy_retry_max,
        "policy_retry_base_sec": args.policy_retry_base_sec,
        "policy_retry_max_sec": args.policy_retry_max_sec,
        "adaptive_throttle": args.adaptive_throttle,
        "graph_enabled": args.graph_enabled,
        "graph_max_hops": args.graph_max_hops,
        "graph_rerank_weight": args.graph_rerank_weight,
        "consistency_evidence_link_policy": args.consistency_evidence_link_policy,
        "consistency_evidence_link_cap": args.consistency_evidence_link_cap,
        "on_interrupt": args.on_interrupt,
        "interrupt_exit_code": args.interrupt_exit_code,
    }

    throughput_run: dict[str, Any] | None = None
    interrupted = False
    interrupt_reason: str | None = None
    if args.profile in {"throughput", "dual"}:
        throughput_run = _run_parallel_once(
            base_url=args.base_url,
            db_path=args.db_path,
            hours=args.hours,
            project_name=args.project_name,
            sleep_sec=args.sleep_sec,
            streams=args.streams,
            parallel_mode=args.parallel_mode,
            seed=args.seed,
            profile="throughput",
            run_label="throughput",
            show_progress=not args.no_progress,
            policy_retry_max=args.policy_retry_max,
            policy_retry_base_sec=args.policy_retry_base_sec,
            policy_retry_max_sec=args.policy_retry_max_sec,
            adaptive_throttle=args.adaptive_throttle,
            max_heavy_jobs=args.max_heavy_jobs,
            graph_enabled=args.graph_enabled,
            graph_max_hops=args.graph_max_hops,
            graph_rerank_weight=args.graph_rerank_weight,
            consistency_evidence_link_policy=args.consistency_evidence_link_policy,
            consistency_evidence_link_cap=args.consistency_evidence_link_cap,
        )
        if bool(throughput_run.get("interrupted")):
            interrupted = True
            interrupt_reason = str(throughput_run.get("interrupt_reason") or "keyboard_interrupt")

    repro_runs: list[dict[str, Any]] = []
    if args.profile in {"repro", "dual"} and not interrupted:
        repro_hours = args.hours if args.profile == "repro" else max(0.001, args.repro_hours)
        for idx in range(args.repro_runs):
            repro_run = _run_parallel_once(
                base_url=args.base_url,
                db_path=args.db_path,
                hours=repro_hours,
                project_name=args.project_name,
                sleep_sec=args.sleep_sec,
                streams=args.streams,
                parallel_mode=args.parallel_mode,
                seed=args.seed,
                profile="repro",
                run_label=f"repro-{idx + 1}",
                show_progress=False,
                policy_retry_max=args.policy_retry_max,
                policy_retry_base_sec=args.policy_retry_base_sec,
                policy_retry_max_sec=args.policy_retry_max_sec,
                adaptive_throttle=args.adaptive_throttle,
                max_heavy_jobs=args.max_heavy_jobs,
                graph_enabled=args.graph_enabled,
                graph_max_hops=args.graph_max_hops,
                graph_rerank_weight=args.graph_rerank_weight,
                consistency_evidence_link_policy=args.consistency_evidence_link_policy,
                consistency_evidence_link_cap=args.consistency_evidence_link_cap,
            )
            repro_runs.append(repro_run)
            if bool(repro_run.get("interrupted")):
                interrupted = True
                interrupt_reason = str(repro_run.get("interrupt_reason") or "keyboard_interrupt")
                break

    main_run = throughput_run
    if main_run is None and repro_runs:
        main_run = repro_runs[0]
    if main_run is None:
        raise SystemExit("no soak run result produced")
    aggregate = main_run["aggregate"]

    repro_semantic_hashes = [run["semantic_hash"] for run in repro_runs]
    repro_metrics_hashes = [run["metrics_hash"] for run in repro_runs]
    semantic_consistent = len(set(repro_semantic_hashes)) <= 1 if repro_runs else True

    consistency_vals = [float(run["aggregate"].get("consistency_p95_ms", 0.0)) for run in repro_runs]
    queue_vals = [float((run["aggregate"].get("timings_ms") or {}).get("queue_lag_all_p95", 0.0)) for run in repro_runs]
    throughput_vals = [float(run["aggregate"].get("throughput_cycles_per_hour", 0.0)) for run in repro_runs]
    metrics_cv = {
        "consistency_p95_cv": coefficient_of_variation(consistency_vals),
        "queue_lag_p95_cv": coefficient_of_variation(queue_vals),
        "throughput_cycles_per_hour_cv": coefficient_of_variation(throughput_vals),
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    diff_path = None
    if repro_runs and not semantic_consistent:
        diff_path = out_dir / f"repro_diff_{stamp}.json"
        _write_repro_diff(diff_path, repro_runs)

    run_manifest = build_run_manifest(
        dataset_hash=dataset_hash,
        config_snapshot=config_snapshot,
        extra={
            "base_url": args.base_url,
            "db_path": str(Path(args.db_path)),
        },
    )

    result = {
        "started_at": main_run["run_started"],
        "hours_target": args.hours,
        "cycles": aggregate["cycles"],
        "jobs_total": aggregate["jobs_total"],
        "jobs_failed": aggregate["jobs_failed"],
        "failed_ratio": aggregate["failed_ratio"],
        "orchestrator_crashes": aggregate["orchestrator_crashes"],
        "status_breakdown": aggregate["status_breakdown"],
        "queue_lag_p95_ms": aggregate["queue_lag_p95_ms"],
        "consistency_p95_ms": aggregate["consistency_p95_ms"],
        "timings_ms": aggregate["timings_ms"],
        "workload": aggregate["workload"],
        "graph_runtime": aggregate.get("graph", {}),
        "rss_mb_min": aggregate["rss_mb_min"],
        "rss_mb_max": aggregate["rss_mb_max"],
        "rss_drift_pct": aggregate["rss_drift_pct"],
        "throughput_cycles_per_hour": aggregate["throughput_cycles_per_hour"],
        "progress_backend": main_run.get("progress_backend"),
        "parallel": {
            "profile": args.profile,
            "streams": args.streams,
            "parallel_mode": args.parallel_mode,
            "worker_procs": args.worker_procs,
            "max_heavy_jobs": args.max_heavy_jobs,
            "policy_retry_max": args.policy_retry_max,
            "policy_retry_base_sec": args.policy_retry_base_sec,
            "policy_retry_max_sec": args.policy_retry_max_sec,
            "adaptive_throttle": args.adaptive_throttle,
            "consistency_evidence_link_policy": args.consistency_evidence_link_policy,
            "consistency_evidence_link_cap": args.consistency_evidence_link_cap,
        },
        "graph": {
            "enabled": bool(args.graph_enabled),
            "max_hops": int(args.graph_max_hops),
            "rerank_weight": float(args.graph_rerank_weight),
            "applied_path": "retrieve_vec_async_only",
        },
        "repro": {
            "seed": args.seed,
            "dataset_hash": dataset_hash,
            "semantic_hash": (repro_semantic_hashes[0] if repro_semantic_hashes else main_run["semantic_hash"]),
            "metrics_hash": (repro_metrics_hashes[0] if repro_metrics_hashes else main_run["metrics_hash"]),
            "semantic_consistent": semantic_consistent,
            "metrics_cv": metrics_cv,
            "run_manifest": run_manifest,
            "diff_artifact": str(diff_path) if diff_path is not None else None,
        },
        "interrupted": interrupted,
        "interrupt_reason": interrupt_reason,
        "partial": interrupted,
        "runs": {
            "throughput": throughput_run,
            "repro": repro_runs,
        },
    }

    if interrupted and args.on_interrupt == "fail":
        print(
            json.dumps(
                {
                    "ok": False,
                    "interrupted": True,
                    "interrupt_reason": interrupt_reason,
                    "policy": args.on_interrupt,
                },
                ensure_ascii=False,
            )
        )
        return args.interrupt_exit_code

    out_path = out_dir / f"soak_{stamp}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path = out_dir / f"soak_{stamp}.md"
    summary_lines = [
        f"# Soak Benchmark Summary ({stamp})",
        "",
        f"- profile: `{args.profile}`",
        f"- streams: `{args.streams}`",
        f"- parallel_mode: `{args.parallel_mode}`",
        f"- consistency_evidence_link_policy: `{args.consistency_evidence_link_policy}`",
        f"- consistency_evidence_link_cap: `{args.consistency_evidence_link_cap}`",
        f"- interrupted: `{interrupted}`",
        f"- interrupt_reason: `{interrupt_reason}`",
        f"- partial: `{result['partial']}`",
        f"- throughput_cycles_per_hour: `{aggregate['throughput_cycles_per_hour']:.4f}`",
        f"- failed_ratio: `{aggregate['failed_ratio']:.6f}`",
        f"- queue_lag_all_p95_ms: `{aggregate['timings_ms']['queue_lag_all_p95']:.2f}`",
        f"- queue_lag_consistency_p95_ms: `{aggregate['timings_ms']['queue_lag_consistency_p95']:.2f}`",
        f"- consistency_p95_ms: `{aggregate['consistency_p95_ms']:.2f}`",
        f"- status_breakdown: `{aggregate['status_breakdown']}`",
        f"- graph: `{result['graph']}`",
        f"- graph_runtime: `{result['graph_runtime']}`",
        f"- semantic_hash: `{result['repro']['semantic_hash']}`",
        f"- metrics_hash: `{result['repro']['metrics_hash']}`",
        "",
        "## Repro",
        f"- semantic_consistent: `{result['repro']['semantic_consistent']}`",
        f"- metrics_cv: `{result['repro']['metrics_cv']}`",
        f"- diff_artifact: `{result['repro']['diff_artifact']}`",
    ]
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": not interrupted,
                "output": str(out_path),
                "summary": str(summary_path),
                "interrupted": interrupted,
                "interrupt_reason": interrupt_reason,
                "partial": bool(result["partial"]),
            },
            ensure_ascii=False,
        )
    )
    if interrupted:
        return args.interrupt_exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
