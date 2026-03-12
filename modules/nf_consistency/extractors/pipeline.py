from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from typing import Any

from modules.nf_model_gateway.contracts import ModelGateway

from .contracts import (
    DEFAULT_MODEL_SLOTS,
    ExtractionCandidate,
    ExtractionMapping,
    ExtractionProfile,
    ExtractionResult,
    ExtractionRule,
    normalize_extraction_profile,
)
from .rule_extractor import RuleExtractor, builtin_rules


_CLAUSE_LIKE_SLOT_KEYS = {"place", "relation", "affiliation", "job", "talent"}
_LEADING_NOISE_TOKENS = {
    "그러자",
    "그리고",
    "하지만",
    "그저",
    "저놈이",
    "저에게",
    "이제",
    "처음",
}
_DESCRIPTIVE_PREFIX_SUFFIXES = (
    "하는",
    "하던",
    "되는",
    "된",
    "던",
    "린",
    "같은",
    "스러운",
)
_DESCRIPTIVE_NONFINAL_SUFFIXES = (
    "는",
    "하는",
    "되는",
    "했던",
    "하던",
    "하며",
    "하고",
    "해서",
    "같은",
    "있는",
    "없는",
    "중인",
    "에게",
    "에서",
    "으로",
    "까지",
    "부터",
    "명의",
)
_LOW_SIGNAL_FINAL_SUFFIXES = (
    "이었다",
    "였다",
    "이다",
    "했다",
    "한다",
    "된다",
    "됐다",
    "있다",
    "없다",
    "있었다",
    "없었다",
    "않았다",
    "않는다",
    "아니다",
    "아니었다",
    "싶다",
    "싶소",
    "겠지",
    "겠다",
    "거든",
    "는데",
    "지만",
    "라면",
    "라고",
    "라며",
    "일까",
    "를까",
    "구나",
    "나요",
    "까요",
    "리라",
    "않아",
    "습니다",
    "됩니다",
    "합니다",
    "해요",
    "예요",
    "군",
    "네",
    "아요",
    "어요",
    "으니",
    "으니까",
    "여도",
    "고",
)
_LOW_SIGNAL_TOKENS = {
    "수",
    "것",
    "편",
    "정도",
    "경우",
    "때문",
    "위해",
    "위한",
    "식",
    "바",
    "가지",
}
_AFFILIATION_SUFFIXES = (
    "제국",
    "왕국",
    "황궁",
    "길드",
    "협회",
    "연맹",
    "문파",
    "기사단",
    "경비대",
    "사단",
    "여단",
    "세가",
    "교",
    "단",
    "문",
    "련",
    "회",
    "파",
    "궁",
    "관",
    "당",
    "각",
)
_TIME_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIME_DATE_RE = re.compile(r"^(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일$")
_STANDALONE_BRACKETED_TIME_SEGMENT_RE = re.compile(r"^\s*\[(?:AM|PM\s*)?\d{1,2}:\d{2}(?:\s*경)?\]\s*$")
_TRAILING_TOKEN_RE = re.compile(r"^\s*[,，]?\s*([0-9A-Za-z\uac00-\ud7a3]{1,16})")
_RELATION_REPORTED_INTRO_TAIL_RE = re.compile(
    r"^[\s\"'“”‘’]*[,，]?\s*[0-9A-Za-z\uac00-\ud7a3]{2,20}(?:\s+[0-9A-Za-z\uac00-\ud7a3]{2,20}){0,2}"
    r"(?:입니다|이다|였다|이었(?:다|습니다|소|지|네)|이에요|예요|라고|라며|랍니다|라네|이랍니다)"
    r"(?=$|[\s,.!?\"'”’)\]}])"
)
_RELATION_TRAILING_BLOCKLIST = {
    "문제",
    "사건",
    "계획",
    "소문",
    "이야기",
    "일",
    "건",
    "관련",
    "기록",
    "쟁탈전",
    "토벌",
}
_GENERIC_AFFILIATION_TAIL_RE = re.compile(
    r"^의\s+([0-9A-Za-z\uac00-\ud7a3]{2,16})(?:\s+[0-9A-Za-z\uac00-\ud7a3]{2,16})?"
    r"(?=(?:이자|이다|입니다|였다|였고|였으니|$|[\"'”’)\]}!?.,]))"
)
_NON_GENERIC_AFFILIATION_TAIL_RE = re.compile(r"^의\s*(?:제?\d+황녀|황녀|왕자|왕녀|공주)")
_NON_GENERIC_AFFILIATION_TITLE_HEADS = {
    "황녀",
    "왕자",
    "왕녀",
    "공주",
}


