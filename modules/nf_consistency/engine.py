from __future__ import annotations

import hashlib
import json
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
    FactSource,
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
_DEFAULT_LAYER3_MIN_FTS_FOR_PROMOTION = 0.25
_DEFAULT_LAYER3_MAX_CLAIM_CHARS = 260
_DEFAULT_LAYER3_OK_THRESHOLD = 0.88
_CANDIDATE_K = 12
_FINAL_K = 3
_VECTOR_REFILL_MIN = 6
_NLI_RERANK_TOP_N = 8
_RETRIEVAL_CACHE_SIZE = 256
_UNKNOWN_REASON_NO_EVIDENCE = "NO_EVIDENCE"
_UNKNOWN_REASON_AMBIGUOUS_ENTITY = "AMBIGUOUS_ENTITY"
_UNKNOWN_REASON_SLOT_UNCOMPARABLE = "SLOT_UNCOMPARABLE"
_UNKNOWN_REASON_CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"

_STRING_SLOT_KEYS = {"time", "place", "relation", "affiliation", "job", "talent"}
_SLOT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "age": ("\ub098\uc774", "\uc5f0\ub839", "age"),
    "time": ("\uc2dc\uac04", "\uc2dc\uc810", "\ub0a0\uc9dc", "\uc77c\uc2dc", "time", "date"),
    "place": ("\uc7a5\uc18c", "\uc704\uce58", "place", "location"),
    "relation": ("\uad00\uacc4", "relation"),
    "affiliation": ("\uc18c\uc18d", "affiliation"),
    "death": ("\uc0ac\ub9dd", "\uc0dd\uc874", "death", "alive"),
    "job": ("\uc9c1\uc5c5", "\ud074\ub798\uc2a4", "job", "class"),
    "talent": ("\uc7ac\ub2a5", "\ud2b9\uae30", "talent"),
}
_SCHEMA_TYPE_SLOT_KEYS: dict[str, str] = {
    "int": "age",
    "time": "time",
    "loc": "place",
    "rel": "relation",
    "bool": "death",
}
_SENTENCE_END_CHARS = {".", "!", "?", "\n", "\u3002", "\uff01", "\uff1f", "\u2026", "\uff0e"}
_SENTENCE_TAIL_CHARS = {
    ".",
    "\u2026",
    "'",
    '"',
    ")",
    "]",
    "}",
    "\u2019",
    "\u201d",
    "\u300d",
    "\u300f",
    "\u300b",
}
_STRING_EQUIVALENTS = {
    "\uc655\uad81": "\uad81",
    "\uc775\uc77c": "\ub2e4\uc74c\ub0a0",
    "tomorrow": "nextday",
}
_KO_POSTPOSITIONS = (
    "\uc73c\ub85c\uc11c",
    "\uc73c\ub85c\uc368",
    "\uc5d0\uac8c\uc11c",
    "\ud55c\ud14c\uc11c",
    "\uc5d0\uc11c\ub294",
    "\uc73c\ub85c\ub294",
    "\ub85c\ub294",
    "\uc5d0\uac8c\ub294",
    "\ud55c\ud14c\ub294",
    "\uae4c\uc9c0",
    "\ubd80\ud130",
    "\uc5d0\uc11c",
    "\uc5d0\uac8c",
    "\ud55c\ud14c",
    "\uc73c\ub85c",
    "\uc640",
    "\uacfc",
    "\uc740",
    "\ub294",
    "\uc774",
    "\uac00",
    "\uc744",
    "\ub97c",
    "\uc5d0",
    "\ub85c",
    "\ub3c4",
    "\ub9cc",
    "\uaed8",
)
_KO_PLACE_SUFFIXES = (
    "\ud2b9\ubcc4\uc790\uce58\uc2dc",
    "\ud2b9\ubcc4\uc790\uce58\ub3c4",
    "\ud2b9\ubcc4\uc2dc",
    "\uad11\uc5ed\uc2dc",
    "\uc790\uce58\uc2dc",
    "\uc790\uce58\ub3c4",
    "\uc2dc",
    "\ub3c4",
    "\uad70",
    "\uad6c",
    "\uc74d",
    "\uba74",
    "\ub3d9",
)
_SLOT_OK_SIMILARITY_THRESHOLD = 0.85
_SLOT_VIOLATE_SIMILARITY_THRESHOLD = 0.25


def _fingerprint(text: str) -> str:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int, str] | None:
    left = max(0, int(start))
    right = max(left, int(end))
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    if right <= left:
        return None
    return left, right, text[left:right]


