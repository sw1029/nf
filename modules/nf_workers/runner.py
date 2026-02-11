from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import time
import uuid
from dataclasses import asdict, replace
from typing import Any

try:
    import resource  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_export.exporter import ExporterImpl
from modules.nf_model_gateway.gateway import select_model
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import (
    chunk_repo,
    document_repo,
    evidence_repo,
    fts_meta_repo,
    ingest_meta_repo,
    ignore_repo,
    job_repo,
    project_repo,
    schema_repo,
)
from modules.nf_retrieval.fts.fts_index import fts_search, index_chunks
from modules.nf_retrieval.vector.manifest import update_manifest, vector_search
from modules.nf_retrieval.vector.shard_store import build_shard
from modules.nf_schema.chunking import build_chunks
from modules.nf_schema.conflict import resolve_conflicts
from modules.nf_schema.extraction import extract_explicit_candidates
from modules.nf_schema.identity import build_alias_index, resolve_entity_id
from modules.nf_schema.registry import default_tag_defs
from modules.nf_schema.units import normalize_value
from modules.nf_schema.policy import enforce_fact_status_policy
from modules.nf_schema.validators import validate_fact_value
from modules.nf_shared.config import load_config
from modules.nf_shared.protocol.dtos import (
    EvidenceMatchType,
    EvidenceRole,
    FactSource,
    FactStatus,
    JobEvent,
    JobEventLevel,
    JobStatus,
    JobType,
    LintItem,
    ReliabilityBreakdown,
    SchemaFact,
    SchemaLayer,
    Span,
    SuggestMode,
    TagKind,
    TagAssignment,
    DocumentType,
    Verdict,
    VerdictEvidenceLink,
    VerdictLog,
)


class CancelledError(RuntimeError):
    pass


class WorkerContext:
    def __init__(
        self,
        *,
        job_id: str,
        project_id: str,
        payload: dict[str, Any],
        params: dict[str, Any],
        db_path=None,
        lease_seconds: int = 30,
    ) -> None:
        self.job_id = job_id
        self.project_id = project_id
        self.payload = payload
        self.params = params
        self._db_path = db_path
        self._lease_seconds = lease_seconds

    def emit(self, event: JobEvent) -> None:
        with db.connect(self._db_path) as conn:
            job_repo.add_job_event(
                conn,
                self.job_id,
                event.level,
                event.message,
                progress=event.progress,
                metrics=dict(event.metrics) if event.metrics else None,
                payload=dict(event.payload) if event.payload else None,
            )
            job_repo.extend_lease(conn, self.job_id, lease_seconds=self._lease_seconds)

    def check_cancelled(self) -> bool:
        with db.connect(self._db_path) as conn:
            return job_repo.is_cancel_requested(conn, self.job_id)


