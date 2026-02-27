from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from modules.nf_consistency.contracts import ConsistencyRequest
from modules.nf_consistency.extractors import ExtractionPipeline, normalize_extraction_profile
from modules.nf_consistency.extractors.contracts import ExtractionMapping as ExtractorMapping
from modules.nf_model_gateway.gateway import select_model
from modules.nf_model_gateway.local.nli_model import infer_nli_distribution
from modules.nf_model_gateway.local.reranker_model import rerank_results
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
from modules.nf_shared.sentence_rules import (
    SENTENCE_END_CHARS,
    SENTENCE_MAX_TAIL_SCAN,
    SENTENCE_TAIL_CHARS,
    is_abbreviation_boundary,
    is_decimal_boundary,
)
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
_DEFAULT_LAYER3_OK_THRESHOLD = 0.92
_DEFAULT_LAYER3_CONTRADICT_THRESHOLD = 0.85
_DEFAULT_VERIFIER_MODE = "off"
_DEFAULT_VERIFIER_PROMOTE_OK_THRESHOLD = 0.95
_DEFAULT_VERIFIER_CONTRADICT_ALERT_THRESHOLD = 0.70
_DEFAULT_VERIFIER_MAX_CLAIM_CHARS = 220
_DEFAULT_TRIAGE_MODE = "off"
_DEFAULT_TRIAGE_ANOMALY_THRESHOLD = 0.65
_DEFAULT_TRIAGE_MAX_SEGMENTS_PER_RUN = 8
_DEFAULT_VERIFICATION_LOOP_ENABLED = False
_DEFAULT_VERIFICATION_LOOP_MAX_ROUNDS = 2
_DEFAULT_VERIFICATION_LOOP_ROUND_TIMEOUT_MS = 250
_DEFAULT_CLAIM_CONFIDENCE_MIN = 0.20
_DEFAULT_GRAPH_MODE = "off"
_DEFAULT_EPISODE_SCOPE_WINDOW = 10
_CANDIDATE_K = 12
_FINAL_K = 3
_VECTOR_REFILL_MIN = 6
_LAYER3_RERANK_TOP_N = 12
_LAYER3_NLI_TOP_K = 3
_RETRIEVAL_CACHE_SIZE = 256
_UNKNOWN_REASON_NO_EVIDENCE = "NO_EVIDENCE"
_UNKNOWN_REASON_AMBIGUOUS_ENTITY = "AMBIGUOUS_ENTITY"
_UNKNOWN_REASON_SLOT_UNCOMPARABLE = "SLOT_UNCOMPARABLE"
_UNKNOWN_REASON_CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
_HASHED_EMBEDDING_DIM = 96

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
_SENTENCE_END_CHAR_SET = set(SENTENCE_END_CHARS)
_SENTENCE_TAIL_CHAR_SET = set(SENTENCE_TAIL_CHARS)
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
        if ch not in _SENTENCE_END_CHAR_SET:
            idx += 1
            continue
        if ch == "." and (is_decimal_boundary(text, idx) or is_abbreviation_boundary(text, idx)):
            idx += 1
            continue
        seg_end = idx
        if ch != "\n":
            seg_end = idx + 1
            tail_scan = 0
            while (
                seg_end < text_len
                and tail_scan < SENTENCE_MAX_TAIL_SCAN
                and text[seg_end] in _SENTENCE_TAIL_CHAR_SET
            ):
                seg_end += 1
                tail_scan += 1
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
    doc_id = raw.get("doc_id")
    if isinstance(doc_id, str) and doc_id.strip():
        normalized["doc_id"] = doc_id.strip()
    doc_ids = raw.get("doc_ids")
    if isinstance(doc_ids, list):
        keep: list[str] = []
        seen: set[str] = set()
        for item in doc_ids:
            if not isinstance(item, str):
                continue
            token = item.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            keep.append(token)
        if keep:
            normalized["doc_ids"] = keep
    return normalized


def _doc_type_name(doc_type: Any) -> str:
    if isinstance(doc_type, str):
        return doc_type
    value = getattr(doc_type, "value", None)
    return value if isinstance(value, str) else ""


def _extract_episode_number_from_doc(doc: Any) -> int | None:
    metadata = getattr(doc, "metadata", None)
    if hasattr(metadata, "get"):
        raw_episode_no = metadata.get("episode_no")
        if isinstance(raw_episode_no, int):
            return raw_episode_no
        if isinstance(raw_episode_no, str):
            token = raw_episode_no.strip()
            if token.isdigit():
                try:
                    return int(token)
                except ValueError:
                    pass
    title = getattr(doc, "title", "")
    if isinstance(title, str):
        matches = re.findall(r"\d+", title)
        if matches:
            try:
                return int(matches[0])
            except ValueError:
                pass
    return None


def _is_world_context_doc(doc: Any) -> bool:
    doc_type = _doc_type_name(getattr(doc, "type", None))
    if doc_type in {"SETTING", "CHAR", "PLOT"}:
        return True
    metadata = getattr(doc, "metadata", None)
    if not hasattr(metadata, "get"):
        return False
    group = metadata.get("group")
    if not isinstance(group, str):
        return False
    lowered = group.strip().lower()
    return lowered in {"timeline", "타임라인"}