def _segment_text(text: str) -> list[tuple[int, int, str]]:
    segments: list[tuple[int, int, str]] = []
    text_len = len(text)
    cursor = 0

    def append_segment(seg_start: int, seg_end: int) -> None:
        trimmed = _trimmed_span(text, seg_start, seg_end)
        if trimmed is None:
            return
        segments.append(trimmed)

    idx = 0
    while idx < text_len:
        ch = text[idx]
        if ch not in _SENTENCE_END_CHARS:
            idx += 1
            continue
        if ch == "." and 0 < idx < text_len - 1 and text[idx - 1].isdigit() and text[idx + 1].isdigit():
            idx += 1
            continue
        seg_end = idx
        if ch != "\n":
            seg_end = idx + 1
            while seg_end < text_len and text[seg_end] in _SENTENCE_TAIL_CHARS:
                seg_end += 1
        append_segment(cursor, seg_end)
        cursor = idx + 1 if ch == "\n" else seg_end
        idx = cursor
    append_segment(cursor, text_len)
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
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for segment_start, segment_end, segment_text in _segment_text(text):
        if pipeline is None:
            slots: dict[str, object] = {}
            candidates: list[Any] = []
            rule_eval_ms = 0.0
            model_eval_ms = 0.0
        else:
            result = pipeline.extract(segment_text)
            slots = result.slots
            candidates = list(result.candidates)
            rule_eval_ms = float(result.rule_eval_ms)
            model_eval_ms = float(result.model_eval_ms)
        if stats is not None:
            stats["rule_eval_ms"] = float(stats.get("rule_eval_ms", 0.0)) + rule_eval_ms
            stats["model_eval_ms"] = float(stats.get("model_eval_ms", 0.0)) + model_eval_ms
            stats["slot_matches"] = int(stats.get("slot_matches", 0)) + len(slots)
            stats["slot_candidate_count"] = int(stats.get("slot_candidate_count", 0)) + len(candidates)
        if not slots:
            continue

        best_by_slot: dict[str, Any] = {}
        for candidate in candidates:
            slot_key = getattr(candidate, "slot_key", None)
            if not isinstance(slot_key, str) or not slot_key:
                continue
            existing = best_by_slot.get(slot_key)
            if existing is None or float(getattr(candidate, "confidence", 0.0)) > float(
                getattr(existing, "confidence", 0.0)
            ):
                best_by_slot[slot_key] = candidate

        for slot_key, slot_value in slots.items():
            candidate = best_by_slot.get(slot_key)
            rel_start = 0
            rel_end = len(segment_text)
            confidence = 0.0
            if candidate is not None:
                confidence = float(getattr(candidate, "confidence", 0.0))
                try:
                    cand_start = int(getattr(candidate, "span_start", 0))
                    cand_end = int(getattr(candidate, "span_end", 0))
                except (TypeError, ValueError):
                    cand_start = 0
                    cand_end = 0
                cand_start = max(0, min(len(segment_text), cand_start))
                cand_end = max(cand_start, min(len(segment_text), cand_end))
                if cand_end > cand_start:
                    rel_start = cand_start
                    rel_end = cand_end

            claim_start = segment_start + rel_start
            claim_end = segment_start + rel_end
            claim_piece = _trimmed_span(text, claim_start, claim_end)
            if claim_piece is None:
                claim_start = segment_start
                claim_end = segment_end
                claim_text = segment_text
            else:
                claim_start, claim_end, claim_text = claim_piece

            claims.append(
                {
                    "segment_start": segment_start,
                    "segment_end": segment_end,
                    "segment_text": segment_text,
                    "claim_start": claim_start,
                    "claim_end": claim_end,
                    "claim_text": claim_text,
                    "slots": {slot_key: slot_value},
                    "slot_key": slot_key,
                    "slot_confidence": confidence,
                }
            )
            if stats is not None:
                stats["slot_candidate_selected"] = int(stats.get("slot_candidate_selected", 0)) + 1
                stats["slot_candidate_conf_sum"] = float(stats.get("slot_candidate_conf_sum", 0.0)) + confidence
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


