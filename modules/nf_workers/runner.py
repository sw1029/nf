from __future__ import annotations

import json
import resource
import time
import uuid
from dataclasses import asdict
from typing import Any

from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_export.exporter import ExporterImpl
from modules.nf_model_gateway.gateway import select_model
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import (
    chunk_repo,
    document_repo,
    evidence_repo,
    job_repo,
    schema_repo,
)
from modules.nf_retrieval.fts.fts_index import fts_search, index_chunks
from modules.nf_retrieval.vector.manifest import update_manifest, vector_search
from modules.nf_retrieval.vector.shard_store import build_shard
from modules.nf_schema.chunking import build_chunks
from modules.nf_schema.conflict import resolve_conflicts
from modules.nf_schema.extraction import extract_explicit_candidates
from modules.nf_schema.identity import build_alias_index, resolve_entity_id
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

    while True:
        if _memory_pressure(settings.max_ram_mb):
            time.sleep(poll_interval)
            continue
        with db.connect(db_path) as conn:
            allow_heavy = job_repo.count_running_jobs(conn, heavy_types) == 0
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
    usage_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    usage_mb = usage_kb / 1024
    return usage_mb > max_ram_mb


def _estimate_index_mb(text: str, chunk_count: int) -> float:
    text_mb = len(text.encode("utf-8")) / (1024 * 1024)
    return text_mb * 2.0 + chunk_count * 0.001


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
    doc_id = ctx.payload.get("doc_id")
    snapshot_id = ctx.payload.get("snapshot_id")
    if not isinstance(doc_id, str):
        raise RuntimeError("doc_id missing")

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
        text = docstore.read_text(snapshot.path)
        tag_defs = schema_repo.list_tag_defs(conn, doc.project_id)
        tag_def_map = {tag.tag_path: tag for tag in tag_defs}
        entities = schema_repo.list_entities(conn, doc.project_id)
        aliases = []
        for entity in entities:
            aliases.extend(schema_repo.list_entity_aliases(conn, doc.project_id, entity.entity_id))
        alias_index = build_alias_index(entities, aliases)
        assignments = schema_repo.list_tag_assignments(
            conn,
            doc.project_id,
            doc_id=doc_id,
            snapshot_id=snapshot.snapshot_id,
        )
        schema_ver = schema_repo.create_schema_version(
            conn,
            project_id=doc.project_id,
            source_snapshot_id=snapshot.snapshot_id,
        ).schema_ver

        facts: list[SchemaFact] = []
        seen_tag_paths: set[str] = set()
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
            evidence_repo.create_evidence(conn, evidence)
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
            evidence_repo.create_evidence(conn, evidence)
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
            evidence_repo.create_evidence(conn, evidence)
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
        proposed = 0
        approved = 0
        for fact in facts:
            schema_repo.create_schema_fact(conn, fact)
            if fact.status is FactStatus.PROPOSED:
                proposed += 1
            if fact.status is FactStatus.APPROVED:
                approved += 1

    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="ingest complete",
            progress=1.0,
            payload={"schema_ver": schema_ver, "proposed_fact_count": proposed, "approved_fact_count": approved},
        )
    )


def _handle_index_fts(ctx: WorkerContext) -> None:
    scope = ctx.payload.get("scope")
    snapshot_id = ctx.payload.get("snapshot_id")
    if not isinstance(scope, str):
        raise RuntimeError("scope missing")

    indexed = 0
    with db.connect(ctx._db_path) as conn:
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
            text = docstore.read_text(snapshot.path)
            chunks = build_chunks(
                project_id=doc.project_id,
                doc_id=doc.doc_id,
                snapshot_id=snapshot.snapshot_id,
                text=text,
            )
            chunk_repo.replace_chunks_for_snapshot(conn, snapshot.snapshot_id, chunks)
            index_chunks(conn, snapshot_id=snapshot.snapshot_id, chunks=chunks, text=text)
            indexed += len(chunks)

    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="fts indexed",
            progress=1.0,
            payload={"chunks_indexed": indexed},
        )
    )


def _handle_consistency(ctx: WorkerContext) -> None:
    engine = ConsistencyEngineImpl(db_path=ctx._db_path)
    req = dict(ctx.payload)
    req.setdefault("project_id", ctx.project_id)
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
            },
        )
    )


def _handle_retrieve_vec(ctx: WorkerContext) -> None:
    query = ctx.payload.get("query")
    filters = ctx.payload.get("filters") or {}
    k = int(ctx.payload.get("k") or 10)
    if not isinstance(query, str):
        raise RuntimeError("query missing")
    req = {
        "project_id": ctx.project_id,
        "query": query,
        "filters": filters,
        "k": k,
    }
    results = vector_search(req)
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


def _handle_suggest(ctx: WorkerContext) -> None:
    mode_raw = ctx.payload.get("mode")
    claim_text = ctx.payload.get("claim_text") or ""
    mode = SuggestMode(mode_raw) if isinstance(mode_raw, str) else SuggestMode.LOCAL_RULE
    gateway = select_model(purpose="suggest_local_rule")
    bundle = {"claim_text": claim_text, "evidence": []}
    if mode is SuggestMode.LOCAL_RULE:
        text = gateway.suggest_local_rule(bundle)
    elif mode is SuggestMode.API:
        text = gateway.suggest_remote_api(bundle)
    else:
        text = gateway.suggest_local_gen(bundle)
    suggestion_id = str(uuid.uuid4())
    ctx.emit(
        JobEvent(
            event_id="",
            job_id=ctx.job_id,
            ts="",
            level=JobEventLevel.INFO,
            message="suggest complete",
            progress=1.0,
            payload={"suggestion_id": suggestion_id, "text": text, "citations": []},
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
    idx = text.find("  ")
    while idx != -1:
        lint_items.append(
            LintItem(
                span_start=idx,
                span_end=idx + 2,
                rule_id="double-space",
                severity="WARN",
                message="double space detected",
                suggestion=" ",
            )
        )
        idx = text.find("  ", idx + 2)

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
    scope = ctx.payload.get("scope")
    if not isinstance(scope, str):
        raise RuntimeError("scope missing")
    new_shards = []
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
                chunk_repo.replace_chunks_for_snapshot(conn, snapshot.snapshot_id, chunks)
            if settings.max_ram_mb > 0:
                usage_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                estimated_mb = _estimate_index_mb(text, len(chunks))
                if usage_mb + estimated_mb > settings.max_ram_mb:
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
            _, meta = build_shard(doc_id=doc.doc_id, snapshot_id=snapshot.snapshot_id, chunks=chunks, text=text)
            meta["checksum"] = doc.checksum
            new_shards.append(meta)
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
            payload={"shards_built": len(new_shards)},
        )
    )