def _build_default_doc_scope(
    project_docs: list[Any],
    *,
    input_doc_id: str,
    episode_window: int = _DEFAULT_EPISODE_SCOPE_WINDOW,
) -> list[str]:
    if not project_docs:
        return [input_doc_id]
    episode_window = max(0, int(episode_window))
    selected: set[str] = {input_doc_id}
    docs_by_id = {
        doc.doc_id: doc
        for doc in project_docs
        if isinstance(getattr(doc, "doc_id", None), str) and getattr(doc, "doc_id")
    }
    current_doc = docs_by_id.get(input_doc_id)
    current_episode_no = _extract_episode_number_from_doc(current_doc) if current_doc is not None else None
    for doc in project_docs:
        doc_id = getattr(doc, "doc_id", None)
        if not isinstance(doc_id, str) or not doc_id:
            continue
        if doc_id == input_doc_id or _is_world_context_doc(doc):
            selected.add(doc_id)
            continue
        if _doc_type_name(getattr(doc, "type", None)) != "EPISODE":
            continue
        if current_episode_no is None:
            continue
        candidate_episode_no = _extract_episode_number_from_doc(doc)
        if candidate_episode_no is None:
            continue
        if abs(candidate_episode_no - current_episode_no) <= episode_window:
            selected.add(doc_id)
    ordered: list[str] = []
    seen: set[str] = set()
    for doc in project_docs:
        doc_id = getattr(doc, "doc_id", None)
        if not isinstance(doc_id, str) or not doc_id:
            continue
        if doc_id in selected and doc_id not in seen:
            seen.add(doc_id)
            ordered.append(doc_id)
    if input_doc_id not in seen:
        ordered.insert(0, input_doc_id)
    return ordered


def _inject_default_doc_scope(
    filters: dict[str, object],
    *,
    project_docs: list[Any],
    input_doc_id: str,
) -> dict[str, object]:
    next_filters = dict(filters)
    if isinstance(next_filters.get("doc_id"), str):
        return next_filters
    raw_doc_ids = next_filters.get("doc_ids")
    if isinstance(raw_doc_ids, list) and any(isinstance(item, str) and item.strip() for item in raw_doc_ids):
        return next_filters
    next_filters["doc_ids"] = _build_default_doc_scope(project_docs, input_doc_id=input_doc_id)
    return next_filters


def _has_metadata_scope_filters(filters: dict[str, object]) -> bool:
    if not filters:
        return False
    return any(key in filters for key in ("entity_id", "time_key", "timeline_idx"))


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


def _resolve_graph_mode(req: ConsistencyRequest, *, legacy_enabled: bool) -> str:
    mode_raw = req.get("graph_mode")
    if isinstance(mode_raw, str):
        mode = mode_raw.strip().lower()
        if mode in {"off", "manual", "auto"}:
            return mode
    return "manual" if legacy_enabled else _DEFAULT_GRAPH_MODE


def _has_graph_seed_signal(*, filters: dict[str, object], slots: dict[str, object]) -> bool:
    if any(filters.get(key) is not None for key in ("entity_id", "time_key", "timeline_idx")):
        return True
    for slot_key in slots:
        if slot_key in {"time", "place", "relation"}:
            return True
    return False


def _has_graph_ambiguity_signal(results: list[dict[str, Any]]) -> bool:
    if len(results) < 4:
        return True
    scores = sorted((_base_retrieval_score(row) for row in results), reverse=True)
    if not scores:
        return True
    top1 = scores[0]
    top2 = scores[1] if len(scores) > 1 else 0.0
    return top1 < 0.30 or (top1 - top2) < 0.07


def _resolve_layer3_promotion_options(req: ConsistencyRequest) -> tuple[bool, float, int, float, float]:
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

    contradict_threshold_raw = req.get("layer3_contradict_threshold")
    try:
        contradict_threshold = (
            float(contradict_threshold_raw)
            if contradict_threshold_raw is not None
            else _DEFAULT_LAYER3_CONTRADICT_THRESHOLD
        )
    except (TypeError, ValueError):
        contradict_threshold = _DEFAULT_LAYER3_CONTRADICT_THRESHOLD
    contradict_threshold = _clamp01(contradict_threshold)

    return enabled, min_fts, max_claim_chars, ok_threshold, contradict_threshold