def run_worker(
    *,
    db_path=None,
    poll_interval: float = 1.0,
    lease_seconds: int = 30,
    max_jobs: int | None = None,
) -> None:
    worker_id = f"worker-{uuid.uuid4()}"
    processed = 0
    heavy_types = [JobType.INDEX_VEC, JobType.CONSISTENCY, JobType.RETRIEVE_VEC]
    settings = load_config()
    max_heavy_jobs = max(1, int(settings.max_heavy_jobs))

    while True:
        if _memory_pressure(settings.max_ram_mb):
            time.sleep(poll_interval)
            continue
        with db.connect(db_path) as conn:
            allow_heavy = job_repo.count_running_jobs(conn, heavy_types) < max_heavy_jobs
            deny = None if allow_heavy else heavy_types
            leased = job_repo.lease_next_job(
                conn,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                deny_job_types=deny,
            )

        if leased is None:
            time.sleep(poll_interval)
        else:
            job, inputs, params = leased
            ctx = WorkerContext(
                job_id=job.job_id,
                project_id=job.project_id,
                payload=inputs,
                params=params,
                db_path=db_path,
                lease_seconds=lease_seconds,
            )
            try:
                ctx.emit(
                    JobEvent(
                        event_id="",
                        job_id=job.job_id,
                        ts="",
                        level=JobEventLevel.INFO,
                        message=f"job {job.job_id} started",
                        progress=0.0,
                    )
                )
                _run_job(job.type, ctx)
                with db.connect(db_path) as conn:
                    job_repo.update_job_status(conn, job.job_id, JobStatus.SUCCEEDED)
                ctx.emit(
                    JobEvent(
                        event_id="",
                        job_id=job.job_id,
                        ts="",
                        level=JobEventLevel.INFO,
                        message=f"job {job.job_id} done",
                        progress=1.0,
                    )
                )
            except CancelledError:
                with db.connect(db_path) as conn:
                    job_repo.update_job_status(conn, job.job_id, JobStatus.CANCELED)
                ctx.emit(
                    JobEvent(
                        event_id="",
                        job_id=job.job_id,
                        ts="",
                        level=JobEventLevel.WARN,
                        message=f"job {job.job_id} canceled",
                        progress=1.0,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                with db.connect(db_path) as conn:
                    job_repo.set_job_error(conn, job.job_id, error_code="INTERNAL_ERROR", error_message=str(exc))
                    job_repo.update_job_status(conn, job.job_id, JobStatus.FAILED)
                ctx.emit(
                    JobEvent(
                        event_id="",
                        job_id=job.job_id,
                        ts="",
                        level=JobEventLevel.ERROR,
                        message=f"job {job.job_id} failed: {exc}",
                        progress=1.0,
                    )
                )
            processed += 1

        if max_jobs is not None and processed >= max_jobs:
            break


def _memory_pressure(max_ram_mb: int) -> bool:
    if max_ram_mb <= 0:
        return False
    usage_mb = _get_process_rss_mb()
    if usage_mb <= 0:
        return False
    return usage_mb > max_ram_mb


def _get_process_rss_mb() -> float:
    if resource is not None:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return float(usage) / (1024 * 1024)
        return float(usage) / 1024

    if sys.platform.startswith("win"):
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
        except Exception:  # noqa: BLE001
            return 0.0

    return 0.0


def _estimate_index_mb(text: str, chunk_count: int) -> float:
    text_mb = len(text.encode("utf-8")) / (1024 * 1024)
    return text_mb * 2.0 + chunk_count * 0.001


def _elapsed_ms(start_perf: float) -> int:
    return max(0, int((time.perf_counter() - start_perf) * 1000))


def _standard_metrics_payload(
    *,
    start_perf: float,
    claims_processed: int = 0,
    chunks_processed: int = 0,
    rows_scanned: int = 0,
    shards_loaded: int = 0,
) -> dict[str, float | int]:
    return {
        "elapsed_ms": _elapsed_ms(start_perf),
        "rss_mb_peak": round(_get_process_rss_mb(), 2),
        "claims_processed": int(claims_processed),
        "chunks_processed": int(chunks_processed),
        "rows_scanned": int(rows_scanned),
        "shards_loaded": int(shards_loaded),
    }


def _parse_consistency_preflight(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("preflight")
    preflight = raw if isinstance(raw, dict) else {}
    ensure_ingest = preflight.get("ensure_ingest")
    ensure_index_fts = preflight.get("ensure_index_fts")
    schema_scope = preflight.get("schema_scope")
    if not isinstance(ensure_ingest, bool):
        ensure_ingest = True
    if not isinstance(ensure_index_fts, bool):
        ensure_index_fts = True
    if not isinstance(schema_scope, str) or schema_scope not in {"latest_approved", "explicit_only"}:
        schema_scope = "latest_approved"
    return {
        "ensure_ingest": ensure_ingest,
        "ensure_index_fts": ensure_index_fts,
        "schema_scope": schema_scope,
    }


def _tag_assignment_signature(conn: sqlite3.Connection, snapshot_id: str) -> str:
    try:
        rows = conn.execute(
            """
            SELECT span_start, span_end, tag_path
            FROM tag_assignment
            WHERE snapshot_id = ?
            ORDER BY span_start ASC, span_end ASC, tag_path ASC
            """,
            (snapshot_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return ""
    parts: list[str] = []
    for row in rows:
        span_start = int(row["span_start"])
        span_end = int(row["span_end"])
        tag_path = str(row["tag_path"] or "")
        parts.append(f"{span_start}:{span_end}:{tag_path}")
    raw = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _tag_def_signature(tag_defs: list) -> str:
    if not tag_defs:
        return ""
    parts: list[str] = []
    for item in sorted(tag_defs, key=lambda t: t.tag_path):
        constraints = json.dumps(item.constraints, ensure_ascii=False, sort_keys=True)
        parts.append(
            f"{item.tag_path}|{item.kind.value}|{item.schema_type.value}|{constraints}"
        )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _alias_signature(aliases: list) -> str:
    if not aliases:
        return ""
    parts: list[str] = []
    for item in sorted(aliases, key=lambda a: (a.entity_id, a.alias_text)):
        parts.append(f"{item.entity_id}|{item.alias_text}|{item.created_by.value}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _ingest_meta_checksum(
    *,
    doc_id: str,
    snapshot_id: str,
    snapshot_checksum: str,
    assignment_sig: str,
    tag_defs_sig: str,
    alias_sig: str,
) -> str:
    payload = (
        f"doc_id={doc_id}|snapshot_id={snapshot_id}|snapshot_checksum={snapshot_checksum}"
        f"|assignment_sig={assignment_sig}|tag_defs_sig={tag_defs_sig}|alias_sig={alias_sig}"
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _fts_meta_checksum(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    snapshot_id: str,
    snapshot_checksum: str,
    episode_id: str | None,
    tag_sig: str | None = None,
) -> str:
    resolved_tag_sig = tag_sig if isinstance(tag_sig, str) else _tag_assignment_signature(conn, snapshot_id)
    payload = (
        f"doc_id={doc_id}|snapshot_id={snapshot_id}|snapshot_checksum={snapshot_checksum}"
        f"|episode_id={episode_id or ''}|tag_sig={resolved_tag_sig}"
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _snapshot_has_chunks(conn: sqlite3.Connection, snapshot_id: str) -> bool:
    try:
        row = conn.execute("SELECT 1 FROM chunks WHERE snapshot_id = ? LIMIT 1", (snapshot_id,)).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def _snapshot_has_fts_rows(conn: sqlite3.Connection, snapshot_id: str) -> bool:
    try:
        row = conn.execute(
            "SELECT row_count FROM fts_snapshot_meta WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    if row is None:
        return False
    try:
        return int(row["row_count"]) > 0
    except (TypeError, ValueError):
        return False


def _collect_aliases(conn: sqlite3.Connection, project_id: str) -> list:
    entities = schema_repo.list_entities(conn, project_id)
    aliases = []
    for entity in entities:
        aliases.extend(schema_repo.list_entity_aliases(conn, project_id, entity.entity_id))
    return aliases


def _ensure_tag_defs(conn: sqlite3.Connection, project_id: str) -> list:
    tag_defs = schema_repo.list_tag_defs(conn, project_id)
    if tag_defs:
        return tag_defs
    for item in default_tag_defs():
        schema_repo.create_tag_def(
            conn,
            project_id=project_id,
            tag_path=item["tag_path"],
            kind=item["kind"],
            schema_type=item["schema_type"],
            constraints=item.get("constraints") or {},
            commit=False,
        )
    return schema_repo.list_tag_defs(conn, project_id)


def _ingest_checksum_for_doc(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    snapshot_id: str,
    snapshot_checksum: str,
    tag_defs_sig: str,
    alias_sig: str,
    assignment_sig_cache: dict[str, str] | None = None,
) -> str:
    assignment_sig: str
    if assignment_sig_cache is not None and snapshot_id in assignment_sig_cache:
        assignment_sig = assignment_sig_cache[snapshot_id]
    else:
        assignment_sig = _tag_assignment_signature(conn, snapshot_id)
        if assignment_sig_cache is not None:
            assignment_sig_cache[snapshot_id] = assignment_sig
    return _ingest_meta_checksum(
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        snapshot_checksum=snapshot_checksum,
        assignment_sig=assignment_sig,
        tag_defs_sig=tag_defs_sig,
        alias_sig=alias_sig,
    )


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[^\n]+", text):
        segment = match.group(0).strip()
        if not segment:
            continue
        spans.append((match.start(), match.end(), segment))
    return spans


_RELATIVE_TIME_RE = re.compile(r"\\d+\\s*(?:일|달|개월|년)\\s*(?:후|뒤|전)")
_RELATIVE_TIME_TOKENS = (
    "다음 날",
    "그날",
    "이튿날",
    "며칠 후",
    "며칠 뒤",
    "첫날",
    "둘째 날",
    "셋째 날",
)


def _extract_time_phrases(text: str) -> list[str]:
    phrases = [match.group(0).strip() for match in _RELATIVE_TIME_RE.finditer(text)]
    for token in _RELATIVE_TIME_TOKENS:
        if token in text:
            phrases.append(token)
    seen: set[str] = set()
    ordered: list[str] = []
    for phrase in phrases:
        if phrase in seen:
            continue
        seen.add(phrase)
        ordered.append(phrase)
    return ordered


def _extract_entity_mentions(
    spans: list[tuple[int, int, str]],
    alias_index: dict[str, set[str]],
) -> list[tuple[str, int, int]]:
    mentions: list[tuple[str, int, int]] = []
    for span_start, span_end, segment in spans:
        matched: set[str] = set()
        for alias_text, entity_ids in alias_index.items():
            if not alias_text or alias_text not in segment:
                continue
            if len(entity_ids) == 1:
                matched.update(entity_ids)
        for entity_id in matched:
            mentions.append((entity_id, span_start, span_end))
    return mentions


def _extract_episode_number(doc) -> int | None:
    if getattr(doc, "type", None) is DocumentType.EPISODE:
        numbers = re.findall(r"\\d+", doc.title or "")
        if numbers:
            try:
                return int(numbers[0])
            except ValueError:
                return None
    return None


def _resolve_episode_id(conn, project_id: str, doc, *, episodes: list | None = None) -> str | None:
    episode_number = _extract_episode_number(doc)
    if episode_number is None:
        return None
    project_episodes = episodes if episodes is not None else document_repo.list_episodes(conn, project_id)
    candidates = [ep for ep in project_episodes if ep.start_n <= episode_number <= ep.end_m]
    if not candidates:
        return None
    candidates.sort(key=lambda ep: (ep.end_m - ep.start_n, ep.created_at, ep.episode_id))
    return candidates[0].episode_id


def _compute_tag_paths_by_chunk_id(chunks: list, assignments: list[TagAssignment]) -> dict[str, list[str]]:
    if not chunks or not assignments:
        return {}
    tag_spans = sorted(
        [(int(a.span_start), int(a.span_end), str(a.tag_path or "")) for a in assignments],
        key=lambda t: (t[0], t[1], t[2]),
    )
    tag_i = 0
    mapping: dict[str, list[str]] = {}
    for chunk in chunks:
        chunk_start = int(getattr(chunk, "span_start", 0))
        chunk_end = int(getattr(chunk, "span_end", 0))
        while tag_i < len(tag_spans) and tag_spans[tag_i][1] <= chunk_start:
            tag_i += 1
        overlap_scores: dict[str, int] = {}
        tag_j = tag_i
        while tag_j < len(tag_spans) and tag_spans[tag_j][0] < chunk_end:
            tag_start, tag_end, tag_path = tag_spans[tag_j]
            if chunk_start < tag_end and tag_start < chunk_end and tag_path:
                overlap = min(chunk_end, tag_end) - max(chunk_start, tag_start)
                prev = overlap_scores.get(tag_path, 0)
                if overlap > prev:
                    overlap_scores[tag_path] = overlap
            tag_j += 1
        if overlap_scores:
            mapping[chunk.chunk_id] = [
                tag_path
                for tag_path, _score in sorted(
                    overlap_scores.items(),
                    key=lambda kv: (-kv[1], -len(kv[0]), kv[0]),
                )
            ]
    return mapping


def _episode_key(doc) -> str:
    episode_number = _extract_episode_number(doc)
    if episode_number is not None:
        return f"episode:{episode_number}"
    return f"doc:{doc.doc_id}"


def _build_timeline_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for idx, (span_start, span_end, segment) in enumerate(_sentence_spans(text), start=1):
        phrases = _extract_time_phrases(segment)
        time_key = phrases[0] if phrases else segment[:40]
        events.append(
            {
                "timeline_idx": idx,
                "label": segment,
                "time_key": time_key,
                "span_start": span_start,
                "span_end": span_end,
            }
        )
    return events


def _match_timeline_idx(
    segment: str, time_key: str, timeline_events: list[dict[str, Any]]
) -> int | None:
    for event in timeline_events:
        label = event.get("label") or ""
        event_time_key = event.get("time_key") or ""
        if time_key and (time_key in label or time_key in event_time_key):
            return int(event.get("timeline_idx"))
        if label and label in segment:
            return int(event.get("timeline_idx"))
    return None


def _filter_results_by_meta(
    conn,
    project_id: str,
    results: list[dict[str, Any]],
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    entity_id = filters.get("entity_id")
    time_key = filters.get("time_key")
    timeline_idx = filters.get("timeline_idx")
    if not isinstance(entity_id, str):
        entity_id = None
    if not isinstance(time_key, str):
        time_key = None
    if not isinstance(timeline_idx, int):
        try:
            timeline_idx = int(timeline_idx)
        except (TypeError, ValueError):
            timeline_idx = None

    if not entity_id and not time_key and timeline_idx is None:
        return results

    entity_cache: dict[tuple[str, str], list[tuple[int, int]]] = {}
    time_cache: dict[tuple[str, str | None, int | None], list[tuple[int, int]]] = {}

    def span_overlaps(span_start: int, span_end: int, spans: list[tuple[int, int]]) -> bool:
        for other_start, other_end in spans:
            if span_start < other_end and other_start < span_end:
                return True
        return False

    def load_entity_spans(doc_id: str, entity_id: str) -> list[tuple[int, int]]:
        key = (doc_id, entity_id)
        if key in entity_cache:
            return entity_cache[key]
        rows = conn.execute(
            """
            SELECT span_start, span_end
            FROM entity_mention_span
            WHERE project_id = ? AND doc_id = ? AND entity_id = ? AND status != ?
            """,
            (project_id, doc_id, entity_id, FactStatus.REJECTED.value),
        ).fetchall()
        spans = [(row["span_start"], row["span_end"]) for row in rows]
        entity_cache[key] = spans
        return spans

    def load_time_spans(doc_id: str, time_key: str | None, timeline_idx: int | None) -> list[tuple[int, int]]:
        key = (doc_id, time_key, timeline_idx)
        if key in time_cache:
            return time_cache[key]
        query = """
            SELECT span_start, span_end
            FROM time_anchor
            WHERE project_id = ? AND doc_id = ? AND status != ?
        """
        params: list[Any] = [project_id, doc_id, FactStatus.REJECTED.value]
        if time_key is not None:
            query += " AND time_key = ?"
            params.append(time_key)
        if timeline_idx is not None:
            query += " AND timeline_idx = ?"
            params.append(timeline_idx)
        rows = conn.execute(query, params).fetchall()
        spans = [(row["span_start"], row["span_end"]) for row in rows]
        time_cache[key] = spans
        return spans

    filtered: list[dict[str, Any]] = []
    for result in results:
        evidence = result.get("evidence") or {}
        doc_id = evidence.get("doc_id")
        span_start = int(evidence.get("span_start", 0))
        span_end = int(evidence.get("span_end", 0))
        if not isinstance(doc_id, str):
            continue
        if entity_id:
            spans = load_entity_spans(doc_id, entity_id)
            if not span_overlaps(span_start, span_end, spans):
                continue
        if time_key or timeline_idx is not None:
            spans = load_time_spans(doc_id, time_key, timeline_idx)
            if not span_overlaps(span_start, span_end, spans):
                continue
        filtered.append(result)
    return filtered


def _run_job(job_type: JobType, ctx: WorkerContext) -> None:
    if ctx.check_cancelled():
        raise CancelledError("cancel requested")

    if job_type == JobType.INGEST:
        _handle_ingest(ctx)
    elif job_type == JobType.INDEX_FTS:
        _handle_index_fts(ctx)
    elif job_type == JobType.CONSISTENCY:
        _handle_consistency(ctx)
    elif job_type == JobType.RETRIEVE_VEC:
        _handle_retrieve_vec(ctx)
    elif job_type == JobType.SUGGEST:
        _handle_suggest(ctx)
    elif job_type == JobType.EXPORT:
        _handle_export(ctx)
    elif job_type == JobType.PROOFREAD:
        _handle_proofread(ctx)
    elif job_type == JobType.INDEX_VEC:
        _handle_index_vec(ctx)
    else:
        raise RuntimeError(f"unsupported job type: {job_type}")


def _handle_ingest(ctx: WorkerContext) -> None:
    start_perf = time.perf_counter()
    doc_id = ctx.payload.get("doc_id")
    snapshot_id = ctx.payload.get("snapshot_id")
    if not isinstance(doc_id, str):
        raise RuntimeError("doc_id missing")

    schema_ver = ""
    proposed = 0
    approved = 0
    skipped = False

    with db.connect(ctx._db_path) as conn:
        doc = document_repo.get_document(conn, doc_id)
        if doc is None:
            raise RuntimeError("document not found")
        if snapshot_id:
            snapshot = document_repo.get_snapshot(conn, snapshot_id)
        else:
            snapshot = document_repo.get_snapshot(conn, doc.head_snapshot_id)
        if snapshot is None:
            raise RuntimeError("snapshot not found")
        tag_defs = _ensure_tag_defs(conn, doc.project_id)
        tag_defs_sig = _tag_def_signature(tag_defs)
        entities = schema_repo.list_entities(conn, doc.project_id)
        aliases = []
        for entity in entities:
            aliases.extend(schema_repo.list_entity_aliases(conn, doc.project_id, entity.entity_id))
        alias_sig = _alias_signature(aliases)
        ingest_checksum = _ingest_checksum_for_doc(
            conn,
            doc_id=doc.doc_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_checksum=snapshot.checksum,
            tag_defs_sig=tag_defs_sig,
            alias_sig=alias_sig,
        )
        previous_state = ingest_meta_repo.get_state(conn, doc.doc_id)
        if previous_state == (snapshot.snapshot_id, ingest_checksum):
            latest_schema = schema_repo.get_latest_schema_version(conn, doc.project_id)
            schema_ver = latest_schema.schema_ver if latest_schema is not None else ""
            skipped = True
        else:
            tag_def_map = {tag.tag_path: tag for tag in tag_defs}
            alias_index = build_alias_index(entities, aliases)
            assignments = schema_repo.list_tag_assignments(
                conn,
                doc.project_id,
                doc_id=doc_id,
                snapshot_id=snapshot.snapshot_id,
            )
            text = docstore.read_text(snapshot.path)
            facts: list[SchemaFact] = []
            seen_tag_paths: set[str] = set()
            try:
                schema_ver = schema_repo.create_schema_version(
                    conn,
                    project_id=doc.project_id,
                    source_snapshot_id=snapshot.snapshot_id,
                    commit=False,
                ).schema_ver

                for assignment in assignments:
                    if ctx.check_cancelled():
                        raise CancelledError("cancel requested")
                    snippet = text[assignment.span_start : assignment.span_end]
                    tag_def = tag_def_map.get(assignment.tag_path)
                    if tag_def is not None:
                        value = normalize_value(tag_def.schema_type, assignment.user_value)
                        try:
                            validate_fact_value(tag_def.schema_type, value, tag_def.constraints)
                        except ValueError:
                            continue
                    else:
                        value = assignment.user_value
                    evidence = evidence_repo.new_evidence(
                        project_id=doc.project_id,
                        doc_id=doc_id,
                        snapshot_id=snapshot.snapshot_id,
                        chunk_id=None,
                        section_path="",
                        tag_path=assignment.tag_path,
                        snippet_text=snippet,
                        span_start=assignment.span_start,
                        span_end=assignment.span_end,
                        fts_score=0.0,
                        match_type=EvidenceMatchType.EXACT,
                        confirmed=assignment.created_by is FactSource.USER,
                    )
                    evidence_repo.create_evidence(conn, evidence, commit=False)
                    status = FactStatus.APPROVED if assignment.created_by is FactSource.USER else FactStatus.PROPOSED
                    fact = SchemaFact(
                        fact_id=str(uuid.uuid4()),
                        project_id=doc.project_id,
                        schema_ver=schema_ver,
                        layer=SchemaLayer.EXPLICIT,
                        entity_id=resolve_entity_id(assignment.tag_path, alias_index),
                        tag_path=assignment.tag_path,
                        value=value,
                        evidence_eid=evidence.eid,
                        confidence=0.9 if assignment.created_by is FactSource.USER else 0.6,
                        source=assignment.created_by,
                        status=status,
                    )
                    fact = enforce_fact_status_policy(fact)
                    facts.append(fact)
                    seen_tag_paths.add(fact.tag_path)

                for extracted in extract_explicit_candidates(text, tag_defs):
                    tag_path = extracted.tag_def.tag_path
                    if tag_path in seen_tag_paths:
                        continue
                    value = normalize_value(extracted.tag_def.schema_type, extracted.value)
                    try:
                        validate_fact_value(extracted.tag_def.schema_type, value, extracted.tag_def.constraints)
                    except ValueError:
                        continue
                    evidence = evidence_repo.new_evidence(
                        project_id=doc.project_id,
                        doc_id=doc_id,
                        snapshot_id=snapshot.snapshot_id,
                        chunk_id=None,
                        section_path="",
                        tag_path=tag_path,
                        snippet_text=extracted.snippet_text,
                        span_start=extracted.span_start,
                        span_end=extracted.span_end,
                        fts_score=0.0,
                        match_type=EvidenceMatchType.EXACT,
                        confirmed=False,
                    )
                    evidence_repo.create_evidence(conn, evidence, commit=False)
                    fact = SchemaFact(
                        fact_id=str(uuid.uuid4()),
                        project_id=doc.project_id,
                        schema_ver=schema_ver,
                        layer=SchemaLayer.EXPLICIT,
                        entity_id=resolve_entity_id(tag_path, alias_index),
                        tag_path=tag_path,
                        value=value,
                        evidence_eid=evidence.eid,
                        confidence=extracted.confidence,
                        source=FactSource.AUTO,
                        status=FactStatus.PROPOSED,
                    )
                    fact = enforce_fact_status_policy(fact)
                    facts.append(fact)
                    seen_tag_paths.add(fact.tag_path)

                for tag_def in tag_defs:
                    if tag_def.kind is not TagKind.IMPLICIT:
                        continue
                    if tag_def.tag_path in seen_tag_paths:
                        continue
                    evidence = evidence_repo.new_evidence(
                        project_id=doc.project_id,
                        doc_id=doc_id,
                        snapshot_id=snapshot.snapshot_id,
                        chunk_id=None,
                        section_path="",
                        tag_path=tag_def.tag_path,
                        snippet_text="",
                        span_start=0,
                        span_end=0,
                        fts_score=0.0,
                        match_type=EvidenceMatchType.FUZZY,
                        confirmed=False,
                    )
                    evidence_repo.create_evidence(conn, evidence, commit=False)
                    fact = SchemaFact(
                        fact_id=str(uuid.uuid4()),
                        project_id=doc.project_id,
                        schema_ver=schema_ver,
                        layer=SchemaLayer.IMPLICIT,
                        entity_id=resolve_entity_id(tag_def.tag_path, alias_index),
                        tag_path=tag_def.tag_path,
                        value="unknown",
                        evidence_eid=evidence.eid,
                        confidence=0.1,
                        source=FactSource.AUTO,
                        status=FactStatus.PROPOSED,
                    )
                    facts.append(fact)
                    seen_tag_paths.add(fact.tag_path)

                facts = resolve_conflicts(facts, tag_defs)
                for fact in facts:
                    schema_repo.create_schema_fact(conn, fact, commit=False)
                    if fact.status is FactStatus.PROPOSED:
                        proposed += 1
                    if fact.status is FactStatus.APPROVED:
                        approved += 1

                ingest_meta_repo.upsert(
                    conn,
                    doc_id=doc.doc_id,
                    snapshot_id=snapshot.snapshot_id,
                    checksum=ingest_checksum,
                    commit=False,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="ingest complete",
            progress=1.0,
            payload={
                "schema_ver": schema_ver,
                "proposed_fact_count": proposed,
                "approved_fact_count": approved,
                "incremental": True,
                "docs_skipped": 1 if skipped else 0,
                **_standard_metrics_payload(
                    start_perf=start_perf,
                    claims_processed=proposed + approved,
                ),
            },
        )
    )


def _handle_index_fts(ctx: WorkerContext) -> None:
    start_perf = time.perf_counter()
    scope = ctx.payload.get("scope")
    snapshot_id = ctx.payload.get("snapshot_id")
    if not isinstance(scope, str):
        raise RuntimeError("scope missing")
    if snapshot_id is not None and not isinstance(snapshot_id, str):
        raise RuntimeError("snapshot_id must be a string")
    if isinstance(snapshot_id, str) and snapshot_id and scope == "global":
        raise RuntimeError("snapshot_id는 scope=global과 함께 사용할 수 없습니다")

    indexed = 0
    docs_indexed = 0
    docs_skipped = 0
    mentions_created = 0
    anchors_created = 0
    timeline_events_created = 0
    grouping = ctx.params.get("grouping") if isinstance(ctx.params, dict) else None
    if not isinstance(grouping, dict):
        grouping = None
    group_entities = bool(grouping.get("entity_mentions")) if grouping else False
    group_time = bool(grouping.get("time_anchors")) if grouping else False
    timeline_doc_id = grouping.get("timeline_doc_id") if grouping else None
    with db.connect(ctx._db_path) as conn:
        project_episodes = document_repo.list_episodes(conn, ctx.project_id)
        timeline_events: list[dict[str, Any]] = []
        if timeline_doc_id is None and grouping:
            project = project_repo.get_project(conn, ctx.project_id)
            if project and isinstance(project.settings, dict):
                timeline_doc_id = project.settings.get("timeline_doc_id")
        if grouping and isinstance(timeline_doc_id, str):
            timeline_doc = document_repo.get_document(conn, timeline_doc_id)
            if timeline_doc is not None:
                timeline_snapshot = document_repo.get_snapshot(conn, timeline_doc.head_snapshot_id)
                if timeline_snapshot is not None:
                    timeline_text = docstore.read_text(timeline_snapshot.path)
                    timeline_events = _build_timeline_events(timeline_text)
                    schema_repo.delete_timeline_events(
                        conn,
                        project_id=ctx.project_id,
                        source_doc_id=timeline_doc_id,
                        commit=False,
                    )
                    for event in timeline_events:
                        schema_repo.create_timeline_event(
                            conn,
                            project_id=ctx.project_id,
                            timeline_idx=int(event["timeline_idx"]),
                            label=str(event["label"]),
                            time_key=str(event["time_key"]),
                            source_doc_id=timeline_doc_id,
                            source_snapshot_id=timeline_snapshot.snapshot_id,
                            span_start=int(event["span_start"]),
                            span_end=int(event["span_end"]),
                            status=FactStatus.PROPOSED,
                            created_by=FactSource.AUTO,
                            commit=False,
                        )
                        timeline_events_created += 1
                    conn.commit()

        alias_index: dict[str, set[str]] = {}
        if group_entities:
            entities = schema_repo.list_entities(conn, ctx.project_id)
            aliases = []
            for entity in entities:
                aliases.extend(schema_repo.list_entity_aliases(conn, ctx.project_id, entity.entity_id))
            alias_index = build_alias_index(entities, aliases)

        if scope == "global":
            docs = document_repo.list_documents(conn, ctx.project_id)
        else:
            doc = document_repo.get_document(conn, scope)
            docs = [doc] if doc else []

        for doc in docs:
            if doc is None:
                continue
            if snapshot_id:
                snapshot = document_repo.get_snapshot(conn, snapshot_id)
            else:
                snapshot = document_repo.get_snapshot(conn, doc.head_snapshot_id)
            if snapshot is None:
                continue
            episode_id = _resolve_episode_id(conn, doc.project_id, doc, episodes=project_episodes)
            if snapshot_id and snapshot.doc_id != doc.doc_id:
                raise RuntimeError("snapshot_id does not belong to the selected document scope")

            meta_checksum = _fts_meta_checksum(
                conn,
                doc_id=doc.doc_id,
                snapshot_id=snapshot.snapshot_id,
                snapshot_checksum=snapshot.checksum,
                episode_id=episode_id,
            )
            prev_checksum = fts_meta_repo.get_checksum(conn, doc.doc_id)
            needs_index = (
                prev_checksum != meta_checksum
                or not _snapshot_has_chunks(conn, snapshot.snapshot_id)
                or not _snapshot_has_fts_rows(conn, snapshot.snapshot_id)
            )

            text = None
            if needs_index or grouping:
                text = docstore.read_text(snapshot.path)

            if needs_index:
                chunks = build_chunks(
                    project_id=doc.project_id,
                    doc_id=doc.doc_id,
                    snapshot_id=snapshot.snapshot_id,
                    text=text or "",
                )
                if episode_id is not None:
                    chunks = [replace(chunk, episode_id=episode_id) for chunk in chunks]
                chunk_repo.replace_chunks_for_snapshot(conn, snapshot.snapshot_id, chunks, commit=False)
                index_chunks(conn, snapshot_id=snapshot.snapshot_id, chunks=chunks, text=text or "", commit=False)
                fts_meta_repo.upsert(conn, doc.doc_id, meta_checksum, commit=False)
                indexed += len(chunks)
                docs_indexed += 1
            else:
                docs_skipped += 1

            if not grouping:
                conn.commit()
                continue
            spans = _sentence_spans(text or "")
            if group_entities and alias_index:
                schema_repo.delete_entity_mention_spans(
                    conn,
                    project_id=ctx.project_id,
                    doc_id=doc.doc_id,
                    snapshot_id=snapshot.snapshot_id,
                    commit=False,
                )
                for entity_id, span_start, span_end in _extract_entity_mentions(spans, alias_index):
                    schema_repo.create_entity_mention_span(
                        conn,
                        project_id=ctx.project_id,
                        doc_id=doc.doc_id,
                        snapshot_id=snapshot.snapshot_id,
                        entity_id=entity_id,
                        span_start=span_start,
                        span_end=span_end,
                        status=FactStatus.PROPOSED,
                        created_by=FactSource.AUTO,
                        commit=False,
                    )
                    mentions_created += 1
            if group_time:
                schema_repo.delete_time_anchors(
                    conn,
                    project_id=ctx.project_id,
                    doc_id=doc.doc_id,
                    snapshot_id=snapshot.snapshot_id,
                    commit=False,
                )
                episode_key = _episode_key(doc)
                for idx, (span_start, span_end, segment) in enumerate(spans, start=1):
                    phrases = _extract_time_phrases(segment)
                    for phrase in phrases:
                        time_key = f"{episode_key}/scene:{idx}/rel:{phrase}"
                        timeline_idx = _match_timeline_idx(segment, time_key, timeline_events)
                        schema_repo.create_time_anchor(
                            conn,
                            project_id=ctx.project_id,
                            doc_id=doc.doc_id,
                            snapshot_id=snapshot.snapshot_id,
                            span_start=span_start,
                            span_end=span_end,
                            time_key=time_key,
                            timeline_idx=timeline_idx,
                            status=FactStatus.PROPOSED,
                            created_by=FactSource.AUTO,
                            commit=False,
                        )
                        anchors_created += 1
            conn.commit()

    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="fts indexed",
            progress=1.0,
            payload={
                "chunks_indexed": indexed,
                "docs_indexed": docs_indexed,
                "docs_skipped": docs_skipped,
                "incremental": True,
                "entity_mentions_created": mentions_created,
                "time_anchors_created": anchors_created,
                "timeline_events_created": timeline_events_created,
                **_standard_metrics_payload(
                    start_perf=start_perf,
                    chunks_processed=indexed,
                ),
            },
        )
    )


def _run_consistency_preflight(ctx: WorkerContext, *, doc_id: str, snapshot_id: str, preflight: dict[str, Any]) -> None:
    ensure_ingest = bool(preflight.get("ensure_ingest"))
    ensure_index_fts = bool(preflight.get("ensure_index_fts"))
    if not ensure_ingest and not ensure_index_fts:
        return

    ingest_targets: list[tuple[str, str]] = []
    index_targets: list[str] = []

    with db.connect(ctx._db_path) as conn:
        docs = document_repo.list_documents(conn, ctx.project_id)
        if not docs:
            fallback_doc = document_repo.get_document(conn, doc_id)
            docs = [fallback_doc] if fallback_doc is not None else []
        episodes = document_repo.list_episodes(conn, ctx.project_id)
        assignment_sig_cache: dict[str, str] = {}

        tag_defs_sig = ""
        alias_sig = ""
        if ensure_ingest:
            tag_defs = schema_repo.list_tag_defs(conn, ctx.project_id)
            tag_defs_sig = _tag_def_signature(tag_defs)
            alias_sig = _alias_signature(_collect_aliases(conn, ctx.project_id))

        for item in docs:
            if item is None:
                continue
            target_snapshot_id = snapshot_id if item.doc_id == doc_id else item.head_snapshot_id
            snapshot = document_repo.get_snapshot(conn, target_snapshot_id)
            if snapshot is None:
                continue

            if ensure_ingest:
                ingest_checksum = _ingest_checksum_for_doc(
                    conn,
                    doc_id=item.doc_id,
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_checksum=snapshot.checksum,
                    tag_defs_sig=tag_defs_sig,
                    alias_sig=alias_sig,
                    assignment_sig_cache=assignment_sig_cache,
                )
                previous_state = ingest_meta_repo.get_state(conn, item.doc_id)
                if previous_state != (snapshot.snapshot_id, ingest_checksum):
                    ingest_targets.append((item.doc_id, snapshot.snapshot_id))

            if ensure_index_fts:
                tag_sig = assignment_sig_cache.get(snapshot.snapshot_id)
                if tag_sig is None:
                    tag_sig = _tag_assignment_signature(conn, snapshot.snapshot_id)
                    assignment_sig_cache[snapshot.snapshot_id] = tag_sig
                episode_id = _resolve_episode_id(conn, item.project_id, item, episodes=episodes)
                meta_checksum = _fts_meta_checksum(
                    conn,
                    doc_id=item.doc_id,
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_checksum=snapshot.checksum,
                    episode_id=episode_id,
                    tag_sig=tag_sig,
                )
                prev_checksum = fts_meta_repo.get_checksum(conn, item.doc_id)
                needs_index = (
                    prev_checksum != meta_checksum
                    or not _snapshot_has_chunks(conn, snapshot.snapshot_id)
                    or not _snapshot_has_fts_rows(conn, snapshot.snapshot_id)
                )
                if needs_index:
                    index_targets.append(item.doc_id)

    if ensure_index_fts and ingest_targets:
        existing = set(index_targets)
        for target_doc_id, _ in ingest_targets:
            if target_doc_id not in existing:
                existing.add(target_doc_id)
                index_targets.append(target_doc_id)

    if ensure_ingest:
        ctx.emit(
            JobEvent(
                event_id="",
                job_id=ctx.job_id,
                ts="",
                level=JobEventLevel.INFO,
                message="consistency preflight ingest",
                progress=None,
                payload={"target_count": len(ingest_targets), "incremental": True},
            )
        )
        for target_doc_id, target_snapshot_id in ingest_targets:
            _handle_ingest(
                WorkerContext(
                    job_id=ctx.job_id,
                    project_id=ctx.project_id,
                    payload={"doc_id": target_doc_id, "snapshot_id": target_snapshot_id},
                    params=ctx.params,
                    db_path=ctx._db_path,
                    lease_seconds=ctx._lease_seconds,
                )
            )

    if ensure_index_fts:
        ctx.emit(
            JobEvent(
                event_id="",
                job_id=ctx.job_id,
                ts="",
                level=JobEventLevel.INFO,
                message="consistency preflight index_fts",
                progress=None,
                payload={"target_count": len(index_targets), "incremental": True},
            )
        )
        for target_doc_id in index_targets:
            _handle_index_fts(
                WorkerContext(
                    job_id=ctx.job_id,
                    project_id=ctx.project_id,
                    payload={"scope": target_doc_id},
                    params=ctx.params,
                    db_path=ctx._db_path,
                    lease_seconds=ctx._lease_seconds,
                )
            )


def _handle_consistency(ctx: WorkerContext) -> None:
    start_perf = time.perf_counter()
    engine = ConsistencyEngineImpl(db_path=ctx._db_path)
    req = dict(ctx.payload)
    req.setdefault("project_id", ctx.project_id)
    preflight = _parse_consistency_preflight(req)

    # Resolve 'latest' snapshot.
    if req.get("input_snapshot_id") == "latest":
        doc_id = req.get("input_doc_id")
        if isinstance(doc_id, str):
            with db.connect(ctx._db_path) as conn:
                doc = document_repo.get_document(conn, doc_id)
                if doc:
                    req["input_snapshot_id"] = doc.head_snapshot_id

    doc_id = req.get("input_doc_id")
    snapshot_id = req.get("input_snapshot_id")
    if not isinstance(doc_id, str) or not isinstance(snapshot_id, str):
        raise RuntimeError("input_doc_id/input_snapshot_id missing")

    _run_consistency_preflight(ctx, doc_id=doc_id, snapshot_id=snapshot_id, preflight=preflight)

    req["preflight"] = preflight
    req.setdefault("schema_scope", preflight["schema_scope"])
    req_stats: dict[str, Any] = {}
    req["stats"] = req_stats
    verdicts = engine.run(req)
    total = len(verdicts)
    violates = len([v for v in verdicts if v.verdict is Verdict.VIOLATE])
    unknowns = len([v for v in verdicts if v.verdict is Verdict.UNKNOWN])
    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="consistency complete",
            progress=1.0,
            payload={
                "vid_count": total,
                "violate_count": violates,
                "unknown_count": unknowns,
                **_standard_metrics_payload(
                    start_perf=start_perf,
                    claims_processed=int(req_stats.get("claims_processed", total)),
                    chunks_processed=int(req_stats.get("chunks_processed", 0)),
                    rows_scanned=int(req_stats.get("rows_scanned", 0)),
                    shards_loaded=int(req_stats.get("shards_loaded", 0)),
                ),
            },
        )
    )


def _handle_retrieve_vec(ctx: WorkerContext) -> None:
    start_perf = time.perf_counter()
    query = ctx.payload.get("query")
    filters = ctx.payload.get("filters") or {}
    k = int(ctx.payload.get("k") or 10)
    if not isinstance(query, str):
        raise RuntimeError("query missing")
    req_stats: dict[str, Any] = {}
    req = {
        "project_id": ctx.project_id,
        "query": query,
        "filters": filters,
        "k": k,
        "stats": req_stats,
    }
    results = vector_search(req)
    if results and isinstance(filters, dict):
        with db.connect(ctx._db_path) as conn:
            results = _filter_results_by_meta(conn, ctx.project_id, results, filters)
    if not results:
        with db.connect(ctx._db_path) as conn:
            results = fts_search(conn, req)
        for result in results:
            result["source"] = "fts"
    page_size = 5
    for idx in range(0, len(results), page_size):
        page = results[idx : idx + page_size]
        ctx.emit(
            JobEvent(
                event_id="",
                job_id=ctx.job_id,
                ts="",
                level=JobEventLevel.INFO,
                message="retrieve_vec page",
                progress=None,
                payload={"results": page, "page": idx // page_size},
            )
        )
        if ctx.check_cancelled():
            raise CancelledError("cancel requested")
    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="retrieve_vec complete",
            progress=1.0,
            payload={
                "result_count": len(results),
                **_standard_metrics_payload(
                    start_perf=start_perf,
                    chunks_processed=int(req_stats.get("chunks_processed", len(results))),
                    rows_scanned=int(req_stats.get("rows_scanned", 0)),
                    shards_loaded=int(req_stats.get("shards_loaded", 0)),
                ),
            },
        )
    )


def _handle_suggest(ctx: WorkerContext) -> None:
    mode_raw = ctx.payload.get("mode")
    claim_text = ctx.payload.get("claim_text") or ""
    include_citations = bool(ctx.payload.get("include_citations", False))
    range_info = ctx.payload.get("range") or {}
    if not isinstance(range_info, dict):
        range_info = {}
    mode = SuggestMode(mode_raw) if isinstance(mode_raw, str) else SuggestMode.LOCAL_RULE
    gateway = select_model(purpose="suggest_local_rule")

    doc_scope = None
    doc_id_raw = range_info.get("doc_id")
    if isinstance(doc_id_raw, str) and doc_id_raw.strip():
        doc_scope = doc_id_raw.strip()
    fingerprint = f"sha256:{hashlib.sha256(str(claim_text).strip().encode('utf-8')).hexdigest()}"
    with db.connect(ctx._db_path) as conn:
        if ignore_repo.is_ignored(conn, ctx.project_id, fingerprint, scope=doc_scope, kind="SUGGEST"):
            suggestion_id = str(uuid.uuid4())
            ctx.emit(
                JobEvent(
                    event_id="",
                    job_id=ctx.job_id,
                    ts="",
                    level=JobEventLevel.INFO,
                    message="suggest suppressed (ignored)",
                    progress=1.0,
                    payload={
                        "suggestion_id": suggestion_id,
                        "text": "",
                        "citations": [],
                        "suppressed": True,
                        "reason": "ignored",
                    },
                )
            )
            return

    k = ctx.payload.get("k") or 3
    try:
        k = int(k)
    except (TypeError, ValueError):
        k = 3
    k = max(1, min(10, k))

    filters: dict[str, Any] = {}
    payload_filters = ctx.payload.get("filters")
    if isinstance(payload_filters, dict):
        filters.update(payload_filters)
    doc_id_filter = range_info.get("doc_id")
    if "doc_id" not in filters and isinstance(doc_id_filter, str) and doc_id_filter.strip():
        filters["doc_id"] = doc_id_filter.strip()

    req = {
        "project_id": ctx.project_id,
        "query": str(claim_text),
        "filters": filters,
        "k": k,
    }
    with db.connect(ctx._db_path) as conn:
        results = fts_search(conn, req)
    if not results and load_config().vector_index_mode.upper() != "DISABLED":
        results = vector_search(req)
    evidences: list[dict[str, Any]] = []
    for result in results:
        evidence_raw = result.get("evidence") or {}
        if isinstance(evidence_raw, dict):
            evidences.append(evidence_raw)
    bundle = {"claim_text": claim_text, "evidence": evidences}
    if mode is SuggestMode.LOCAL_RULE:
        text = gateway.suggest_local_rule(bundle)
    elif mode is SuggestMode.API:
        text = gateway.suggest_remote_api(bundle)
    else:
        text = gateway.suggest_local_gen(bundle)
    suggestion_id = str(uuid.uuid4())

    citations: list[dict[str, Any]] = []
    if include_citations:
        for evidence in evidences[:5]:
            citations.append(
                {
                    "doc_id": evidence.get("doc_id", ""),
                    "snapshot_id": evidence.get("snapshot_id", ""),
                    "tag_path": evidence.get("tag_path", ""),
                    "section_path": evidence.get("section_path", ""),
                    "snippet_text": evidence.get("snippet_text", ""),
                }
            )
    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="suggest complete",
            progress=1.0,
            payload={"suggestion_id": suggestion_id, "text": text, "citations": citations},
        )
    )


def _handle_export(ctx: WorkerContext) -> None:
    range_info = ctx.payload.get("range") or {}
    export_format = ctx.payload.get("format") or "txt"
    include_meta = bool(ctx.payload.get("include_meta", False))
    doc_id = range_info.get("doc_id")
    snapshot_id = range_info.get("snapshot_id")
    if not isinstance(doc_id, str):
        raise RuntimeError("range.doc_id required")

    meta_lines: list[str] | None = None
    meta_rows: list[dict[str, str]] | None = None
    with db.connect(ctx._db_path) as conn:
        if isinstance(snapshot_id, str):
            snapshot = document_repo.get_snapshot(conn, snapshot_id)
        else:
            doc = document_repo.get_document(conn, doc_id)
            snapshot = document_repo.get_snapshot(conn, doc.head_snapshot_id) if doc else None
        if snapshot is None:
            raise RuntimeError("snapshot not found")
        input_path = snapshot.path
        if include_meta:
            schema_ver = ""
            latest = schema_repo.get_latest_schema_version(conn, ctx.project_id)
            if latest:
                schema_ver = latest.schema_ver
            facts = (
                schema_repo.list_schema_facts(conn, ctx.project_id, schema_ver=schema_ver) if schema_ver else []
            )
            evidence = evidence_repo.list_evidence(
                conn,
                ctx.project_id,
                doc_id=doc_id,
                snapshot_id=snapshot.snapshot_id,
            )
            evidence_map = {item.eid: item for item in evidence}

            meta_lines = [
                "Metadata",
                f"schema_ver: {schema_ver}",
                f"fact_count: {len(facts)}",
            ]
            meta_rows = []
            for fact in facts:
                ev = evidence_map.get(fact.evidence_eid)
                snippet = ev.snippet_text if ev else ""
                snippet = snippet[:120] if snippet else ""
                try:
                    value = json.dumps(fact.value, ensure_ascii=False)
                except TypeError:
                    value = str(fact.value)
                meta_rows.append(
                    {
                        "tag_path": fact.tag_path,
                        "value": value,
                        "status": fact.status.value,
                        "evidence": snippet,
                    }
                )

    exporter = ExporterImpl()
    filename = f"{doc_id}.{export_format}"
    output_path = docstore.export_path(ctx.project_id, ctx.job_id, filename)
    if export_format == "txt":
        exporter.export_txt(
            input_path=input_path,
            output_path=output_path,
            include_meta=include_meta,
            meta_lines=meta_lines,
        )
    elif export_format == "docx":
        exporter.export_docx(
            input_path=input_path,
            output_path=output_path,
            include_meta=include_meta,
            meta_lines=meta_lines,
            meta_rows=meta_rows,
        )
    else:
        raise RuntimeError("unsupported format")

    size_bytes = output_path.stat().st_size if output_path.exists() else 0
    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="export complete",
            progress=1.0,
            payload={"artifact_path": str(output_path), "size_bytes": size_bytes},
        )
    )


