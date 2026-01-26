from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

from modules.nf_consistency.contracts import ConsistencyRequest
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo, evidence_repo, schema_repo, whitelist_repo
from modules.nf_model_gateway.gateway import select_model
from modules.nf_retrieval.fts.fts_index import fts_search
from modules.nf_retrieval.vector.manifest import vector_search
from modules.nf_schema.identity import build_alias_index, find_entity_candidates
from modules.nf_shared.config import load_config
from modules.nf_shared.protocol.dtos import (
    EvidenceMatchType,
    EvidenceRole,
    FactStatus,
    ReliabilityBreakdown,
    Span,
    Verdict,
    VerdictEvidenceLink,
    VerdictLog,
)


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
    age_match = re.search(r"(\\d{1,3})\\s*살", segment)
    if age_match:
        slots["age"] = int(age_match.group(1))
    time_match = re.search(r"(\\d{1,2}:\\d{2}|\\d{4}년\\s*\\d{1,2}월\\s*\\d{1,2}일)", segment)
    if time_match:
        slots["time"] = time_match.group(1)
    place_match = re.search(r"(?:장소|위치)[:\\s]+([^\\n,.]+)", segment)
    if place_match:
        slots["place"] = place_match.group(1).strip()
    relation_match = re.search(r"(?:관계)[:\\s]+([^\\n,.]+)", segment)
    if relation_match:
        slots["relation"] = relation_match.group(1).strip()
    affiliation_match = re.search(r"(?:소속)[:\\s]+([^\\n,.]+)", segment)
    if affiliation_match:
        slots["affiliation"] = affiliation_match.group(1).strip()
    if re.search(r"(사망|죽었|죽었다|사망했다|사망함)", segment):
        slots["death"] = True
    return slots


def _extract_claims(text: str) -> list[tuple[int, int, str, dict[str, object]]]:
    segments = _segment_text(text)
    claims = []
    for span_start, span_end, segment in segments:
        slots = _extract_slots(segment)
        if slots:
            claims.append((span_start, span_end, segment, slots))
    if claims:
        return claims
    return [(span_start, span_end, segment, {}) for span_start, span_end, segment in segments]


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


class ConsistencyEngineImpl:
    def __init__(self, *, db_path=None) -> None:
        self._db_path = db_path

    def run(self, req: ConsistencyRequest) -> list[VerdictLog]:
        project_id = req.get("project_id")
        doc_id = req.get("input_doc_id")
        snapshot_id = req.get("input_snapshot_id")
        range_info = req.get("range") or {}

        if not isinstance(project_id, str) or not isinstance(doc_id, str) or not isinstance(snapshot_id, str):
            raise RuntimeError("invalid consistency request")

        with db.connect(self._db_path) as conn:
            snapshot = document_repo.get_snapshot(conn, snapshot_id)
            if snapshot is None:
                raise RuntimeError("snapshot not found")
            schema_ver = req.get("schema_ver")
            if not schema_ver:
                latest = schema_repo.get_latest_schema_version(conn, project_id)
                schema_ver = latest.schema_ver if latest else ""
            facts = []
            if schema_ver:
                facts = schema_repo.list_schema_facts(
                    conn,
                    project_id,
                    schema_ver=schema_ver,
                    status=FactStatus.APPROVED,
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
            verdicts: list[VerdictLog] = []
            for span_start, span_end, claim_text, _slots in claims:
                retrieval_req = {
                    "project_id": project_id,
                    "query": claim_text,
                    "filters": {},
                    "k": 3,
                }
                results = fts_search(conn, retrieval_req)
                if not results and settings.vector_index_mode.upper() != "DISABLED":
                    results = vector_search(retrieval_req)
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
                    evidence_repo.create_evidence(conn, evidence)
                    evidences.append(evidence)

                verdict = Verdict.OK if evidences else Verdict.UNKNOWN
                candidates = find_entity_candidates(claim_text, alias_index)
                ambiguous = len(candidates) > 1
                filtered_facts = facts
                if len(candidates) == 1:
                    target = next(iter(candidates))
                    filtered_facts = [fact for fact in facts if fact.entity_id in (None, target)]
                if evidences and filtered_facts:
                    verdict = _judge_with_facts(claim_text, filtered_facts) or verdict
                if ambiguous:
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
                whitelist_applied = whitelist_repo.is_whitelisted(conn, project_id, _fingerprint(claim_text))

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
                evidence_repo.create_verdict_log(conn, verdict_log)
                links = [
                    VerdictEvidenceLink(vid=verdict_log.vid, eid=e.eid, role=EvidenceRole.SUPPORT)
                    for e in evidences
                ]
                evidence_repo.create_verdict_links(conn, links)
                verdicts.append(verdict_log)

        return verdicts


def _judge_with_facts(claim_text: str, facts: list) -> Verdict | None:
    numbers = re.findall(r"\\d+", claim_text)
    for fact in facts:
        value = fact.value
        tag_tail = fact.tag_path.split("/")[-1]
        if numbers and isinstance(value, (int, float)) and tag_tail in claim_text:
            try:
                claimed = int(numbers[0])
            except ValueError:
                continue
            if claimed != int(value):
                return Verdict.VIOLATE
            return Verdict.OK
        if isinstance(value, str) and value and value in claim_text:
            return Verdict.OK
    return None


def evaluate_consistency(req: ConsistencyRequest | None = None, *, db_path=None) -> list[VerdictLog]:
    if req is None:
        return []
    engine = ConsistencyEngineImpl(db_path=db_path)
    return engine.run(req)