def _resolve_verifier_options(req: ConsistencyRequest) -> tuple[str, float, float, int]:
    raw = req.get("verifier")
    options = raw if isinstance(raw, dict) else {}
    mode_raw = options.get("mode")
    mode = str(mode_raw).strip().lower() if isinstance(mode_raw, str) else _DEFAULT_VERIFIER_MODE
    if mode not in {"off", "conservative_nli"}:
        mode = _DEFAULT_VERIFIER_MODE

    promote_raw = options.get("promote_ok_threshold")
    try:
        promote_ok_threshold = (
            float(promote_raw)
            if promote_raw is not None
            else _DEFAULT_VERIFIER_PROMOTE_OK_THRESHOLD
        )
    except (TypeError, ValueError):
        promote_ok_threshold = _DEFAULT_VERIFIER_PROMOTE_OK_THRESHOLD
    promote_ok_threshold = _clamp01(promote_ok_threshold)

    contradict_raw = options.get("contradict_alert_threshold")
    try:
        contradict_alert_threshold = (
            float(contradict_raw)
            if contradict_raw is not None
            else _DEFAULT_VERIFIER_CONTRADICT_ALERT_THRESHOLD
        )
    except (TypeError, ValueError):
        contradict_alert_threshold = _DEFAULT_VERIFIER_CONTRADICT_ALERT_THRESHOLD
    contradict_alert_threshold = _clamp01(contradict_alert_threshold)

    max_claim_chars_raw = options.get("max_claim_chars")
    try:
        max_claim_chars = int(max_claim_chars_raw) if max_claim_chars_raw is not None else _DEFAULT_VERIFIER_MAX_CLAIM_CHARS
    except (TypeError, ValueError):
        max_claim_chars = _DEFAULT_VERIFIER_MAX_CLAIM_CHARS
    max_claim_chars = max(1, max_claim_chars)
    return mode, promote_ok_threshold, contradict_alert_threshold, max_claim_chars


def _resolve_triage_options(req: ConsistencyRequest) -> tuple[str, float, int]:
    raw = req.get("triage")
    options = raw if isinstance(raw, dict) else {}
    mode_raw = options.get("mode")
    mode = str(mode_raw).strip().lower() if isinstance(mode_raw, str) else _DEFAULT_TRIAGE_MODE
    if mode not in {"off", "embedding_anomaly"}:
        mode = _DEFAULT_TRIAGE_MODE

    threshold_raw = options.get("anomaly_threshold")
    try:
        threshold = float(threshold_raw) if threshold_raw is not None else _DEFAULT_TRIAGE_ANOMALY_THRESHOLD
    except (TypeError, ValueError):
        threshold = _DEFAULT_TRIAGE_ANOMALY_THRESHOLD
    threshold = _clamp01(threshold)

    max_segments_raw = options.get("max_segments_per_run")
    try:
        max_segments = int(max_segments_raw) if max_segments_raw is not None else _DEFAULT_TRIAGE_MAX_SEGMENTS_PER_RUN
    except (TypeError, ValueError):
        max_segments = _DEFAULT_TRIAGE_MAX_SEGMENTS_PER_RUN
    max_segments = max(1, max_segments)
    return mode, threshold, max_segments


def _resolve_verification_loop_options(req: ConsistencyRequest) -> tuple[bool, int, int]:
    raw = req.get("verification_loop")
    options = raw if isinstance(raw, dict) else {}

    enabled_raw = options.get("enabled")
    enabled = bool(enabled_raw) if enabled_raw is not None else _DEFAULT_VERIFICATION_LOOP_ENABLED

    max_rounds_raw = options.get("max_rounds")
    try:
        max_rounds = int(max_rounds_raw) if max_rounds_raw is not None else _DEFAULT_VERIFICATION_LOOP_MAX_ROUNDS
    except (TypeError, ValueError):
        max_rounds = _DEFAULT_VERIFICATION_LOOP_MAX_ROUNDS
    max_rounds = max(1, max_rounds)

    timeout_raw = options.get("round_timeout_ms")
    try:
        round_timeout_ms = (
            int(timeout_raw)
            if timeout_raw is not None
            else _DEFAULT_VERIFICATION_LOOP_ROUND_TIMEOUT_MS
        )
    except (TypeError, ValueError):
        round_timeout_ms = _DEFAULT_VERIFICATION_LOOP_ROUND_TIMEOUT_MS
    round_timeout_ms = max(1, round_timeout_ms)
    return enabled, max_rounds, round_timeout_ms


def _tokenize_for_embedding(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    tokens = re.findall(r"[0-9a-z\uac00-\ud7a3]+", normalized)
    if tokens:
        return tokens
    compact = normalized.strip()
    return [compact] if compact else []


def _vectorize_text_embedding(text: str, *, dim: int = _HASHED_EMBEDDING_DIM) -> list[float]:
    vec = [0.0 for _ in range(dim)]
    tokens = _tokenize_for_embedding(text)
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[0:2], "big") % dim
        sign = 1.0 if (digest[2] % 2 == 0) else -1.0
        vec[idx] += sign
    norm = sum(value * value for value in vec) ** 0.5
    if norm <= 0:
        return vec
    return [value / norm for value in vec]


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0 for _ in range(dim)]
    for vec in vectors:
        if len(vec) != dim:
            continue
        for idx, value in enumerate(vec):
            out[idx] += value
    denom = float(max(1, len(vectors)))
    averaged = [value / denom for value in out]
    norm = sum(value * value for value in averaged) ** 0.5
    if norm <= 0:
        return averaged
    return [value / norm for value in averaged]


def _cosine_similarity(lhs: list[float], rhs: list[float]) -> float:
    if not lhs or not rhs or len(lhs) != len(rhs):
        return 0.0
    dot = 0.0
    for left, right in zip(lhs, rhs):
        dot += left * right
    return _clamp01((dot + 1.0) * 0.5)