def _bundle_result_rows(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    bundled: list[dict[str, object]] = []
    for row in rows:
        evidence = row.get("evidence") or {}
        bundled.append(
            {
                "doc_id": str(evidence.get("doc_id", "")),
                "snapshot_id": str(evidence.get("snapshot_id", "")),
                "chunk_id": evidence.get("chunk_id"),
                "section_path": str(evidence.get("section_path", "")),
                "tag_path": str(evidence.get("tag_path", "")),
                "snippet_text": str(evidence.get("snippet_text", "")),
                "span_start": int(evidence.get("span_start", 0)),
                "span_end": int(evidence.get("span_end", 0)),
                "match_type": str(evidence.get("match_type", EvidenceMatchType.FUZZY.value)),
                "confirmed": bool(evidence.get("confirmed", False)),
            }
        )
    return bundled


def _normalize_slot_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {
        "age",
        "time",
        "place",
        "relation",
        "affiliation",
        "job",
        "talent",
        "death",
    }:
        return normalized
    return None


def _slot_key_from_constraints(constraints: Any) -> str | None:
    if not hasattr(constraints, "get"):
        return None
    raw = constraints.get("slot_key")
    return _normalize_slot_key(raw)


def _slot_key_from_schema_type(schema_type: Any) -> str | None:
    raw = getattr(schema_type, "value", schema_type)
    if not isinstance(raw, str):
        return None
    return _SCHEMA_TYPE_SLOT_KEYS.get(raw.strip().lower())


def _legacy_fact_slot_key(tag_path: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", tag_path or "").lower()
    for slot_key, keywords in _SLOT_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return slot_key
    return None


def _fact_slot_key(tag_path: str, *, tag_def: Any | None = None) -> str | None:
    if tag_def is not None:
        slot_key = _slot_key_from_constraints(getattr(tag_def, "constraints", {}))
        if slot_key is not None:
            return slot_key
        slot_key = _slot_key_from_schema_type(getattr(tag_def, "schema_type", None))
        if slot_key is not None:
            return slot_key
    return _legacy_fact_slot_key(tag_path)


def _norm_text(value: object) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().lower()


def _strip_trailing_suffix_once(text: str, suffixes: tuple[str, ...]) -> str:
    for suffix in sorted(suffixes, key=len, reverse=True):
        if not suffix:
            continue
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _normalize_slot_text(value: object, *, slot_key: str | None = None) -> str:
    text = _norm_text(value)
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    compact = compact.replace("'", "").replace('"', "")
    for src, dst in _STRING_EQUIVALENTS.items():
        compact = compact.replace(src, dst)
    compact = _strip_trailing_suffix_once(compact, _KO_POSTPOSITIONS)
    if slot_key == "place":
        compact = _strip_trailing_suffix_once(compact, _KO_PLACE_SUFFIXES)
    return compact


def _tokenize_slot_text(value: object, *, slot_key: str | None = None) -> set[str]:
    text = _norm_text(value)
    if not text:
        return set()
    tokens = re.split(r"[\s,./;:()\[\]{}<>|]+", text)
    cleaned: set[str] = set()
    for token in tokens:
        if not token:
            continue
        reduced = re.sub(r"[^0-9a-zA-Z\uac00-\ud7a3]+", "", token)
        reduced = _strip_trailing_suffix_once(reduced, _KO_POSTPOSITIONS)
        if slot_key == "place":
            reduced = _strip_trailing_suffix_once(reduced, _KO_PLACE_SUFFIXES)
        if reduced:
            cleaned.add(reduced)
    return cleaned


def _token_overlap_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = left.intersection(right)
    if not overlap:
        return 0.0
    return float(len(overlap)) / float(max(1, min(len(left), len(right))))


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
    true_values = {"1", "true", "yes", "\uc0ac\ub9dd", "\uc8fd\uc74c", "\uc8fd\uc5c8\ub2e4", "\uc0ac\ub9dd\ud568"}
    false_values = {"0", "false", "no", "\uc0dd\uc874", "\uc0b4\uc544\uc788\ub2e4", "\uc0b4\uc544\uc788\uc74c"}
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

    if slot_key in _STRING_SLOT_KEYS:
        claimed = _normalize_slot_text(claimed_value, slot_key=slot_key)
        expected = _normalize_slot_text(fact_value, slot_key=slot_key)
        if not claimed or not expected:
            return None
        if claimed == expected or claimed in expected or expected in claimed:
            return Verdict.OK

        claimed_tokens = _tokenize_slot_text(claimed_value, slot_key=slot_key)
        expected_tokens = _tokenize_slot_text(fact_value, slot_key=slot_key)
        similarity = _token_overlap_similarity(claimed_tokens, expected_tokens)
        if similarity >= _SLOT_OK_SIMILARITY_THRESHOLD:
            return Verdict.OK

        claimed_num = _coerce_int(claimed_value)
        expected_num = _coerce_int(fact_value)
        numeric_mismatch = claimed_num is not None and expected_num is not None and claimed_num != expected_num

        if numeric_mismatch and similarity <= _SLOT_VIOLATE_SIMILARITY_THRESHOLD:
            return Verdict.VIOLATE
        if (
            similarity <= _SLOT_VIOLATE_SIMILARITY_THRESHOLD
            and len(claimed_tokens) == 1
            and len(expected_tokens) == 1
            and claimed_tokens != expected_tokens
        ):
            return Verdict.VIOLATE
        if (
            similarity <= _SLOT_VIOLATE_SIMILARITY_THRESHOLD
            and not claimed_tokens.intersection(expected_tokens)
            and (len(claimed_tokens) == 1 or len(expected_tokens) == 1)
        ):
            return Verdict.VIOLATE
        return None

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


def _build_fact_index(
    facts: list,
    *,
    tag_defs: list[Any] | None = None,
) -> dict[tuple[str, str | None], list]:
    indexed: dict[tuple[str, str | None], list] = {}
    tag_def_by_path: dict[str, Any] = {}
    for tag_def in tag_defs or []:
        tag_path = getattr(tag_def, "tag_path", None)
        if isinstance(tag_path, str) and tag_path:
            tag_def_by_path[tag_path] = tag_def

    for fact in facts:
        slot_key = _fact_slot_key(fact.tag_path, tag_def=tag_def_by_path.get(fact.tag_path))
        if slot_key is None:
            continue
        indexed.setdefault((slot_key, _FACT_ALL_KEY), []).append(fact)
        entity_id = fact.entity_id if isinstance(fact.entity_id, str) and fact.entity_id else None
        indexed.setdefault((slot_key, entity_id), []).append(fact)
    return indexed


def _resolve_excluded_self_fact_eids(
    conn,
    *,
    facts: list,
    input_doc_id: str,
) -> set[str]:
    if not input_doc_id:
        return set()
    candidate_eids = [
        fact.evidence_eid
        for fact in facts
        if getattr(fact, "source", None) is FactSource.AUTO
        and getattr(fact, "status", None) is FactStatus.PROPOSED
        and isinstance(getattr(fact, "evidence_eid", None), str)
        and fact.evidence_eid
    ]
    if not candidate_eids:
        return set()
    unique_eids = sorted(set(candidate_eids))
    excluded: set[str] = set()
    chunk_size = 200
    for start in range(0, len(unique_eids), chunk_size):
        chunk = unique_eids[start : start + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        rows = conn.execute(
            f"SELECT eid FROM evidence WHERE doc_id = ? AND eid IN ({placeholders})",
            [input_doc_id, *chunk],
        ).fetchall()
        for row in rows:
            eid = row["eid"]
            if isinstance(eid, str) and eid:
                excluded.add(eid)
    return excluded


def _judge_with_fact_index(
    slots: dict[str, object],
    fact_index: dict[tuple[str, str | None], list],
    *,
    target_entity_id: str | None,
    evidence_link_policy: str = "full",
    evidence_link_cap: int = _DEFAULT_EVIDENCE_LINK_CAP,
    comparison_cache: dict[tuple[str, str, str], Verdict | None] | None = None,
    excluded_fact_eids: set[str] | None = None,
) -> tuple[Verdict | None, list[tuple[str, EvidenceRole]], dict[str, bool]]:
    meta = {
        "saw_ok": False,
        "saw_violate": False,
        "saw_uncomparable": False,
        "conflicting": False,
    }
    if not slots:
        return None, [], meta

    cap = max(1, int(evidence_link_cap))
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
            evidence_eid = getattr(fact, "evidence_eid", None)
            if excluded_fact_eids and isinstance(evidence_eid, str) and evidence_eid in excluded_fact_eids:
                continue
            judged: Verdict | None
            cache_key = (slot_key, repr(claimed_value), repr(fact.value))
            if comparison_cache is None:
                judged = _compare_slot(slot_key, claimed_value, fact.value)
            else:
                if cache_key not in comparison_cache:
                    comparison_cache[cache_key] = _compare_slot(slot_key, claimed_value, fact.value)
                judged = comparison_cache[cache_key]
            if judged is None:
                meta["saw_uncomparable"] = True
                continue
            if judged is Verdict.VIOLATE:
                meta["saw_violate"] = True
                link_set.add((fact.evidence_eid, EvidenceRole.CONTRADICT))
            elif judged is Verdict.OK:
                meta["saw_ok"] = True
                link_set.add((fact.evidence_eid, EvidenceRole.SUPPORT))
            if evidence_link_policy != "full" and meta["saw_violate"] and len(link_set) >= cap:
                break
        if evidence_link_policy != "full" and meta["saw_violate"] and len(link_set) >= cap:
            break

    links = sorted(link_set, key=lambda item: (item[0], item[1].value))
    if meta["saw_ok"] and meta["saw_violate"]:
        meta["conflicting"] = True
        return Verdict.UNKNOWN, links, meta
    if meta["saw_violate"]:
        return Verdict.VIOLATE, links, meta
    if meta["saw_ok"]:
        return Verdict.OK, links, meta
    return None, [], meta


def _claim_cache_key(text: str, *, filters: dict[str, object] | None = None) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    if not filters:
        return normalized
    payload = json.dumps(filters, ensure_ascii=False, sort_keys=True, default=str)
    return f"{normalized}|{payload}"


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


def _resolve_layer3_promotion_options(req: ConsistencyRequest) -> tuple[bool, float, int, float]:
    enabled = bool(req.get("layer3_verdict_promotion", False))

    min_fts_raw = req.get("layer3_min_fts_for_promotion")
    try:
        min_fts = float(min_fts_raw) if min_fts_raw is not None else _DEFAULT_LAYER3_MIN_FTS_FOR_PROMOTION
    except (TypeError, ValueError):
        min_fts = _DEFAULT_LAYER3_MIN_FTS_FOR_PROMOTION
    min_fts = _clamp01(min_fts)

    max_claim_chars_raw = req.get("layer3_max_claim_chars")
    try:
        max_claim_chars = int(max_claim_chars_raw) if max_claim_chars_raw is not None else _DEFAULT_LAYER3_MAX_CLAIM_CHARS
    except (TypeError, ValueError):
        max_claim_chars = _DEFAULT_LAYER3_MAX_CLAIM_CHARS
    max_claim_chars = max(1, max_claim_chars)

    ok_threshold_raw = req.get("layer3_ok_threshold")
    try:
        ok_threshold = float(ok_threshold_raw) if ok_threshold_raw is not None else _DEFAULT_LAYER3_OK_THRESHOLD
    except (TypeError, ValueError):
        ok_threshold = _DEFAULT_LAYER3_OK_THRESHOLD
    ok_threshold = _clamp01(ok_threshold)

    return enabled, min_fts, max_claim_chars, ok_threshold


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


def _result_doc_id(result: dict[str, Any]) -> str:
    evidence = result.get("evidence") or {}
    doc_id = evidence.get("doc_id")
    if isinstance(doc_id, str):
        return doc_id
    return ""


def _base_retrieval_score(result: dict[str, Any]) -> float:
    source = str(result.get("source", "")).lower()
    try:
        raw_score = float(result.get("score") or 0.0)
    except (TypeError, ValueError):
        raw_score = 0.0
    if source == "fts":
        return 1.0 / (1.0 + max(0.0, raw_score))
    return max(0.0, min(1.0, raw_score))


def _rerank_results_for_consistency(
    *,
    results: list[dict[str, Any]],
    claim_text: str,
    filters: dict[str, object],
    graph_doc_distances: dict[str, int],
    gateway: Any,
    enable_model: bool,
) -> tuple[list[dict[str, Any]], float]:
    if not results:
        return [], 0.0

    scored: list[tuple[dict[str, Any], float]] = []
    for idx, row in enumerate(results):
        rank_score = 1.0 / float(idx + 1)
        base_score = _base_retrieval_score(row)
        doc_id = _result_doc_id(row)
        graph_bonus = 0.0
        hop = graph_doc_distances.get(doc_id)
        if isinstance(hop, int):
            if hop <= 1:
                graph_bonus = 0.15
            elif hop == 2:
                graph_bonus = 0.08
        metadata_bonus = 0.05 if filters and str(row.get("source", "")).lower() == "fts" else 0.0
        score = (base_score * 0.60) + (rank_score * 0.25) + graph_bonus + metadata_bonus
        scored.append((row, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    max_nli = 0.0
    if enable_model and gateway is not None:
        nli_scores: dict[str, float] = {}
        for row, _cheap_score in scored[:_NLI_RERANK_TOP_N]:
            identity = _result_identity(row)
            try:
                nli_value = gateway.nli_score(
                    {
                        "claim_text": claim_text,
                        "evidence": _bundle_result_rows([row]),
                    }
                )
                nli_score = max(0.0, min(1.0, float(nli_value)))
            except Exception:  # noqa: BLE001
                nli_score = 0.0
            nli_scores[identity] = nli_score
            if nli_score > max_nli:
                max_nli = nli_score

        rescored: list[tuple[dict[str, Any], float]] = []
        for row, cheap_score in scored:
            nli_bonus = 0.2 * nli_scores.get(_result_identity(row), 0.0)
            rescored.append((row, cheap_score + nli_bonus))
        scored = rescored
        scored.sort(key=lambda item: item[1], reverse=True)

    return [row for row, _score in scored], max_nli


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


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _compute_reliability(
    *,
    verdict: Verdict,
    breakdown: ReliabilityBreakdown,
) -> tuple[float, float, float]:
    evidence_count = max(0, int(breakdown.evidence_count))
    confirmed = max(0, int(breakdown.confirmed_evidence))
    fts_component = 0.0
    if evidence_count > 0:
        fts_component = _clamp01(1.0 / (1.0 + max(0.0, float(breakdown.fts_strength))))
    evidence_count_component = _clamp01(evidence_count / float(_FINAL_K))
    confirmed_component = _clamp01(confirmed / float(max(1, evidence_count)))
    model_component = _clamp01(float(breakdown.model_score))
    evidence_confidence = _clamp01(
        (0.45 * evidence_count_component)
        + (0.25 * confirmed_component)
        + (0.20 * fts_component)
        + (0.10 * model_component)
    )
    if verdict is Verdict.UNKNOWN:
        decision_confidence = 0.05 if evidence_count == 0 else _clamp01(0.20 + (0.45 * evidence_confidence))
    elif verdict is Verdict.VIOLATE:
        decision_confidence = _clamp01(0.55 + (0.45 * evidence_confidence))
    else:
        decision_confidence = _clamp01(0.50 + (0.45 * evidence_confidence))
    reliability = _clamp01((0.65 * evidence_confidence) + (0.35 * decision_confidence))
    return reliability, evidence_confidence, decision_confidence


def _add_unknown_reasons(req_stats: dict[str, Any] | None, reasons: set[str]) -> None:
    if req_stats is None or not reasons:
        return
    bucket_raw = req_stats.get("unknown_reason_counts")
    if not isinstance(bucket_raw, dict):
        bucket_raw = {}
    for reason in sorted(reasons):
        bucket_raw[reason] = int(bucket_raw.get(reason, 0)) + 1
    req_stats["unknown_reason_counts"] = bucket_raw


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
        layer3_promotion_enabled, layer3_min_fts, layer3_max_claim_chars, layer3_ok_threshold = (
            _resolve_layer3_promotion_options(req)
        )
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
            req_stats.setdefault("slot_candidate_count", 0)
            req_stats.setdefault("slot_candidate_selected", 0)
            req_stats.setdefault("slot_candidate_conf_sum", 0.0)
            req_stats.setdefault("self_evidence_filtered_count", 0)
            req_stats.setdefault("graph_expand_applied_count", 0)
            req_stats.setdefault("graph_expand_candidate_docs", 0)
            req_stats.setdefault("graph_expand_refill_results", 0)
            req_stats.setdefault("unknown_reason_counts", {})
            req_stats.setdefault("evidence_confidence_sum", 0.0)
            req_stats.setdefault("decision_confidence_sum", 0.0)
            req_stats.setdefault("layer3_promoted_ok_count", 0)

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
            if req_stats is not None:
                selected = int(req_stats.get("slot_candidate_selected", 0))
                if selected > 0:
                    req_stats["avg_slot_confidence"] = float(req_stats.get("slot_candidate_conf_sum", 0.0)) / selected
            tag_defs = schema_repo.list_tag_defs(conn, project_id)
            fact_index = _build_fact_index(facts, tag_defs=tag_defs)
            excluded_self_fact_eids = _resolve_excluded_self_fact_eids(
                conn,
                facts=facts,
                input_doc_id=doc_id,
            )
            project_doc_ids_for_vector: list[str] | None = None
            retrieval_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
            slot_compare_cache: dict[tuple[str, str, str], Verdict | None] = {}

            verdicts: list[VerdictLog] = []
            for claim in claims:
                claim_text = str(claim["claim_text"])
                segment_text = str(claim["segment_text"])
                claim_start = int(claim["claim_start"])
                claim_end = int(claim["claim_end"])
                slots = dict(claim.get("slots") or {})
                if req_stats is not None:
                    req_stats["claims_processed"] = int(req_stats.get("claims_processed", 0)) + 1
                fingerprint = _fingerprint(claim_text)
                segment_fingerprint = _fingerprint(segment_text)
                if ignore_repo.is_ignored(
                    conn,
                    project_id,
                    fingerprint,
                    scope=doc_id,
                    kind="CONSISTENCY",
                ) or (
                    segment_fingerprint != fingerprint
                    and ignore_repo.is_ignored(
                        conn,
                        project_id,
                        segment_fingerprint,
                        scope=doc_id,
                        kind="CONSISTENCY",
                    )
                ):
                    continue
                if whitelist_repo.is_whitelisted(conn, project_id, fingerprint, scope=doc_id) or (
                    segment_fingerprint != fingerprint
                    and whitelist_repo.is_whitelisted(conn, project_id, segment_fingerprint, scope=doc_id)
                ):
                    continue

                retrieval_stats: dict[str, Any] = {
                    "chunks_processed": 0,
                    "rows_scanned": 0,
                    "shards_loaded": 0,
                }
                claim_abs_start = claim_start + offset
                claim_abs_end = claim_end + offset
                retrieval_query = segment_text or claim_text
                cache_key = _claim_cache_key(retrieval_query, filters=retrieval_filters)
                cached_results = retrieval_cache.get(cache_key)
                if cached_results is not None:
                    retrieval_cache.move_to_end(cache_key)
                    candidate_results = list(cached_results.get("results", []))
                    graph_doc_distances = dict(cached_results.get("graph_doc_distances", {}))
                else:
                    graph_doc_distances: dict[str, int] = {}
                    retrieval_req: dict[str, Any] = {
                        "project_id": project_id,
                        "query": retrieval_query,
                        "filters": dict(retrieval_filters),
                        "k": _CANDIDATE_K,
                        "stats": retrieval_stats,
                    }
                    candidate_results = fts_search(conn, retrieval_req)
                    if (
                        len(candidate_results) < _VECTOR_REFILL_MIN
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
                            "query": retrieval_query,
                            "filters": vector_filters,
                            "k": _CANDIDATE_K,
                            "stats": retrieval_stats,
                        }
                        vector_results = vector_search(vector_req)
                        candidate_results = _merge_result_lists(
                            candidate_results,
                            vector_results,
                            limit=_CANDIDATE_K * 3,
                        )
                    if graph_expand_enabled:
                        candidate_doc_ids, graph_meta = expand_candidate_docs_with_graph(
                            conn,
                            project_id=project_id,
                            query=retrieval_query,
                            filters=dict(retrieval_filters),
                            max_hops=graph_max_hops,
                            doc_cap=graph_doc_cap,
                        )
                        raw_distances = graph_meta.get("doc_distances")
                        if isinstance(raw_distances, dict):
                            for key, value in raw_distances.items():
                                if isinstance(key, str):
                                    try:
                                        graph_doc_distances[key] = int(value)
                                    except (TypeError, ValueError):
                                        continue
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
                                    "query": retrieval_query,
                                    "filters": graph_filters,
                                    "k": _CANDIDATE_K,
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
                                candidate_results = _merge_result_lists(
                                    candidate_results,
                                    graph_results,
                                    limit=_CANDIDATE_K * 3,
                                )
                    retrieval_cache[cache_key] = {
                        "results": list(candidate_results),
                        "graph_doc_distances": dict(graph_doc_distances),
                    }
                    retrieval_cache.move_to_end(cache_key)
                    while len(retrieval_cache) > _RETRIEVAL_CACHE_SIZE:
                        retrieval_cache.popitem(last=False)
                if exclude_self_evidence:
                    candidate_results, filtered_count = _filter_self_evidence_results(
                        candidate_results,
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
                reranked_results, rerank_model_score = _rerank_results_for_consistency(
                    results=candidate_results,
                    claim_text=claim_text,
                    filters=retrieval_filters,
                    graph_doc_distances=graph_doc_distances,
                    gateway=gateway,
                    enable_model=bool(settings.enable_layer3_model),
                )
                results = reranked_results[:_FINAL_K]
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
                unknown_reasons: set[str] = set()
                if not results:
                    unknown_reasons.add(_UNKNOWN_REASON_NO_EVIDENCE)

                candidates = find_entity_candidates(segment_text, alias_index)
                ambiguous = len(candidates) > 1
                target_entity_id: str | None = None
                if len(candidates) == 1:
                    target_entity_id = next(iter(candidates))

                fact_links: list[tuple[str, EvidenceRole]] = []
                judge_meta = {
                    "saw_ok": False,
                    "saw_violate": False,
                    "saw_uncomparable": False,
                    "conflicting": False,
                }
                if fact_index:
                    judged, fact_links, judge_meta = _judge_with_fact_index(
                        slots,
                        fact_index,
                        target_entity_id=target_entity_id,
                        evidence_link_policy=evidence_link_policy,
                        evidence_link_cap=evidence_link_cap,
                        comparison_cache=slot_compare_cache,
                        excluded_fact_eids=excluded_self_fact_eids,
                    )
                    if judged is not None:
                        verdict = judged
                    if judge_meta.get("saw_uncomparable"):
                        unknown_reasons.add(_UNKNOWN_REASON_SLOT_UNCOMPARABLE)
                    if judge_meta.get("conflicting"):
                        unknown_reasons.add(_UNKNOWN_REASON_CONFLICTING_EVIDENCE)
                if ambiguous:
                    verdict = Verdict.UNKNOWN
                    unknown_reasons.add(_UNKNOWN_REASON_AMBIGUOUS_ENTITY)

                # Enforce evidence contract: VIOLATE must keep CONTRADICT role.
                if verdict is Verdict.VIOLATE and not any(role is EvidenceRole.CONTRADICT for _, role in fact_links):
                    verdict = Verdict.UNKNOWN
                    unknown_reasons.add(_UNKNOWN_REASON_CONFLICTING_EVIDENCE)

                fts_strength = float(results[0]["score"]) if results else 0.0
                promotion_fts_strength = _base_retrieval_score(results[0]) if results else 0.0
                model_score = rerank_model_score if settings.enable_layer3_model else 0.0
                confirmed_evidence_count = len([e for e in evidences if e.confirmed])

                if (
                    verdict is Verdict.UNKNOWN
                    and settings.enable_layer3_model
                    and layer3_promotion_enabled
                    and evidences
                    and confirmed_evidence_count > 0
                    and promotion_fts_strength >= layer3_min_fts
                    and len(claim_text) <= layer3_max_claim_chars
                    and model_score >= layer3_ok_threshold
                ):
                    verdict = Verdict.OK
                    unknown_reasons.clear()
                    if req_stats is not None:
                        req_stats["layer3_promoted_ok_count"] = int(req_stats.get("layer3_promoted_ok_count", 0)) + 1

                if verdict is Verdict.UNKNOWN and not unknown_reasons:
                    if results:
                        unknown_reasons.add(_UNKNOWN_REASON_CONFLICTING_EVIDENCE)
                    else:
                        unknown_reasons.add(_UNKNOWN_REASON_NO_EVIDENCE)
                if verdict is not Verdict.UNKNOWN:
                    unknown_reasons.clear()
                _add_unknown_reasons(req_stats, unknown_reasons)

                breakdown = ReliabilityBreakdown(
                    fts_strength=fts_strength,
                    evidence_count=len(evidences),
                    confirmed_evidence=confirmed_evidence_count,
                    model_score=model_score,
                )
                reliability, evidence_confidence, decision_confidence = _compute_reliability(
                    verdict=verdict,
                    breakdown=breakdown,
                )
                if req_stats is not None:
                    req_stats["evidence_confidence_sum"] = float(req_stats.get("evidence_confidence_sum", 0.0)) + float(
                        evidence_confidence
                    )
                    req_stats["decision_confidence_sum"] = float(req_stats.get("decision_confidence_sum", 0.0)) + float(
                        decision_confidence
                    )
                whitelist_applied = whitelist_repo.is_whitelisted(conn, project_id, fingerprint, scope=doc_id) or (
                    segment_fingerprint != fingerprint
                    and whitelist_repo.is_whitelisted(conn, project_id, segment_fingerprint, scope=doc_id)
                )

                verdict_log = VerdictLog(
                    vid=str(uuid.uuid4()),
                    project_id=project_id,
                    input_doc_id=doc_id,
                    input_snapshot_id=snapshot_id,
                    schema_ver=schema_ver,
                    segment_span=Span(start=claim_start + offset, end=claim_end + offset),
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
