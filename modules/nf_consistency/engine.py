from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from modules.nf_consistency.contracts import ConsistencyRequest
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

_AGE_RE = re.compile(r"(\d{1,3})\s*(?:살|세)")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{1,2}월\s*\d{1,2}일)")
_PLACE_RE = re.compile(r"(?:장소|위치)[:\s]+([^\n,.]+)")
_REL_RE = re.compile(r"(?:관계)[:\s]+([^\n,.]+)")
_AFFIL_RE = re.compile(r"(?:소속)[:\s]+([^\n,.]+)")
_JOB_RE = re.compile(r"(?:직업|클래스)[:\s]+([^\n,.]+)")
_TALENT_RE = re.compile(r"(?:재능)[:\s]+([^\n,.]+)")
_DEATH_RE = re.compile(r"(사망|죽었|죽었다|사망했다|사망함)")
_ALIVE_RE = re.compile(r"(생존|살아있)")
_JOB_FALLBACK_RE = re.compile(r"(\d+\s*서클\s*마법사)")
_NO_TALENT_RE = re.compile(r"재능\s*없(?:음|다)")


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


def _extract_slots(segment: str) -> dict[str, object]:
    slots: dict[str, object] = {}

    age_match = _AGE_RE.search(segment)
    if age_match:
        slots["age"] = int(age_match.group(1))

    time_match = _TIME_RE.search(segment)
    if time_match:
        slots["time"] = time_match.group(1)

    place_match = _PLACE_RE.search(segment)
    if place_match:
        slots["place"] = place_match.group(1).strip()

    relation_match = _REL_RE.search(segment)
    if relation_match:
        slots["relation"] = relation_match.group(1).strip()

    affiliation_match = _AFFIL_RE.search(segment)
    if affiliation_match:
        slots["affiliation"] = affiliation_match.group(1).strip()

    job_match = _JOB_RE.search(segment)
    if job_match:
        slots["job"] = job_match.group(1).strip()
    elif "노 클래스" in segment:
        slots["job"] = "노 클래스"
    else:
        circle_match = _JOB_FALLBACK_RE.search(segment)
        if circle_match:
            slots["job"] = circle_match.group(1)

    talent_match = _TALENT_RE.search(segment)
    if talent_match:
        slots["talent"] = talent_match.group(1).strip()
    elif _NO_TALENT_RE.search(segment):
        slots["talent"] = "재능 없음"
    elif "천재" in segment:
        slots["talent"] = "천재"

    if _DEATH_RE.search(segment):
        slots["death"] = True
    elif _ALIVE_RE.search(segment):
        slots["death"] = False

    return slots


def _extract_claims(text: str) -> list[tuple[int, int, str, dict[str, object]]]:
    claims = []
    for span_start, span_end, segment in _segment_text(text):
        slots = _extract_slots(segment)
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


def _judge_with_facts(slots: dict[str, object], facts: list) -> tuple[Verdict | None, list[tuple[str, EvidenceRole]]]:
    if not slots:
        return None, []

    saw_ok = False
    saw_violate = False
    link_set: set[tuple[str, EvidenceRole]] = set()
    for fact in facts:
        slot_key = _fact_slot_key(fact.tag_path)
        if slot_key is None or slot_key not in slots:
            continue
        judged = _compare_slot(slot_key, slots[slot_key], fact.value)
        if judged is None:
            continue
        if judged is Verdict.VIOLATE:
            saw_violate = True
            link_set.add((fact.evidence_eid, EvidenceRole.CONTRADICT))
        elif judged is Verdict.OK:
            saw_ok = True
            link_set.add((fact.evidence_eid, EvidenceRole.SUPPORT))

    links = sorted(link_set, key=lambda item: (item[0], item[1].value))
    if saw_violate:
        return Verdict.VIOLATE, links
    if saw_ok:
        return Verdict.OK, links
    return None, []


class ConsistencyEngineImpl:
    def __init__(self, *, db_path=None) -> None:
        self._db_path = db_path

    def run(self, req: ConsistencyRequest) -> list[VerdictLog]:
        project_id = req.get("project_id")
        doc_id = req.get("input_doc_id")
        snapshot_id = req.get("input_snapshot_id")
        range_info = req.get("range") or {}
        schema_scope = _resolve_schema_scope(req)
        stats_raw = req.get("stats")
        req_stats = stats_raw if isinstance(stats_raw, dict) else None
        if req_stats is not None:
            req_stats.setdefault("claims_processed", 0)
            req_stats.setdefault("chunks_processed", 0)
            req_stats.setdefault("rows_scanned", 0)
            req_stats.setdefault("shards_loaded", 0)

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
            if isinstance(range_info, dict):
                start = range_info.get("start")
                end = range_info.get("end")
                if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
                    text = text[start:end]
                    offset = start

            settings = load_config()
            gateway = select_model(purpose="consistency")
            claims = _extract_claims(text)
            project_docs = document_repo.list_documents(conn, project_id)
            project_doc_ids = [item.doc_id for item in project_docs]
            project_snapshot_ids = [item.head_snapshot_id for item in project_docs]

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

                retrieval_req: dict[str, Any] = {
                    "project_id": project_id,
                    "query": claim_text,
                    "filters": {
                        "doc_ids": project_doc_ids,
                        "snapshot_ids": project_snapshot_ids,
                    },
                    "k": 3,
                }
                retrieval_stats: dict[str, Any] = {}
                retrieval_req["stats"] = retrieval_stats

                results = fts_search(conn, retrieval_req)
                if not results and settings.vector_index_mode.upper() != "DISABLED":
                    results = vector_search(retrieval_req)
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
                filtered_facts = facts
                if len(candidates) == 1:
                    target = next(iter(candidates))
                    filtered_facts = [fact for fact in facts if fact.entity_id in (None, target)]

                fact_links: list[tuple[str, EvidenceRole]] = []
                if filtered_facts:
                    judged, fact_links = _judge_with_facts(slots, filtered_facts)
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
                links: list[VerdictEvidenceLink] = [
                    VerdictEvidenceLink(vid=verdict_log.vid, eid=e.eid, role=EvidenceRole.SUPPORT)
                    for e in evidences
                ]
                for eid, role in fact_links:
                    links.append(VerdictEvidenceLink(vid=verdict_log.vid, eid=eid, role=role))
                evidence_repo.create_verdict_links(conn, links, commit=False)
                verdicts.append(verdict_log)
            conn.commit()

        return verdicts


def evaluate_consistency(req: ConsistencyRequest | None = None, *, db_path=None) -> list[VerdictLog]:
    if req is None:
        return []
    engine = ConsistencyEngineImpl(db_path=db_path)
    return engine.run(req)