def _build_world_memory_embedding(*, facts: list, entities: list, aliases: list) -> list[float]:
    memory_texts: list[str] = []
    for fact in facts:
        tag_path = str(getattr(fact, "tag_path", "") or "")
        value = str(getattr(fact, "value", "") or "")
        chunk = f"{tag_path} {value}".strip()
        if chunk:
            memory_texts.append(chunk)
    for entity in entities:
        canonical_name = str(getattr(entity, "canonical_name", "") or "")
        if canonical_name:
            memory_texts.append(canonical_name)
    for alias in aliases:
        alias_text = str(getattr(alias, "alias_text", "") or "")
        if alias_text:
            memory_texts.append(alias_text)
    vectors = [_vectorize_text_embedding(text) for text in memory_texts if text]
    return _average_vectors(vectors)


def _select_claims_by_triage(
    claims: list[dict[str, Any]],
    *,
    mode: str,
    anomaly_threshold: float,
    max_segments_per_run: int,
    world_memory_embedding: list[float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if mode != "embedding_anomaly":
        return claims, {
            "mode": "off",
            "total_claims": len(claims),
            "selected_claims": len(claims),
            "skipped_claims": 0,
        }
    if not claims:
        return claims, {
            "mode": "embedding_anomaly",
            "total_claims": 0,
            "selected_claims": 0,
            "skipped_claims": 0,
        }

    scored: list[tuple[dict[str, Any], float]] = []
    for claim in claims:
        claim_text = str(claim.get("segment_text") or claim.get("claim_text") or "")
        claim_embedding = _vectorize_text_embedding(claim_text)
        similarity = _cosine_similarity(claim_embedding, world_memory_embedding)
        anomaly_score = _clamp01(1.0 - similarity)
        scored.append((claim, anomaly_score))
    scored.sort(key=lambda item: item[1], reverse=True)

    selected: list[dict[str, Any]] = []
    for claim, anomaly_score in scored:
        if anomaly_score < anomaly_threshold:
            continue
        selected.append(claim)
        if len(selected) >= max_segments_per_run:
            break

    if not selected and scored:
        selected.append(scored[0][0])
    if len(selected) > max_segments_per_run:
        selected = selected[:max_segments_per_run]

    selected_keys = {id(item) for item in selected}
    return selected, {
        "mode": "embedding_anomaly",
        "total_claims": len(claims),
        "selected_claims": len(selected),
        "skipped_claims": max(0, len(claims) - len(selected)),
        "anomaly_threshold": float(anomaly_threshold),
        "max_segments_per_run": int(max_segments_per_run),
        "fallback_selected": bool(scored and len(selected) == 1 and id(scored[0][0]) in selected_keys),
    }


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
        # FTS(BM25)는 낮을수록 좋은 방향이므로 절댓값 기반으로 [0,1] 강도로 정규화한다.
        return _clamp01(1.0 / (1.0 + abs(raw_score)))
    return max(0.0, min(1.0, raw_score))


def _rerank_results_for_consistency(
    *,
    results: list[dict[str, Any]],
    claim_text: str,
    filters: dict[str, object],
    graph_doc_distances: dict[str, int],
    gateway: Any,
    enable_model: bool,
    settings: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not results:
        return [], {
            "entail_score": 0.0,
            "contradict_score": 0.0,
            "rerank_applied": False,
            "model_fallback_count": 0,
        }

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
    rerank_applied = False
    model_fallback_count = 0
    if enable_model and bool(getattr(settings, "enable_local_reranker", False)):
        top_rows = [row for row, _score in scored[:_LAYER3_RERANK_TOP_N]]
        try:
            rerank_pairs, fallback_used = rerank_results(
                claim_text,
                top_rows,
                enabled=True,
                model_id=str(getattr(settings, "local_reranker_model_id", "")),
            )
            if fallback_used:
                model_fallback_count += 1
            if rerank_pairs:
                rerank_applied = True
                rerank_bonus: dict[str, float] = {}
                for idx, rerank_score in rerank_pairs:
                    if idx < 0 or idx >= len(top_rows):
                        continue
                    rerank_bonus[_result_identity(top_rows[idx])] = 0.25 * float(rerank_score)
                rescored: list[tuple[dict[str, Any], float]] = []
                for row, cheap_score in scored:
                    rescored.append((row, cheap_score + rerank_bonus.get(_result_identity(row), 0.0)))
                scored = rescored
                scored.sort(key=lambda item: item[1], reverse=True)
        except Exception:  # noqa: BLE001
            model_fallback_count += 1

    entail_score = 0.0
    contradict_score = 0.0
    if enable_model:
        top_rows = [row for row, _score in scored[:_LAYER3_NLI_TOP_K]]
        evidence_rows = _bundle_result_rows(top_rows)
        snippets = []
        for item in evidence_rows:
            snippet = str(item.get("snippet_text", "") or "")
            if snippet:
                snippets.append(snippet)
        premise = "\n".join(snippets[:_LAYER3_NLI_TOP_K])
        if premise:
            if bool(getattr(settings, "enable_local_nli", False)):
                try:
                    scores = infer_nli_distribution(
                        premise,
                        claim_text,
                        enabled=True,
                        model_id=str(getattr(settings, "local_nli_model_id", "")),
                    )
                    entail_score = _clamp01(float(scores.get("entail", 0.0)))
                    contradict_score = _clamp01(float(scores.get("contradict", 0.0)))
                    if bool(scores.get("fallback_used")):
                        model_fallback_count += 1
                except Exception:  # noqa: BLE001
                    model_fallback_count += 1
            if entail_score <= 0.0 and gateway is not None:
                try:
                    entail_score = _clamp01(
                        float(
                            gateway.nli_score(
                                {
                                    "claim_text": claim_text,
                                    "evidence": evidence_rows,
                                }
                            )
                        )
                    )
                except Exception:  # noqa: BLE001
                    model_fallback_count += 1

    return [row for row, _score in scored], {
        "entail_score": entail_score,
        "contradict_score": contradict_score,
        "rerank_applied": rerank_applied,
        "model_fallback_count": model_fallback_count,
    }


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


def _overlaps_any_span(span_start: int, span_end: int, spans: list[tuple[int, int]]) -> bool:
    for other_start, other_end in spans:
        if span_start < other_end and other_start < span_end:
            return True
    return False


def _load_user_tag_spans(
    conn,
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    cache: dict[tuple[str, str], list[tuple[int, int]]],
) -> list[tuple[int, int]]:
    key = (doc_id, snapshot_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = conn.execute(
        """
        SELECT span_start, span_end
        FROM tag_assignment
        WHERE project_id = ? AND doc_id = ? AND snapshot_id = ? AND created_by = ?
        """,
        (project_id, doc_id, snapshot_id, FactSource.USER.value),
    ).fetchall()
    spans: list[tuple[int, int]] = []
    for row in rows:
        try:
            start = int(row["span_start"])
            end = int(row["span_end"])
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        spans.append((start, end))
    cache[key] = spans
    return spans


def _load_approved_evidence_spans(
    conn,
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    cache: dict[tuple[str, str], list[tuple[int, int]]],
) -> list[tuple[int, int]]:
    key = (doc_id, snapshot_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = conn.execute(
        """
        SELECT e.span_start AS span_start, e.span_end AS span_end
        FROM evidence e
        JOIN schema_facts sf ON sf.evidence_eid = e.eid
        WHERE sf.project_id = ? AND e.doc_id = ? AND e.snapshot_id = ? AND sf.status = ?
        """,
        (project_id, doc_id, snapshot_id, FactStatus.APPROVED.value),
    ).fetchall()
    spans: list[tuple[int, int]] = []
    for row in rows:
        try:
            start = int(row["span_start"])
            end = int(row["span_end"])
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        spans.append((start, end))
    cache[key] = spans
    return spans


def _promote_confirmed_evidence(
    conn,
    *,
    project_id: str,
    results: list[dict[str, Any]],
    user_tag_span_cache: dict[tuple[str, str], list[tuple[int, int]]],
    approved_evidence_span_cache: dict[tuple[str, str], list[tuple[int, int]]],
) -> None:
    for row in results:
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            continue
        if bool(evidence.get("confirmed", False)):
            continue

        doc_id_raw = evidence.get("doc_id")
        snapshot_id_raw = evidence.get("snapshot_id")
        if not isinstance(doc_id_raw, str) or not doc_id_raw:
            continue
        if not isinstance(snapshot_id_raw, str) or not snapshot_id_raw:
            continue
        try:
            span_start = int(evidence.get("span_start", 0))
            span_end = int(evidence.get("span_end", 0))
        except (TypeError, ValueError):
            continue
        if span_end <= span_start:
            continue

        user_spans = _load_user_tag_spans(
            conn,
            project_id=project_id,
            doc_id=doc_id_raw,
            snapshot_id=snapshot_id_raw,
            cache=user_tag_span_cache,
        )
        approved_spans = _load_approved_evidence_spans(
            conn,
            project_id=project_id,
            doc_id=doc_id_raw,
            snapshot_id=snapshot_id_raw,
            cache=approved_evidence_span_cache,
        )
        if _overlaps_any_span(span_start, span_end, user_spans) or _overlaps_any_span(span_start, span_end, approved_spans):
            evidence["confirmed"] = True


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
        fts_component = _clamp01(float(breakdown.fts_strength))
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
        graph_mode = _resolve_graph_mode(req, legacy_enabled=graph_expand_enabled)
        (
            layer3_promotion_enabled,
            layer3_min_fts,
            layer3_max_claim_chars,
            layer3_ok_threshold,
            layer3_contradict_threshold,
        ) = _resolve_layer3_promotion_options(req)
        (
            verifier_mode,
            verifier_promote_ok_threshold,
            verifier_contradict_alert_threshold,
            verifier_max_claim_chars,
        ) = _resolve_verifier_options(req)
        triage_mode, triage_anomaly_threshold, triage_max_segments_per_run = _resolve_triage_options(req)
        (
            verification_loop_enabled,
            verification_loop_max_rounds,
            verification_loop_round_timeout_ms,
        ) = _resolve_verification_loop_options(req)
        verifier_ok_threshold = verifier_promote_ok_threshold if verifier_mode == "conservative_nli" else layer3_ok_threshold
        verifier_contradict_threshold = (
            verifier_contradict_alert_threshold
            if verifier_mode == "conservative_nli"
            else layer3_contradict_threshold
        )
        verifier_claim_char_limit = verifier_max_claim_chars if verifier_mode == "conservative_nli" else layer3_max_claim_chars
        retrieval_filters = _normalize_consistency_filters(req.get("filters"))
        metadata_filter_requested = _has_metadata_scope_filters(retrieval_filters)
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
            req_stats.setdefault("graph_auto_trigger_count", 0)
            req_stats.setdefault("graph_auto_skip_count", 0)
            req_stats.setdefault("unknown_reason_counts", {})
            req_stats.setdefault("evidence_confidence_sum", 0.0)
            req_stats.setdefault("decision_confidence_sum", 0.0)
            req_stats.setdefault("layer3_promoted_ok_count", 0)
            req_stats.setdefault("layer3_rerank_applied_count", 0)
            req_stats.setdefault("layer3_model_fallback_count", 0)
            req_stats.setdefault("claims_skipped_low_confidence", 0)
            req_stats.setdefault("triage_skipped_claims", 0)
            req_stats.setdefault("verification_loop_trigger_count", 0)
            req_stats.setdefault("verification_loop_rounds_total", 0)
            req_stats.setdefault("verification_loop_timeout_count", 0)
            req_stats["verifier_mode"] = verifier_mode
            req_stats["triage_mode"] = triage_mode
            req_stats["graph_mode"] = graph_mode

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
            project_docs = document_repo.list_documents(conn, project_id)
            retrieval_filters = _inject_default_doc_scope(
                retrieval_filters,
                project_docs=project_docs,
                input_doc_id=doc_id,
            )
            if req_stats is not None:
                doc_scope = retrieval_filters.get("doc_ids")
                if isinstance(doc_scope, list):
                    req_stats["default_doc_scope_count"] = len(doc_scope)

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
            world_memory_embedding = _build_world_memory_embedding(facts=facts, entities=entities, aliases=aliases)
            claims, triage_meta = _select_claims_by_triage(
                claims,
                mode=triage_mode,
                anomaly_threshold=triage_anomaly_threshold,
                max_segments_per_run=triage_max_segments_per_run,
                world_memory_embedding=world_memory_embedding,
            )
            if req_stats is not None:
                req_stats["triage_total_claims"] = int(triage_meta.get("total_claims", len(claims)))
                req_stats["triage_selected_claims"] = int(triage_meta.get("selected_claims", len(claims)))
                req_stats["triage_skipped_claims"] = int(triage_meta.get("skipped_claims", 0))
                req_stats["triage_anomaly_threshold"] = float(triage_meta.get("anomaly_threshold", triage_anomaly_threshold))
                req_stats["triage_max_segments_per_run"] = int(
                    triage_meta.get("max_segments_per_run", triage_max_segments_per_run)
                )
            excluded_self_fact_eids = _resolve_excluded_self_fact_eids(
                conn,
                facts=facts,
                input_doc_id=doc_id,
            )
            retrieval_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
            slot_compare_cache: dict[tuple[str, str, str], Verdict | None] = {}
            user_tag_span_cache: dict[tuple[str, str], list[tuple[int, int]]] = {}
            approved_evidence_span_cache: dict[tuple[str, str], list[tuple[int, int]]] = {}

            verdicts: list[VerdictLog] = []
            for claim in claims:
                claim_text = str(claim["claim_text"])
                segment_text = str(claim["segment_text"])
                claim_start = int(claim["claim_start"])
                claim_end = int(claim["claim_end"])
                slots = dict(claim.get("slots") or {})
                slot_confidence = float(claim.get("slot_confidence", 0.0) or 0.0)
                if req_stats is not None:
                    req_stats["claims_processed"] = int(req_stats.get("claims_processed", 0)) + 1
                if (
                    extraction_profile.get("mode") != "rule_only"
                    and slot_confidence < _DEFAULT_CLAIM_CONFIDENCE_MIN
                ):
                    if req_stats is not None:
                        req_stats["claims_skipped_low_confidence"] = int(
                            req_stats.get("claims_skipped_low_confidence", 0)
                        ) + 1
                    continue
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
                cache_filters = dict(retrieval_filters)
                if graph_mode == "auto":
                    slot_key_hint = claim.get("slot_key")
                    if isinstance(slot_key_hint, str) and slot_key_hint:
                        cache_filters["_slot_key"] = slot_key_hint
                cache_key = _claim_cache_key(retrieval_query, filters=cache_filters)
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
                        vector_req: dict[str, Any] = {
                            "project_id": project_id,
                            "query": retrieval_query,
                            "filters": dict(retrieval_filters),
                            "k": _CANDIDATE_K,
                            "stats": retrieval_stats,
                        }
                        vector_results = vector_search(vector_req)
                        candidate_results = _merge_result_lists(
                            candidate_results,
                            vector_results,
                            limit=_CANDIDATE_K * 3,
                        )
                    graph_expand_for_claim = False
                    if graph_mode == "manual":
                        graph_expand_for_claim = True
                    elif graph_mode == "auto":
                        seed_signal = _has_graph_seed_signal(filters=retrieval_filters, slots=slots)
                        ambiguity_signal = _has_graph_ambiguity_signal(candidate_results)
                        graph_expand_for_claim = seed_signal and ambiguity_signal
                        if req_stats is not None:
                            stat_key = "graph_auto_trigger_count" if graph_expand_for_claim else "graph_auto_skip_count"
                            req_stats[stat_key] = int(req_stats.get(stat_key, 0)) + 1
                    if graph_expand_for_claim:
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
                _promote_confirmed_evidence(
                    conn,
                    project_id=project_id,
                    results=candidate_results,
                    user_tag_span_cache=user_tag_span_cache,
                    approved_evidence_span_cache=approved_evidence_span_cache,
                )
                reranked_results, rerank_meta = _rerank_results_for_consistency(
                    results=candidate_results,
                    claim_text=claim_text,
                    filters=retrieval_filters,
                    graph_doc_distances=graph_doc_distances,
                    gateway=gateway,
                    enable_model=bool(settings.enable_layer3_model),
                    settings=settings,
                )
                results = reranked_results[:_FINAL_K]
                candidates = find_entity_candidates(segment_text, alias_index)
                ambiguous = len(candidates) > 1
                target_entity_id: str | None = None
                if len(candidates) == 1:
                    target_entity_id = next(iter(candidates))

                def _accumulate_metrics(local_retrieval_stats: dict[str, Any], local_rerank_meta: dict[str, Any]) -> None:
                    if req_stats is None:
                        return
                    req_stats["chunks_processed"] = int(req_stats.get("chunks_processed", 0)) + int(
                        local_retrieval_stats.get("chunks_processed", 0)
                    )
                    req_stats["rows_scanned"] = int(req_stats.get("rows_scanned", 0)) + int(
                        local_retrieval_stats.get("rows_scanned", 0)
                    )
                    req_stats["shards_loaded"] = int(req_stats.get("shards_loaded", 0)) + int(
                        local_retrieval_stats.get("shards_loaded", 0)
                    )
                    if bool(local_rerank_meta.get("rerank_applied")):
                        req_stats["layer3_rerank_applied_count"] = int(req_stats.get("layer3_rerank_applied_count", 0)) + 1
                    req_stats["layer3_model_fallback_count"] = int(req_stats.get("layer3_model_fallback_count", 0)) + int(
                        local_rerank_meta.get("model_fallback_count", 0) or 0
                    )

                def _evaluate_current_results(
                    current_results: list[dict[str, Any]],
                    current_rerank_meta: dict[str, Any],
                ) -> dict[str, Any]:
                    verdict = Verdict.UNKNOWN
                    unknown_reasons: set[str] = set()
                    if not current_results:
                        unknown_reasons.add(_UNKNOWN_REASON_NO_EVIDENCE)

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

                    if verdict is Verdict.VIOLATE and not any(role is EvidenceRole.CONTRADICT for _, role in fact_links):
                        verdict = Verdict.UNKNOWN
                        unknown_reasons.add(_UNKNOWN_REASON_CONFLICTING_EVIDENCE)

                    fts_strength = _base_retrieval_score(current_results[0]) if current_results else 0.0
                    promotion_fts_strength = fts_strength
                    model_score = (
                        float(current_rerank_meta.get("entail_score", 0.0))
                        if settings.enable_layer3_model
                        else 0.0
                    )
                    contradict_score = (
                        float(current_rerank_meta.get("contradict_score", 0.0))
                        if settings.enable_layer3_model
                        else 0.0
                    )
                    confirmed_evidence_count = len(
                        [
                            row
                            for row in current_results
                            if bool((row.get("evidence") or {}).get("confirmed", False))
                        ]
                    )

                    if verdict is Verdict.UNKNOWN and contradict_score >= verifier_contradict_threshold:
                        unknown_reasons.add(_UNKNOWN_REASON_CONFLICTING_EVIDENCE)
                    if (
                        verdict is Verdict.OK
                        and verifier_mode == "conservative_nli"
                        and settings.enable_layer3_model
                        and contradict_score >= verifier_contradict_threshold
                    ):
                        verdict = Verdict.UNKNOWN
                        unknown_reasons.add(_UNKNOWN_REASON_CONFLICTING_EVIDENCE)

                    promotion_blocked = bool(
                        ambiguous
                        or judge_meta.get("saw_uncomparable")
                        or judge_meta.get("conflicting")
                        or (_UNKNOWN_REASON_AMBIGUOUS_ENTITY in unknown_reasons)
                        or (_UNKNOWN_REASON_SLOT_UNCOMPARABLE in unknown_reasons)
                        or (_UNKNOWN_REASON_CONFLICTING_EVIDENCE in unknown_reasons)
                    )
                    promoted = False
                    if (
                        verdict is Verdict.UNKNOWN
                        and settings.enable_layer3_model
                        and layer3_promotion_enabled
                        and current_results
                        and confirmed_evidence_count >= 2
                        and not promotion_blocked
                        and promotion_fts_strength >= layer3_min_fts
                        and len(claim_text) <= verifier_claim_char_limit
                        and model_score >= verifier_ok_threshold
                        and contradict_score < verifier_contradict_threshold
                    ):
                        verdict = Verdict.OK
                        unknown_reasons.clear()
                        promoted = True

                    if verdict is Verdict.UNKNOWN and not unknown_reasons:
                        if current_results:
                            unknown_reasons.add(_UNKNOWN_REASON_CONFLICTING_EVIDENCE)
                        else:
                            unknown_reasons.add(_UNKNOWN_REASON_NO_EVIDENCE)
                    if verdict is not Verdict.UNKNOWN:
                        unknown_reasons.clear()

                    return {
                        "verdict": verdict,
                        "unknown_reasons": unknown_reasons,
                        "fact_links": fact_links,
                        "judge_meta": judge_meta,
                        "fts_strength": fts_strength,
                        "promotion_fts_strength": promotion_fts_strength,
                        "model_score": model_score,
                        "contradict_score": contradict_score,
                        "confirmed_evidence_count": confirmed_evidence_count,
                        "promoted": promoted,
                    }

                _accumulate_metrics(retrieval_stats, rerank_meta)
                evaluation = _evaluate_current_results(results, rerank_meta)

                should_verify = (
                    verification_loop_enabled
                    and evaluation["verdict"] is Verdict.UNKNOWN
                    and bool(
                        evaluation["unknown_reasons"]
                        & {_UNKNOWN_REASON_NO_EVIDENCE, _UNKNOWN_REASON_CONFLICTING_EVIDENCE}
                    )
                )
                if should_verify:
                    if req_stats is not None:
                        req_stats["verification_loop_trigger_count"] = int(
                            req_stats.get("verification_loop_trigger_count", 0)
                        ) + 1
                    loop_started = time.perf_counter()
                    for round_idx in range(verification_loop_max_rounds):
                        elapsed_ms = (time.perf_counter() - loop_started) * 1000.0
                        if elapsed_ms >= float(verification_loop_round_timeout_ms):
                            if req_stats is not None:
                                req_stats["verification_loop_timeout_count"] = int(
                                    req_stats.get("verification_loop_timeout_count", 0)
                                ) + 1
                            break
                        loop_query = claim_text if round_idx == 0 else f"{claim_text} {segment_text}".strip()
                        loop_retrieval_stats: dict[str, Any] = {
                            "chunks_processed": 0,
                            "rows_scanned": 0,
                            "shards_loaded": 0,
                        }
                        loop_req: dict[str, Any] = {
                            "project_id": project_id,
                            "query": loop_query,
                            "filters": dict(retrieval_filters),
                            "k": _CANDIDATE_K + (round_idx + 1) * 2,
                            "stats": loop_retrieval_stats,
                        }
                        loop_results = fts_search(conn, loop_req)
                        if (
                            len(loop_results) < _VECTOR_REFILL_MIN
                            and settings.vector_index_mode.upper() != "DISABLED"
                            and not metadata_filter_requested
                        ):
                            loop_vector_req: dict[str, Any] = {
                                "project_id": project_id,
                                "query": loop_query,
                                "filters": dict(retrieval_filters),
                                "k": _CANDIDATE_K,
                                "stats": loop_retrieval_stats,
                            }
                            loop_vector_results = vector_search(loop_vector_req)
                            loop_results = _merge_result_lists(
                                loop_results,
                                loop_vector_results,
                                limit=_CANDIDATE_K * 3,
                            )
                        candidate_results = _merge_result_lists(candidate_results, loop_results, limit=_CANDIDATE_K * 4)
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
                        _promote_confirmed_evidence(
                            conn,
                            project_id=project_id,
                            results=candidate_results,
                            user_tag_span_cache=user_tag_span_cache,
                            approved_evidence_span_cache=approved_evidence_span_cache,
                        )
                        reranked_results, rerank_meta = _rerank_results_for_consistency(
                            results=candidate_results,
                            claim_text=claim_text,
                            filters=retrieval_filters,
                            graph_doc_distances=graph_doc_distances,
                            gateway=gateway,
                            enable_model=bool(settings.enable_layer3_model),
                            settings=settings,
                        )
                        results = reranked_results[:_FINAL_K]
                        _accumulate_metrics(loop_retrieval_stats, rerank_meta)
                        if req_stats is not None:
                            req_stats["verification_loop_rounds_total"] = int(
                                req_stats.get("verification_loop_rounds_total", 0)
                            ) + 1
                        evaluation = _evaluate_current_results(results, rerank_meta)
                        if evaluation["verdict"] is not Verdict.UNKNOWN:
                            break
                        if not (
                            evaluation["unknown_reasons"]
                            & {_UNKNOWN_REASON_NO_EVIDENCE, _UNKNOWN_REASON_CONFLICTING_EVIDENCE}
                        ):
                            break

                verdict = evaluation["verdict"]
                unknown_reasons = set(evaluation["unknown_reasons"])
                fact_links = list(evaluation["fact_links"])
                fts_strength = float(evaluation["fts_strength"])
                model_score = float(evaluation["model_score"])
                confirmed_evidence_count = int(evaluation["confirmed_evidence_count"])
                if bool(evaluation["promoted"]) and req_stats is not None:
                    req_stats["layer3_promoted_ok_count"] = int(req_stats.get("layer3_promoted_ok_count", 0)) + 1
                _add_unknown_reasons(req_stats, unknown_reasons)

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
                    unknown_reasons=tuple(sorted(unknown_reasons)),
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