def _handle_proofread(ctx: WorkerContext) -> None:
    doc_id = ctx.payload.get("doc_id")
    snapshot_id = ctx.payload.get("snapshot_id")
    if not isinstance(doc_id, str) or not isinstance(snapshot_id, str):
        raise RuntimeError("doc_id/snapshot_id missing")
    with db.connect(ctx._db_path) as conn:
        snapshot = document_repo.get_snapshot(conn, snapshot_id)
        if snapshot is None:
            raise RuntimeError("snapshot not found")
        text = docstore.read_text(snapshot.path)

    lint_items: list[LintItem] = []
    max_items = 500

    def add_item(item: LintItem) -> None:
        if len(lint_items) >= max_items:
            return
        lint_items.append(item)

    for match in re.finditer(r" {2,}", text):
        add_item(
            LintItem(
                span_start=match.start(),
                span_end=match.end(),
                rule_id="double-space",
                severity="WARN",
                message="연속된 공백이 있습니다.",
                suggestion=" ",
            )
        )

    for match in re.finditer(r"[\\t ]+(?=\\r?\\n)", text):
        add_item(
            LintItem(
                span_start=match.start(),
                span_end=match.end(),
                rule_id="trailing-whitespace",
                severity="INFO",
                message="줄 끝 공백이 있습니다.",
                suggestion="",
            )
        )

    for match in re.finditer(r"\\n{3,}", text):
        add_item(
            LintItem(
                span_start=match.start(),
                span_end=match.end(),
                rule_id="many-blank-lines",
                severity="INFO",
                message="빈 줄이 너무 많습니다.",
                suggestion="\\n\\n",
            )
        )

    for match in re.finditer(r"[\\t ]+([,.;:!?])", text):
        add_item(
            LintItem(
                span_start=match.start(),
                span_end=match.end(),
                rule_id="space-before-punct",
                severity="WARN",
                message="구두점 앞 공백을 제거하세요.",
                suggestion=match.group(1),
            )
        )

    for match in re.finditer(r"([!?])\\1{1,}", text):
        add_item(
            LintItem(
                span_start=match.start(),
                span_end=match.end(),
                rule_id="repeated-punct",
                severity="INFO",
                message="구두점이 반복되었습니다.",
                suggestion=match.group(1),
            )
        )

    for match in re.finditer(r"\\.{4,}", text):
        add_item(
            LintItem(
                span_start=match.start(),
                span_end=match.end(),
                rule_id="ellipsis",
                severity="INFO",
                message="말줄임표는 '...' 형태를 권장합니다.",
                suggestion="...",
            )
        )

    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="proofread complete",
            progress=1.0,
            payload={"lint_items": [asdict(item) for item in lint_items]},
        )
    )