def _checksum_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _split_candidate_tokens(value: object) -> list[str]:
    text = str(value or "").strip().lower()
    if not text:
        return []
    parts = re.split(r"[\s,./;:()\[\]{}<>|\"'“”‘’]+", text)
    tokens: list[str] = []
    for item in parts:
        cleaned = re.sub(r"[^0-9a-zA-Z\uac00-\ud7a3]+", "", item)
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _looks_descriptive_token(token: str) -> bool:
    if not token or token.endswith("의"):
        return False
    return any(token.endswith(suffix) for suffix in _DESCRIPTIVE_NONFINAL_SUFFIXES)


def _looks_clause_like_value(value: object) -> bool:
    tokens = _split_candidate_tokens(value)
    if not tokens:
        return True
    if tokens[0] in _LEADING_NOISE_TOKENS:
        return True
    if len(tokens) > 6:
        return True
    if len(tokens) == 1 and len(tokens[0]) == 1:
        return True
    if any(token in _LOW_SIGNAL_TOKENS for token in tokens[1:]):
        return True
    if any(_looks_descriptive_token(token) for token in tokens[:-1]):
        return True
    last = tokens[-1]
    return any(last.endswith(suffix) for suffix in _LOW_SIGNAL_FINAL_SUFFIXES)


def _has_descriptive_prefix_token(value: object) -> bool:
    tokens = _split_candidate_tokens(value)
    if len(tokens) < 2:
        return False
    first = tokens[0]
    if not first or first.endswith("의"):
        return False
    return any(first.endswith(suffix) for suffix in _DESCRIPTIVE_PREFIX_SUFFIXES)


def _segment_prefix_before_span(segment: str, span_start: int) -> str:
    start = max(0, int(span_start))
    prefix = str(segment or "")[:start].rstrip()
    if not prefix:
        return ""
    match = re.search(r"([0-9A-Za-z\uac00-\ud7a3]+)\s*$", prefix)
    if not match:
        return ""
    return str(match.group(1) or "")


def _has_descriptive_prefix_before_span(segment: str, span_start: int) -> bool:
    token = _segment_prefix_before_span(segment, span_start)
    if not token or token.endswith("의"):
        return False
    return any(token.endswith(suffix) for suffix in _DESCRIPTIVE_PREFIX_SUFFIXES)


def _relation_trailing_token(segment: str, span_end: int) -> str:
    tail = str(segment or "")[max(0, int(span_end)) :]
    match = _TRAILING_TOKEN_RE.match(tail)
    if not match:
        return ""
    return str(match.group(1) or "")


def _has_blocked_relation_tail(segment: str, span_end: int) -> bool:
    trailing = _relation_trailing_token(segment, span_end)
    return trailing in _RELATION_TRAILING_BLOCKLIST


def _has_reported_intro_relation_tail(segment: str, span_end: int) -> bool:
    tail = str(segment or "")[max(0, int(span_end)) :]
    return bool(_RELATION_REPORTED_INTRO_TAIL_RE.match(tail))


def _normalize_affiliation_value(value: object) -> object:
    raw = str(value or "").strip()
    if not raw:
        return value
    parts = [part for part in re.split(r"\s+", raw) if part]
    if len(parts) <= 1:
        return raw
    last_affiliation_idx = -1
    for idx, part in enumerate(parts):
        cleaned = re.sub(r"[^0-9a-zA-Z\uac00-\ud7a3]+", "", part)
        if cleaned and any(cleaned.endswith(suffix) for suffix in _AFFILIATION_SUFFIXES):
            last_affiliation_idx = idx
    if last_affiliation_idx < 0:
        return raw
    normalized = " ".join(parts[: last_affiliation_idx + 1]).strip()
    return normalized or raw


def _looks_like_affiliation_entity(value: object) -> bool:
    tokens = _split_candidate_tokens(value)
    if not tokens or len(tokens) > 4:
        return False
    last = tokens[-1]
    return any(last.endswith(suffix) for suffix in _AFFILIATION_SUFFIXES)


def _is_generic_narrative_affiliation_tail(tail: str) -> bool:
    normalized_tail = str(tail or "").strip()
    if _NON_GENERIC_AFFILIATION_TAIL_RE.match(normalized_tail):
        return False
    match = _GENERIC_AFFILIATION_TAIL_RE.match(normalized_tail)
    if not match:
        return False
    head = str(match.group(1) or "").strip()
    if not head:
        return False
    if head in _NON_GENERIC_AFFILIATION_TITLE_HEADS or head.endswith("황녀"):
        return False
    return True


