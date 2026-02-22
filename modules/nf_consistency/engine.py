from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from modules.nf_consistency.contracts import ConsistencyRequest
from modules.nf_consistency.extractors import ExtractionPipeline, normalize_extraction_profile
from modules.nf_consistency.extractors.contracts import ExtractionMapping as ExtractorMapping
from modules.nf_model_gateway.gateway import select_model
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import (
    document_repo,
    evidence_repo,
    ignore_repo,
    schema_repo,
    whitelist_repo,
)
from modules.nf_retrieval.fts.fts_index import fts_search
from modules.nf_retrieval.graph.rerank import expand_candidate_docs_with_graph
from modules.nf_retrieval.vector.manifest import vector_search
from modules.nf_schema.identity import build_alias_index, find_entity_candidates
from modules.nf_shared.config import load_config
from modules.nf_shared.protocol.dtos import (
    EvidenceMatchType,
    EvidenceRole,
    FactStatus,
    ReliabilityBreakdown,
    SchemaLayer,
    Span,
    Verdict,
    VerdictEvidenceLink,
    VerdictLog,
)
_FACT_ALL_KEY = "__all__"
_ALLOWED_EVIDENCE_LINK_POLICIES = {"full", "cap", "contradict_only"}
_DEFAULT_EVIDENCE_LINK_CAP = 20
_DEFAULT_SELF_EVIDENCE_SCOPE = "range"
_DEFAULT_GRAPH_DOC_CAP = 200


def _fingerprint(text: str) -> str:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _segment_text(text: str) -> list[tuple[int, int, str]]:
    segments: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[^\n]+", text):
        segment = match.group(0).strip()
        if not segment:
            continue
        segments.append((match.start(), match.end(), segment))
    return segments


def _extract_slots(segment: str, *, pipeline: ExtractionPipeline | None = None) -> dict[str, object]:
    if pipeline is None:
        return {}
    return pipeline.extract(segment).slots


def _extract_claims(
    text: str,
    *,
    pipeline: ExtractionPipeline | None = None,
    stats: dict[str, Any] | None = None,
) -> list[tuple[int, int, str, dict[str, object]]]:
    claims = []
    for span_start, span_end, segment in _segment_text(text):
        if pipeline is None:
            slots = {}
            result_rule_ms = 0.0
            result_model_ms = 0.0
        else:
            result = pipeline.extract(segment)
            slots = result.slots
            result_rule_ms = result.rule_eval_ms
            result_model_ms = result.model_eval_ms
        if stats is not None:
            stats["rule_eval_ms"] = float(stats.get("rule_eval_ms", 0.0)) + result_rule_ms
            stats["model_eval_ms"] = float(stats.get("model_eval_ms", 0.0)) + result_model_ms
            stats["slot_matches"] = int(stats.get("slot_matches", 0)) + len(slots)
        if slots:
            claims.append((span_start, span_end, segment, slots))
    return claims


def _bundle_evidence(evidences: list) -> list[dict[str, object]]:
    bundled = []
    for evidence in evidences:
        bundled.append(
            {
                "doc_id": evidence.doc_id,
                "snapshot_id": evidence.snapshot_id,
                "chunk_id": evidence.chunk_id,
                "section_path": evidence.section_path,
                "tag_path": evidence.tag_path,
                "snippet_text": evidence.snippet_text,
                "span_start": evidence.span_start,
                "span_end": evidence.span_end,
                "match_type": evidence.match_type.value,
                "confirmed": evidence.confirmed,
            }
        )
    return bundled


