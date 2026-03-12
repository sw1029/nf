from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from modules.nf_consistency.extractors import ExtractionPipeline, normalize_extraction_profile
from modules.nf_consistency.extractors.contracts import ALLOWED_SLOT_KEYS, ExtractionMapping
from modules.nf_model_gateway.contracts import ModelGateway
from modules.nf_shared.protocol.dtos import SchemaType, TagDef, TagKind


_DESCRIPTIVE_HEAD_SLOT_KEYS = {"relation", "affiliation", "job", "talent"}
_DESCRIPTIVE_TOKEN_SUFFIXES = (
    "는",
    "하는",
    "되는",
    "했던",
    "하던",
    "하다",
    "했다",
    "하며",
    "하고",
    "해서",
    "같은",
    "있는",
    "없는",
    "중인",
)
_EXPLICIT_SLOT_PREFIXES: dict[str, tuple[str, ...]] = {
    "age": ("나이", "연령", "age"),
    "time": ("시간", "시점", "날짜", "time", "date"),
    "place": ("장소", "위치", "place", "location"),
    "relation": ("관계", "relation"),
    "affiliation": ("소속", "affiliation"),
    "job": ("직업", "클래스", "job", "class"),
    "talent": ("재능", "talent"),
    "death": ("사망", "생존", "death", "alive"),
}
_STANDALONE_EXPLICIT_VALUES: dict[str, tuple[str, ...]] = {
    "job": ("노 클래스",),
    "talent": ("천재", "재능 없음"),
    "death": ("사망", "생존"),
}
_NARRATIVE_RELATION_RE = re.compile(r"의\s*(?:아들|딸|동생|형제|손녀딸|손자|사제|조력자|배신자)")
_NARRATIVE_AFFILIATION_RE = re.compile(r"(?:소속의|의\s*(?:제?\d+황녀|황녀|왕자|왕녀|공주))")
_NARRATIVE_GENERIC_AFFILIATION_RE = re.compile(
    r"의\s+[A-Za-z\uac00-\ud7a3]{2,12}(?=(?:이자|이다|입니다|였다|였고|였으니|$|[\"'”’)\]}!?.,]))"
)
_NARRATIVE_GENERIC_AFFILIATION_APPOSITIVE_RE = re.compile(
    r"의\s+[A-Za-z\uac00-\ud7a3]{2,12}\s+[A-Za-z\uac00-\ud7a3]{2,12}"
)
_AFFILIATION_ENTITY_SUFFIXES = (
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


@dataclass(frozen=True)
class ExtractedFact:
    tag_def: TagDef
    value: object
    span_start: int
    span_end: int
    snippet_text: str
    confidence: float


def _tag_slot_key(tag_def: TagDef) -> str | None:
    constraints = tag_def.constraints or {}
    if not hasattr(constraints, "get"):
        return None
    raw = constraints.get("slot_key")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().lower()
    if normalized in ALLOWED_SLOT_KEYS:
        return normalized
    return None


def _pick_tag(
    tag_defs: list[TagDef],
    *,
    slot_key: str,
    schema_type: SchemaType,
    keywords: tuple[str, ...],
) -> TagDef | None:
    for tag_def in tag_defs:
        if tag_def.kind not in (TagKind.EXPLICIT, TagKind.USER):
            continue
        if _tag_slot_key(tag_def) == slot_key:
            return tag_def

    for tag_def in tag_defs:
        if tag_def.kind not in (TagKind.EXPLICIT, TagKind.USER):
            continue
        if tag_def.schema_type is not schema_type:
            continue
        if any(keyword in tag_def.tag_path for keyword in keywords):
            return tag_def
    return None


def _candidate_meta(result_candidates, slot_key: str) -> tuple[int, int, str, float]:
    for item in result_candidates:
        if item.slot_key != slot_key:
            continue
        return item.span_start, item.span_end, item.matched_text, item.confidence
    return 0, 0, "", 0.3


def _split_head_phrase_tokens(value: object) -> list[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return []
    parts = re.split(r"[\s,./;:()\[\]{}<>|]+", raw)
    tokens: list[str] = []
    for item in parts:
        cleaned = re.sub(r"[^0-9a-zA-Z\uac00-\ud7a3]+", "", item)
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _is_descriptive_head_phrase(slot_key: str, value: object) -> bool:
    if slot_key not in _DESCRIPTIVE_HEAD_SLOT_KEYS:
        return False
    tokens = _split_head_phrase_tokens(value)
    if len(tokens) < 2:
        return False
    if any(token.endswith("의") for token in tokens[:-1]):
        return False
    return any(token.endswith(suffix) for token in tokens[:-1] for suffix in _DESCRIPTIVE_TOKEN_SUFFIXES)


def _iter_lines_with_offsets(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    cursor = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if line.strip():
            lines.append((cursor, line))
        cursor += len(raw_line)
    if not lines and text.strip():
        lines.append((0, text))
    return lines


def _normalize_explicit_line(line: str) -> str:
    stripped = line.strip()
    stripped = re.sub(r"^[\-\*\u2022]+\s*", "", stripped)
    return stripped


def _looks_like_affiliation_entity(value: object) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return False
    parts = re.split(r"[\s,./;:()\[\]{}<>|\"'“”‘’]+", raw)
    tokens = [re.sub(r"[^0-9a-zA-Z\uac00-\ud7a3]+", "", item) for item in parts if item]
    tokens = [item for item in tokens if item]
    if not tokens or len(tokens) > 4:
        return False
    return any(tokens[-1].endswith(suffix) for suffix in _AFFILIATION_ENTITY_SUFFIXES)


def _explicit_slots_for_line(line: str) -> set[str]:
    normalized = _normalize_explicit_line(line)
    lowered = normalized.lower()
    allowed: set[str] = set()
    for slot_key, prefixes in _EXPLICIT_SLOT_PREFIXES.items():
        if any(lowered.startswith(prefix.lower()) for prefix in prefixes):
            allowed.add(slot_key)
    for slot_key, values in _STANDALONE_EXPLICIT_VALUES.items():
        if lowered in {value.lower() for value in values}:
            allowed.add(slot_key)
    return allowed


def _narrative_slots_for_line(line: str, result) -> set[str]:  # noqa: ANN001
    allowed: set[str] = set()
    normalized = _normalize_explicit_line(line)
    if "relation" in result.slots and _NARRATIVE_RELATION_RE.search(normalized):
        allowed.add("relation")
    if "affiliation" in result.slots:
        affiliation_value = result.slots.get("affiliation")
        if _NARRATIVE_AFFILIATION_RE.search(normalized):
            allowed.add("affiliation")
        elif _looks_like_affiliation_entity(affiliation_value) and (
            _NARRATIVE_GENERIC_AFFILIATION_RE.search(normalized)
            or _NARRATIVE_GENERIC_AFFILIATION_APPOSITIVE_RE.search(normalized)
        ):
            allowed.add("affiliation")
    if "job" in result.slots and "affiliation" in result.slots and "소속의" in normalized:
        allowed.add("job")
    return allowed


def _best_candidate_for_slot(candidates, slot_key: str):
    best = None
    best_score = -1.0
    for item in candidates:
        if item.slot_key != slot_key:
            continue
        score = float(getattr(item, "confidence", 0.0))
        if score > best_score:
            best = item
            best_score = score
    return best


def _tag_defs_by_slot(tag_defs: list[TagDef]) -> dict[str, TagDef]:
    tag_map: dict[str, TagDef] = {}
    slot_specs = (
        ("age", SchemaType.INT, ("나이",)),
        ("time", SchemaType.TIME, ("시간", "시점", "날짜")),
        ("place", SchemaType.LOC, ("장소", "위치")),
        ("relation", SchemaType.REL, ("관계",)),
        ("affiliation", SchemaType.STR, ("소속",)),
        ("job", SchemaType.STR, ("직업", "클래스")),
        ("talent", SchemaType.STR, ("재능",)),
        ("death", SchemaType.BOOL, ("사망", "생존")),
    )
    for slot_key, schema_type, keywords in slot_specs:
        tag_def = _pick_tag(tag_defs, slot_key=slot_key, schema_type=schema_type, keywords=keywords)
        if tag_def is not None:
            tag_map[slot_key] = tag_def
    return tag_map


def extract_explicit_candidates(
    text: str,
    tag_defs: list[TagDef],
    *,
    profile: dict[str, Any] | None = None,
    mappings: list[ExtractionMapping] | None = None,
    gateway: ModelGateway | None = None,
    stats: dict[str, Any] | None = None,
) -> list[ExtractedFact]:
    extracted: list[ExtractedFact] = []
    normalized_profile = normalize_extraction_profile(profile)
    normalized_profile["allow_generic_narrative_affiliation"] = True
    pipeline = ExtractionPipeline(
        profile=normalized_profile,
        mappings=mappings or [],
        gateway=gateway,
    )
    if stats is not None:
        stats["extractor_profile"] = pipeline.profile["mode"]
        stats["extractor_version"] = pipeline.version
        stats["ruleset_checksum"] = pipeline.ruleset_checksum
        stats["mapping_checksum"] = pipeline.mapping_checksum

    tag_defs_by_slot = _tag_defs_by_slot(tag_defs)
    line_candidates = _iter_lines_with_offsets(text)
    for line_start, line_text in line_candidates:
        result = pipeline.extract(line_text)
        allowed_slots = _explicit_slots_for_line(line_text)
        allowed_slots.update(_narrative_slots_for_line(line_text, result))
        if not allowed_slots:
            continue
        if stats is not None:
            stats["rule_eval_ms"] = float(stats.get("rule_eval_ms", 0.0)) + float(result.rule_eval_ms)
            stats["model_eval_ms"] = float(stats.get("model_eval_ms", 0.0)) + float(result.model_eval_ms)
            stats["slot_matches"] = int(stats.get("slot_matches", 0)) + len(result.slots)
        for slot_key in allowed_slots:
            tag_def = tag_defs_by_slot.get(slot_key)
            if tag_def is None or slot_key not in result.slots:
                continue
            candidate = _best_candidate_for_slot(result.candidates, slot_key)
            if candidate is None:
                continue
            value = result.slots[slot_key]
            if _is_descriptive_head_phrase(slot_key, value):
                continue
            rel_start = int(candidate.span_start)
            rel_end = int(candidate.span_end)
            extracted.append(
                ExtractedFact(
                    tag_def=tag_def,
                    value=value,
                    span_start=line_start + rel_start,
                    span_end=line_start + rel_end,
                    snippet_text=candidate.matched_text or str(value),
                    confidence=float(candidate.confidence),
                )
            )

    return extracted