def _handle_index_vec(ctx: WorkerContext) -> None:
    start_perf = time.perf_counter()
    scope = ctx.payload.get("scope")
    if not isinstance(scope, str):
        raise RuntimeError("scope missing")
    new_shards = []
    chunks_processed = 0
    settings = load_config()
    with db.connect(ctx._db_path) as conn:
        if scope == "global":
            docs = document_repo.list_documents(conn, ctx.project_id)
        else:
            doc = document_repo.get_document(conn, scope)
            docs = [doc] if doc else []
        for doc in docs:
            if doc is None:
                continue
            snapshot = document_repo.get_snapshot(conn, doc.head_snapshot_id)
            if snapshot is None:
                continue
            text = docstore.read_text(snapshot.path)
            chunks = chunk_repo.list_chunks_for_snapshot(conn, snapshot.snapshot_id)
            if not chunks:
                chunks = build_chunks(
                    project_id=doc.project_id,
                    doc_id=doc.doc_id,
                    snapshot_id=snapshot.snapshot_id,
                    text=text,
                )
            episode_id = _resolve_episode_id(conn, doc.project_id, doc)
            if episode_id is not None and any(chunk.episode_id != episode_id for chunk in chunks):
                chunks = [replace(chunk, episode_id=episode_id) for chunk in chunks]
            chunk_repo.replace_chunks_for_snapshot(conn, snapshot.snapshot_id, chunks)
            if settings.max_ram_mb > 0:
                usage_mb = _get_process_rss_mb()
                estimated_mb = _estimate_index_mb(text, len(chunks))
                if usage_mb > 0 and usage_mb + estimated_mb > settings.max_ram_mb:
                    ctx.emit(
                        JobEvent(
                            event_id="",
                            job_id=ctx.job_id,
                            ts="",
                            level=JobEventLevel.WARN,
                            message="vector index throttled",
                            progress=None,
                            payload={
                                "doc_id": doc.doc_id,
                                "estimated_mb": estimated_mb,
                                "usage_mb": usage_mb,
                            },
                        )
                    )
                    continue
            assignments = schema_repo.list_tag_assignments(
                conn,
                doc.project_id,
                doc_id=doc.doc_id,
                snapshot_id=snapshot.snapshot_id,
            )
            tag_paths_by_chunk_id = _compute_tag_paths_by_chunk_id(chunks, assignments)
            _, meta = build_shard(
                doc_id=doc.doc_id,
                snapshot_id=snapshot.snapshot_id,
                chunks=chunks,
                text=text,
                tag_paths_by_chunk_id=tag_paths_by_chunk_id,
            )
            meta["checksum"] = doc.checksum
            new_shards.append(meta)
            chunks_processed += len(chunks)
    if new_shards:
        update_manifest(new_shards)
    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="vector index complete",
            progress=1.0,
            payload={
                "shards_built": len(new_shards),
                **_standard_metrics_payload(
                    start_perf=start_perf,
                    chunks_processed=chunks_processed,
                ),
            },
        )
    )