def _fact_slot_key(tag_path: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", tag_path or "").lower()
    if "나이" in normalized:
        return "age"
    if "시간" in normalized or "시점" in normalized or "날짜" in normalized or "일시" in normalized:
        return "time"
    if "장소" in normalized or "위치" in normalized:
        return "place"
    if "관계" in normalized:
        return "relation"
    if "소속" in normalized:
        return "affiliation"
    if "사망" in normalized or "생존" in normalized:
        return "death"
    if "직업" in normalized or "클래스" in normalized:
        return "job"
    if "재능" in normalized:
        return "talent"
    return None


def _norm_text(value: object) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().lower()


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = _norm_text(value)
    match = re.search(r"-?\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _norm_text(value)
    if not text:
        return None
    true_values = {"1", "true", "yes", "사망", "죽음", "죽었다", "죽었", "사망함", "사망했다"}
    false_values = {"0", "false", "no", "생존", "살아있다", "살아있음"}
    if text in true_values:
        return True
    if text in false_values:
        return False
    return None


def _compare_slot(slot_key: str, claimed_value: object, fact_value: object) -> Verdict | None:
    if slot_key == "age":
        claimed = _coerce_int(claimed_value)
        expected = _coerce_int(fact_value)
        if claimed is None or expected is None:
            return None
        return Verdict.OK if claimed == expected else Verdict.VIOLATE

    if slot_key == "death":
        claimed = _coerce_bool(claimed_value)
        expected = _coerce_bool(fact_value)
        if claimed is None or expected is None:
            return None
        return Verdict.OK if claimed == expected else Verdict.VIOLATE

    if slot_key in {"time", "place", "relation", "affiliation", "job", "talent"}:
        claimed = _norm_text(claimed_value)
        expected = _norm_text(fact_value)
        if not claimed or not expected:
            return None
        if claimed == expected or claimed in expected or expected in claimed:
            return Verdict.OK
        return Verdict.VIOLATE

    return None


def _resolve_schema_scope(req: ConsistencyRequest) -> str:
    scope = req.get("schema_scope")
    if isinstance(scope, str) and scope in {"latest_approved", "explicit_only"}:
        return scope
    preflight = req.get("preflight")
    if isinstance(preflight, dict):
        preflight_scope = preflight.get("schema_scope")
        if isinstance(preflight_scope, str) and preflight_scope in {"latest_approved", "explicit_only"}:
            return preflight_scope
    return "latest_approved"


def _normalize_consistency_filters(raw: Any) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, object] = {}

    entity_id = raw.get("entity_id")
    if isinstance(entity_id, str) and entity_id.strip():
        normalized["entity_id"] = entity_id.strip()

    time_key = raw.get("time_key")
    if isinstance(time_key, str) and time_key.strip():
        normalized["time_key"] = time_key.strip()

    timeline_idx = raw.get("timeline_idx")
    if timeline_idx is not None:
        try:
            normalized["timeline_idx"] = int(timeline_idx)
        except (TypeError, ValueError):
            pass
    return normalized


def _load_facts_for_scope(
    conn,
    *,
    project_id: str,
    schema_ver: str | None,
    scope: str,
) -> tuple[str, list]:
    latest = schema_repo.get_latest_schema_version(conn, project_id)
    latest_schema_ver = latest.schema_ver if latest else ""
    resolved_schema_ver = schema_ver or latest_schema_ver

    if scope == "explicit_only":
        if schema_ver:
            facts = schema_repo.list_schema_facts(
                conn,
                project_id,
                schema_ver=schema_ver,
                layer=SchemaLayer.EXPLICIT,
            )
        else:
            facts = schema_repo.list_schema_facts(
                conn,
                project_id,
                layer=SchemaLayer.EXPLICIT,
            )
        kept = [fact for fact in facts if fact.status is not FactStatus.REJECTED]
        return resolved_schema_ver, kept

    if not resolved_schema_ver:
        return "", []

    facts = schema_repo.list_schema_facts(
        conn,
        project_id,
        schema_ver=resolved_schema_ver,
        status=FactStatus.APPROVED,
    )
    return resolved_schema_ver, facts


def _build_fact_index(facts: list) -> dict[tuple[str, str | None], list]:
    indexed: dict[tuple[str, str | None], list] = {}
    for fact in facts:
        slot_key = _fact_slot_key(fact.tag_path)
        if slot_key is None:
            continue
        indexed.setdefault((slot_key, _FACT_ALL_KEY), []).append(fact)
        entity_id = fact.entity_id if isinstance(fact.entity_id, str) and fact.entity_id else None
        indexed.setdefault((slot_key, entity_id), []).append(fact)
    return indexed


def _judge_with_fact_index(
    slots: dict[str, object],
    fact_index: dict[tuple[str, str | None], list],
    *,
    target_entity_id: str | None,
    evidence_link_policy: str = "full",
    evidence_link_cap: int = _DEFAULT_EVIDENCE_LINK_CAP,
    comparison_cache: dict[tuple[str, str, str], Verdict | None] | None = None,
) -> tuple[Verdict | None, list[tuple[str, EvidenceRole]]]:
    if not slots:
        return None, []

    cap = max(1, int(evidence_link_cap))
    saw_ok = False
    saw_violate = False
    link_set: set[tuple[str, EvidenceRole]] = set()
    for slot_key, claimed_value in slots.items():
        if target_entity_id is None:
            candidates = fact_index.get((slot_key, _FACT_ALL_KEY), [])
        else:
            candidates = [
                *fact_index.get((slot_key, target_entity_id), []),
                *fact_index.get((slot_key, None), []),
            ]
        if not candidates:
            continue
        for fact in candidates:
            judged: Verdict | None
            cache_key = (slot_key, repr(claimed_value), repr(fact.value))
            if comparison_cache is None:
                judged = _compare_slot(slot_key, claimed_value, fact.value)
            else:
                if cache_key not in comparison_cache:
                    comparison_cache[cache_key] = _compare_slot(slot_key, claimed_value, fact.value)
                judged = comparison_cache[cache_key]
            if judged is None:
                continue
            if judged is Verdict.VIOLATE:
                saw_violate = True
                link_set.add((fact.evidence_eid, EvidenceRole.CONTRADICT))
            elif judged is Verdict.OK:
                saw_ok = True
                link_set.add((fact.evidence_eid, EvidenceRole.SUPPORT))
            if evidence_link_policy != "full" and saw_violate and len(link_set) >= cap:
                break
        if evidence_link_policy != "full" and saw_violate and len(link_set) >= cap:
            break

    links = sorted(link_set, key=lambda item: (item[0], item[1].value))
    if saw_violate:
        return Verdict.VIOLATE, links
    if saw_ok:
        return Verdict.OK, links
    return None, []


def _claim_cache_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def _resolve_evidence_link_options(req: ConsistencyRequest) -> tuple[str, int]:
    policy_raw = req.get("evidence_link_policy")
    if isinstance(policy_raw, str):
        policy = policy_raw.strip().lower()
    else:
        policy = "full"
    if policy not in _ALLOWED_EVIDENCE_LINK_POLICIES:
        policy = "full"
    cap_raw = req.get("evidence_link_cap")
    try:
        cap = int(cap_raw) if cap_raw is not None else _DEFAULT_EVIDENCE_LINK_CAP
    except (TypeError, ValueError):
        cap = _DEFAULT_EVIDENCE_LINK_CAP
    return policy, max(1, cap)


def _resolve_self_evidence_options(req: ConsistencyRequest) -> tuple[bool, str]:
    raw_exclude = req.get("exclude_self_evidence")
    exclude = True if raw_exclude is None else bool(raw_exclude)
    raw_scope = req.get("self_evidence_scope")
    scope = str(raw_scope).strip().lower() if isinstance(raw_scope, str) else _DEFAULT_SELF_EVIDENCE_SCOPE
    if scope not in {"range", "doc"}:
        scope = _DEFAULT_SELF_EVIDENCE_SCOPE
    return exclude, scope


def _resolve_graph_expand_options(req: ConsistencyRequest) -> tuple[bool, int, int]:
    enabled = bool(req.get("graph_expand_enabled", False))
    max_hops_raw = req.get("graph_max_hops")
    doc_cap_raw = req.get("graph_doc_cap")
    try:
        max_hops = int(max_hops_raw) if max_hops_raw is not None else 1
    except (TypeError, ValueError):
        max_hops = 1
    if max_hops not in {1, 2}:
        max_hops = 1
    try:
        doc_cap = int(doc_cap_raw) if doc_cap_raw is not None else _DEFAULT_GRAPH_DOC_CAP
    except (TypeError, ValueError):
        doc_cap = _DEFAULT_GRAPH_DOC_CAP
    return enabled, max_hops, max(1, doc_cap)


def _spans_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def _result_identity(result: dict[str, Any]) -> str:
    evidence = result.get("evidence") or {}
    chunk_id = evidence.get("chunk_id")
    if isinstance(chunk_id, str) and chunk_id:
        return f"chunk:{chunk_id}"
    doc_id = evidence.get("doc_id")
    span_start = evidence.get("span_start")
    span_end = evidence.get("span_end")
    return f"doc:{doc_id}|span:{span_start}:{span_end}"


def _merge_result_lists(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*primary, *secondary]:
        key = _result_identity(row)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged


def _filter_self_evidence_results(
    results: list[dict[str, Any]],
    *,
    input_doc_id: str,
    scope: str,
    claim_abs_start: int,
    claim_abs_end: int,
    range_start: int | None,
    range_end: int | None,
) -> tuple[list[dict[str, Any]], int]:
    if not results:
        return [], 0
    filtered: list[dict[str, Any]] = []
    removed = 0
    target_start = claim_abs_start
    target_end = claim_abs_end
    if scope == "range" and range_start is not None and range_end is not None and range_start < range_end:
        target_start = range_start
        target_end = range_end
    for row in results:
        evidence = row.get("evidence") or {}
        doc_id = evidence.get("doc_id")
        if not isinstance(doc_id, str) or doc_id != input_doc_id:
            filtered.append(row)
            continue
        if scope == "doc":
            removed += 1
            continue
        try:
            ev_start = int(evidence.get("span_start", 0))
            ev_end = int(evidence.get("span_end", 0))
        except (TypeError, ValueError):
            filtered.append(row)
            continue
        if ev_end <= ev_start:
            filtered.append(row)
            continue
        if _spans_overlap(ev_start, ev_end, target_start, target_end):
            removed += 1
            continue
        filtered.append(row)
    return filtered, removed


def _build_verdict_links(
    *,
    verdict_id: str,
    evidences: list[Any],
    fact_links: list[tuple[str, EvidenceRole]],
    policy: str,
    cap: int,
) -> list[VerdictEvidenceLink]:
    cap_value = max(1, int(cap))
    dedup: set[tuple[str, EvidenceRole]] = set()
    links: list[VerdictEvidenceLink] = []

    def append_link(eid: str, role: EvidenceRole) -> bool:
        key = (eid, role)
        if key in dedup:
            return False
        dedup.add(key)
        links.append(VerdictEvidenceLink(vid=verdict_id, eid=eid, role=role))
        return True

    policy_name = policy if policy in _ALLOWED_EVIDENCE_LINK_POLICIES else "full"
    if policy_name == "contradict_only":
        for eid, role in fact_links:
            if role is not EvidenceRole.CONTRADICT:
                continue
            append_link(eid, role)
            if len(links) >= cap_value:
                break
        return links

    if policy_name == "cap":
        for evidence in evidences:
            append_link(evidence.eid, EvidenceRole.SUPPORT)
            if len(links) >= cap_value:
                return links
        for eid, role in fact_links:
            append_link(eid, role)
            if len(links) >= cap_value:
                return links
        return links

    for evidence in evidences:
        append_link(evidence.eid, EvidenceRole.SUPPORT)
    for eid, role in fact_links:
        append_link(eid, role)
    return links


class ConsistencyEngineImpl:
    def __init__(self, *, db_path=None) -> None:
        self._db_path = db_path

    def run(self, req: ConsistencyRequest) -> list[VerdictLog]:
        project_id = req.get("project_id")
        doc_id = req.get("input_doc_id")
        snapshot_id = req.get("input_snapshot_id")
        range_info = req.get("range") or {}
        schema_scope = _resolve_schema_scope(req)
        evidence_link_policy, evidence_link_cap = _resolve_evidence_link_options(req)
        exclude_self_evidence, self_evidence_scope = _resolve_self_evidence_options(req)
        graph_expand_enabled, graph_max_hops, graph_doc_cap = _resolve_graph_expand_options(req)
        retrieval_filters = _normalize_consistency_filters(req.get("filters"))
        metadata_filter_requested = bool(retrieval_filters)
        stats_raw = req.get("stats")
        req_stats = stats_raw if isinstance(stats_raw, dict) else None
        if req_stats is not None:
            req_stats.setdefault("claims_processed", 0)
            req_stats.setdefault("chunks_processed", 0)
            req_stats.setdefault("rows_scanned", 0)
            req_stats.setdefault("shards_loaded", 0)
            req_stats.setdefault("rule_eval_ms", 0.0)
            req_stats.setdefault("model_eval_ms", 0.0)
            req_stats.setdefault("slot_matches", 0)
            req_stats.setdefault("self_evidence_filtered_count", 0)
            req_stats.setdefault("graph_expand_applied_count", 0)
            req_stats.setdefault("graph_expand_candidate_docs", 0)
            req_stats.setdefault("graph_expand_refill_results", 0)

        if not isinstance(project_id, str) or not isinstance(doc_id, str) or not isinstance(snapshot_id, str):
            raise RuntimeError("invalid consistency request")

        with db.connect(self._db_path) as conn:
            snapshot = document_repo.get_snapshot(conn, snapshot_id)
            if snapshot is None:
                raise RuntimeError("snapshot not found")

            schema_ver_req = req.get("schema_ver")
            schema_ver, facts = _load_facts_for_scope(
                conn,
                project_id=project_id,
                schema_ver=schema_ver_req if isinstance(schema_ver_req, str) else None,
                scope=schema_scope,
            )

            entities = schema_repo.list_entities(conn, project_id)
            aliases = []
            for entity in entities:
                aliases.extend(schema_repo.list_entity_aliases(conn, project_id, entity.entity_id))
            alias_index = build_alias_index(entities, aliases)

            text = docstore.read_text(snapshot.path)
            offset = 0
            range_start: int | None = None
            range_end: int | None = None
            if isinstance(range_info, dict):
                start = range_info.get("start")
                end = range_info.get("end")
                if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
                    text = text[start:end]
                    offset = start
                    range_start = start
                    range_end = end

            settings = load_config()
            gateway = select_model(purpose="consistency")
            extraction_profile = normalize_extraction_profile(req.get("extraction"))
            extraction_mappings: list[ExtractorMapping] = []
            if extraction_profile.get("use_user_mappings", True):
                raw_mappings = schema_repo.list_extraction_mappings(conn, project_id, enabled_only=True)
                extraction_mappings = [
                    ExtractorMapping(
                        mapping_id=item.mapping_id,
                        project_id=item.project_id,
                        slot_key=item.slot_key,
                        pattern=item.pattern,
                        flags=item.flags,
                        transform=item.transform,
                        priority=item.priority,
                        enabled=item.enabled,
                        created_by=item.created_by,
                        created_at=item.created_at,
                    )
                    for item in raw_mappings
                ]
            extractor_pipeline = ExtractionPipeline(
                profile=extraction_profile,
                mappings=extraction_mappings,
                gateway=gateway,
            )
            if req_stats is not None:
                req_stats["extractor_profile"] = extractor_pipeline.profile["mode"]
                req_stats["extractor_version"] = extractor_pipeline.version
                req_stats["ruleset_checksum"] = extractor_pipeline.ruleset_checksum
                req_stats["mapping_checksum"] = extractor_pipeline.mapping_checksum
            claims = _extract_claims(text, pipeline=extractor_pipeline, stats=req_stats)
            fact_index = _build_fact_index(facts)
            project_doc_ids_for_vector: list[str] | None = None
            retrieval_cache: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
            retrieval_cache_size = 256
            slot_compare_cache: dict[tuple[str, str, str], Verdict | None] = {}

            verdicts: list[VerdictLog] = []
            for span_start, span_end, claim_text, slots in claims:
                if req_stats is not None:
                    req_stats["claims_processed"] = int(req_stats.get("claims_processed", 0)) + 1
                fingerprint = _fingerprint(claim_text)
                if ignore_repo.is_ignored(
                    conn,
                    project_id,
                    fingerprint,
                    scope=doc_id,
                    kind="CONSISTENCY",
                ):
                    continue
                if whitelist_repo.is_whitelisted(conn, project_id, fingerprint, scope=doc_id):
                    continue

                retrieval_stats: dict[str, Any] = {
                    "chunks_processed": 0,
                    "rows_scanned": 0,
                    "shards_loaded": 0,
                }
                claim_abs_start = span_start + offset
                claim_abs_end = span_end + offset
                cache_key = _claim_cache_key(claim_text)
                cached_results = retrieval_cache.get(cache_key)
                if cached_results is not None:
                    retrieval_cache.move_to_end(cache_key)
                    results = list(cached_results)
                else:
                    retrieval_req: dict[str, Any] = {
                        "project_id": project_id,
                        "query": claim_text,
                        "filters": dict(retrieval_filters),
                        "k": 3,
                        "stats": retrieval_stats,
                    }
                    results = fts_search(conn, retrieval_req)
                    if (
                        not results
                        and settings.vector_index_mode.upper() != "DISABLED"
                        and not metadata_filter_requested
                    ):
                        if project_doc_ids_for_vector is None:
                            project_docs = document_repo.list_documents(conn, project_id)
                            project_doc_ids_for_vector = [item.doc_id for item in project_docs]
                        vector_filters = dict(retrieval_filters)
                        vector_filters["doc_ids"] = project_doc_ids_for_vector
                        vector_req: dict[str, Any] = {
                            "project_id": project_id,
                            "query": claim_text,
                            "filters": vector_filters,
                            "k": 3,
                            "stats": retrieval_stats,
                        }
                        results = vector_search(vector_req)
                    if graph_expand_enabled:
                        candidate_doc_ids, graph_meta = expand_candidate_docs_with_graph(
                            conn,
                            project_id=project_id,
                            query=claim_text,
                            filters=dict(retrieval_filters),
                            max_hops=graph_max_hops,
                            doc_cap=graph_doc_cap,
                        )
                        if graph_meta.get("applied"):
                            if req_stats is not None:
                                req_stats["graph_expand_applied_count"] = int(
                                    req_stats.get("graph_expand_applied_count", 0)
                                ) + 1
                            if candidate_doc_ids:
                                graph_filters = dict(retrieval_filters)
                                graph_filters["doc_ids"] = candidate_doc_ids
                                graph_req: dict[str, Any] = {
                                    "project_id": project_id,
                                    "query": claim_text,
                                    "filters": graph_filters,
                                    "k": 3,
                                    "stats": retrieval_stats,
                                }
                                graph_results = fts_search(conn, graph_req)
                                if req_stats is not None:
                                    req_stats["graph_expand_candidate_docs"] = int(
                                        req_stats.get("graph_expand_candidate_docs", 0)
                                    ) + len(candidate_doc_ids)
                                    req_stats["graph_expand_refill_results"] = int(
                                        req_stats.get("graph_expand_refill_results", 0)
                                    ) + len(graph_results)
                                results = _merge_result_lists(results, graph_results, limit=3)
                    retrieval_cache[cache_key] = results
                    retrieval_cache.move_to_end(cache_key)
                    while len(retrieval_cache) > retrieval_cache_size:
                        retrieval_cache.popitem(last=False)
                if exclude_self_evidence:
                    results, filtered_count = _filter_self_evidence_results(
                        results,
                        input_doc_id=doc_id,
                        scope=self_evidence_scope,
                        claim_abs_start=claim_abs_start,
                        claim_abs_end=claim_abs_end,
                        range_start=range_start,
                        range_end=range_end,
                    )
                    if req_stats is not None and filtered_count > 0:
                        req_stats["self_evidence_filtered_count"] = int(
                            req_stats.get("self_evidence_filtered_count", 0)
                        ) + filtered_count
                if req_stats is not None:
                    req_stats["chunks_processed"] = int(req_stats.get("chunks_processed", 0)) + int(
                        retrieval_stats.get("chunks_processed", 0)
                    )
                    req_stats["rows_scanned"] = int(req_stats.get("rows_scanned", 0)) + int(
                        retrieval_stats.get("rows_scanned", 0)
                    )
                    req_stats["shards_loaded"] = int(req_stats.get("shards_loaded", 0)) + int(
                        retrieval_stats.get("shards_loaded", 0)
                    )

                evidences = []
                for result in results:
                    ev_raw = result.get("evidence") or {}
                    evidence = evidence_repo.new_evidence(
                        project_id=project_id,
                        doc_id=ev_raw.get("doc_id", ""),
                        snapshot_id=ev_raw.get("snapshot_id", ""),
                        chunk_id=ev_raw.get("chunk_id"),
                        section_path=ev_raw.get("section_path", ""),
                        tag_path=ev_raw.get("tag_path", ""),
                        snippet_text=ev_raw.get("snippet_text", ""),
                        span_start=int(ev_raw.get("span_start", 0)),
                        span_end=int(ev_raw.get("span_end", 0)),
                        fts_score=float(ev_raw.get("fts_score", 0.0)),
                        match_type=EvidenceMatchType(ev_raw.get("match_type", EvidenceMatchType.EXACT.value)),
                        confirmed=bool(ev_raw.get("confirmed", False)),
                    )
                    evidence_repo.create_evidence(conn, evidence, commit=False)
                    evidences.append(evidence)

                verdict = Verdict.UNKNOWN
                candidates = find_entity_candidates(claim_text, alias_index)
                ambiguous = len(candidates) > 1
                target_entity_id: str | None = None
                if len(candidates) == 1:
                    target_entity_id = next(iter(candidates))

                fact_links: list[tuple[str, EvidenceRole]] = []
                if fact_index:
                    judged, fact_links = _judge_with_fact_index(
                        slots,
                        fact_index,
                        target_entity_id=target_entity_id,
                        evidence_link_policy=evidence_link_policy,
                        evidence_link_cap=evidence_link_cap,
                        comparison_cache=slot_compare_cache,
                    )
                    if judged is not None:
                        verdict = judged
                if ambiguous:
                    verdict = Verdict.UNKNOWN

                # Enforce evidence contract: VIOLATE must keep CONTRADICT role.
                if verdict is Verdict.VIOLATE and not any(role is EvidenceRole.CONTRADICT for _, role in fact_links):
                    verdict = Verdict.UNKNOWN

                fts_strength = float(results[0]["score"]) if results else 0.0
                model_score = 0.0
                if settings.enable_layer3_model and verdict is Verdict.UNKNOWN and evidences:
                    model_score = gateway.nli_score(
                        {"claim_text": claim_text, "evidence": _bundle_evidence(evidences)}
                    )
                breakdown = ReliabilityBreakdown(
                    fts_strength=fts_strength,
                    evidence_count=len(evidences),
                    confirmed_evidence=len([e for e in evidences if e.confirmed]),
                    model_score=model_score,
                )
                reliability = min(0.6, breakdown.evidence_count / 3) if evidences else 0.0
                if verdict is Verdict.UNKNOWN:
                    reliability = 0.0
                whitelist_applied = whitelist_repo.is_whitelisted(conn, project_id, fingerprint, scope=doc_id)

                verdict_log = VerdictLog(
                    vid=str(uuid.uuid4()),
                    project_id=project_id,
                    input_doc_id=doc_id,
                    input_snapshot_id=snapshot_id,
                    schema_ver=schema_ver,
                    segment_span=Span(start=span_start + offset, end=span_end + offset),
                    claim_text=claim_text,
                    verdict=verdict,
                    reliability_overall=reliability,
                    breakdown=breakdown,
                    whitelist_applied=whitelist_applied,
                    created_at=_now_ts(),
                )
                evidence_repo.create_verdict_log(conn, verdict_log, commit=False)
                links = _build_verdict_links(
                    verdict_id=verdict_log.vid,
                    evidences=evidences,
                    fact_links=fact_links,
                    policy=evidence_link_policy,
                    cap=evidence_link_cap,
                )
                evidence_repo.create_verdict_links(conn, links, commit=False)
                verdicts.append(verdict_log)
            conn.commit()

        return verdicts


def evaluate_consistency(req: ConsistencyRequest | None = None, *, db_path=None) -> list[VerdictLog]:
    if req is None:
        return []
    engine = ConsistencyEngineImpl(db_path=db_path)
    return engine.run(req)