def _is_valid_time_value(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if match := _TIME_CLOCK_RE.fullmatch(text):
        hour = int(match.group(1))
        minute = int(match.group(2))
        return 0 <= hour <= 23 and 0 <= minute <= 59
    if match := _TIME_DATE_RE.fullmatch(text):
        month = int(match.group(2))
        day = int(match.group(3))
        return 1 <= month <= 12 and 1 <= day <= 31
    return True


def _sanitize_candidate(
    candidate: ExtractionCandidate,
    *,
    segment: str = "",
    allow_generic_narrative_affiliation: bool = False,
) -> ExtractionCandidate | None:
    slot_key = str(candidate.slot_key or "")
    if slot_key == "time":
        if not _is_valid_time_value(candidate.value):
            return None
        if _STANDALONE_BRACKETED_TIME_SEGMENT_RE.fullmatch(str(segment or "")):
            return None
    if slot_key in _CLAUSE_LIKE_SLOT_KEYS and _looks_clause_like_value(candidate.value):
        return None
    if slot_key == "talent" and _has_descriptive_prefix_before_span(segment, candidate.span_start):
        return None
    if slot_key == "relation":
        if _has_blocked_relation_tail(segment, candidate.span_end):
            return None
        if _has_reported_intro_relation_tail(segment, candidate.span_end):
            return None
        if _has_descriptive_prefix_token(candidate.value):
            return None
    if slot_key == "affiliation":
        normalized = _normalize_affiliation_value(candidate.value)
        tail = str(segment or "")[max(0, int(candidate.span_end)) :].lstrip()
        allows_title_head_without_entity_suffix = bool(
            allow_generic_narrative_affiliation and _NON_GENERIC_AFFILIATION_TAIL_RE.match(tail)
        )
        if (
            tail.startswith("의")
            and not _looks_like_affiliation_entity(normalized)
            and not allows_title_head_without_entity_suffix
        ):
            return None
        if (
            not allow_generic_narrative_affiliation
            and tail.startswith("의")
            and _is_generic_narrative_affiliation_tail(tail)
        ):
            return None
        if str(normalized or "").strip() != str(candidate.value or "").strip():
            normalized_text = str(normalized or "").strip()
            matched_text = str(candidate.matched_text or "")
            span_end = candidate.span_end
            if normalized_text and matched_text.startswith(normalized_text):
                span_end = candidate.span_start + len(normalized_text)
                matched_text = normalized_text
            return ExtractionCandidate(
                slot_key=candidate.slot_key,
                value=normalized,
                confidence=candidate.confidence,
                source=candidate.source,
                span_start=candidate.span_start,
                span_end=span_end,
                matched_text=matched_text,
            )
    return candidate


def _sanitize_candidates(
    candidates: list[ExtractionCandidate],
    *,
    segment: str = "",
    allow_generic_narrative_affiliation: bool = False,
) -> list[ExtractionCandidate]:
    kept: list[ExtractionCandidate] = []
    for item in candidates:
        if item.source == "user_mapping":
            kept.append(item)
            continue
        sanitized = _sanitize_candidate(
            item,
            segment=segment,
            allow_generic_narrative_affiliation=allow_generic_narrative_affiliation,
        )
        if sanitized is not None:
            kept.append(sanitized)
    return kept


def _merge_candidates(candidates: list[ExtractionCandidate]) -> dict[str, object]:
    slots: dict[str, object] = {}
    for candidate in candidates:
        if candidate.slot_key in slots:
            continue
        slots[candidate.slot_key] = candidate.value
    return slots


class ExtractionPipeline:
    def __init__(
        self,
        *,
        profile: dict[str, Any] | ExtractionProfile | None = None,
        mappings: list[ExtractionMapping] | None = None,
        gateway: ModelGateway | None = None,
    ) -> None:
        self.profile: ExtractionProfile = normalize_extraction_profile(profile)
        self.version = "extractor_v2"
        self._gateway = gateway
        self._segment_cache: OrderedDict[str, ExtractionResult] = OrderedDict()
        self._cache_size = 1024

        self._builtin_extractor = RuleExtractor(builtin_rules())
        enabled_mappings = [item for item in (mappings or []) if item.enabled]
        mapping_rules = []
        for item in enabled_mappings:
            mapping_rules.append(
                ExtractionRule(
                    slot_key=item.slot_key,
                    pattern=item.pattern,
                    flags=item.flags,
                    priority=int(item.priority),
                    transform=item.transform,
                    keywords=(),
                )
            )
        self._mapping_extractor = RuleExtractor(mapping_rules) if mapping_rules else None
        self.ruleset_checksum = _checksum_payload([rule.pattern for rule in builtin_rules()])
        self.mapping_checksum = _checksum_payload(
            [
                {
                    "mapping_id": item.mapping_id,
                    "slot_key": item.slot_key,
                    "pattern": item.pattern,
                    "flags": item.flags,
                    "transform": item.transform,
                    "priority": item.priority,
                    "enabled": item.enabled,
                }
                for item in enabled_mappings
            ]
        )

    def extract(self, segment: str) -> ExtractionResult:
        normalized = " ".join(segment.split()).strip().lower()
        cached = self._segment_cache.get(normalized)
        if cached is not None:
            self._segment_cache.move_to_end(normalized)
            return cached

        rule_start = time.perf_counter()
        candidates: list[ExtractionCandidate] = []
        if self.profile["use_user_mappings"] and self._mapping_extractor is not None:
            candidates.extend(self._mapping_extractor.extract(segment, source="user_mapping", confidence=0.98))
        candidates.extend(self._builtin_extractor.extract(segment, source="rule", confidence=0.85))
        candidates = _sanitize_candidates(
            candidates,
            segment=segment,
            allow_generic_narrative_affiliation=bool(self.profile["allow_generic_narrative_affiliation"]),
        )
        candidates.sort(key=lambda item: (item.source != "user_mapping", -item.confidence))
        slots = _merge_candidates(candidates)
        rule_eval_ms = (time.perf_counter() - rule_start) * 1000.0

        model_eval_ms = 0.0
        mode = self.profile["mode"]
        if mode != "rule_only":
            missing_slots = [slot for slot in self.profile["model_slots"] if slot not in slots]
            if missing_slots:
                model_start = time.perf_counter()
                model_candidates: list[ExtractionCandidate] = []
                if mode in {"hybrid_local", "hybrid_dual"}:
                    model_candidates.extend(self._run_model_local(segment, missing_slots))
                if mode in {"hybrid_remote", "hybrid_dual"}:
                    remote_missing = [slot for slot in missing_slots if slot not in {c.slot_key for c in model_candidates}]
                    if remote_missing:
                        model_candidates.extend(self._run_model_remote(segment, remote_missing))
                model_candidates = _sanitize_candidates(
                    model_candidates,
                    segment=segment,
                    allow_generic_narrative_affiliation=bool(self.profile["allow_generic_narrative_affiliation"]),
                )
                for item in model_candidates:
                    if item.slot_key not in slots:
                        candidates.append(item)
                        slots[item.slot_key] = item.value
                model_eval_ms = (time.perf_counter() - model_start) * 1000.0

        result = ExtractionResult(
            slots=slots,
            candidates=candidates,
            rule_eval_ms=rule_eval_ms,
            model_eval_ms=model_eval_ms,
        )
        self._segment_cache[normalized] = result
        self._segment_cache.move_to_end(normalized)
        while len(self._segment_cache) > self._cache_size:
            self._segment_cache.popitem(last=False)
        return result

    def _run_model_local(self, segment: str, model_slots: list[str]) -> list[ExtractionCandidate]:
        if self._gateway is None:
            return []
        try:
            raw = self._gateway.extract_slots_local(
                {
                    "claim_text": segment,
                    "evidence": [],
                    "model_slots": list(model_slots or DEFAULT_MODEL_SLOTS),
                    "timeout_ms": int(self.profile["model_timeout_ms"]),
                }
            )
        except Exception:  # noqa: BLE001
            return []
        return self._from_model_candidates(raw, source="local_model")

    def _run_model_remote(self, segment: str, model_slots: list[str]) -> list[ExtractionCandidate]:
        if self._gateway is None:
            return []
        try:
            raw = self._gateway.extract_slots_remote(
                {
                    "claim_text": segment,
                    "evidence": [],
                    "model_slots": list(model_slots or DEFAULT_MODEL_SLOTS),
                    "timeout_ms": int(self.profile["model_timeout_ms"]),
                }
            )
        except Exception:  # noqa: BLE001
            return []
        return self._from_model_candidates(raw, source="remote_model")

    @staticmethod
    def _from_model_candidates(raw: list[dict[str, Any]] | None, *, source: str) -> list[ExtractionCandidate]:
        if not isinstance(raw, list):
            return []
        parsed: list[ExtractionCandidate] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            slot_key = item.get("slot_key")
            if not isinstance(slot_key, str):
                continue
            confidence_raw = item.get("confidence", 0.5)
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.5
            span_start = item.get("span_start", 0)
            span_end = item.get("span_end", 0)
            try:
                span_start_i = int(span_start)
            except (TypeError, ValueError):
                span_start_i = 0
            try:
                span_end_i = int(span_end)
            except (TypeError, ValueError):
                span_end_i = 0
            matched_text = item.get("matched_text")
            if not isinstance(matched_text, str):
                matched_text = str(item.get("value", ""))
            parsed.append(
                ExtractionCandidate(
                    slot_key=slot_key,
                    value=item.get("value"),
                    confidence=max(0.0, min(1.0, confidence)),
                    source=source,
                    span_start=max(0, span_start_i),
                    span_end=max(0, span_end_i),
                    matched_text=matched_text,
                )
            )
        return parsed
