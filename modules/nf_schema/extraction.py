from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.nf_consistency.extractors import ExtractionPipeline, normalize_extraction_profile
from modules.nf_consistency.extractors.contracts import ALLOWED_SLOT_KEYS, ExtractionMapping
from modules.nf_model_gateway.contracts import ModelGateway
from modules.nf_shared.protocol.dtos import SchemaType, TagDef, TagKind


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
    pipeline = ExtractionPipeline(
        profile=normalize_extraction_profile(profile),
        mappings=mappings or [],
        gateway=gateway,
    )
    result = pipeline.extract(text)

    if stats is not None:
        stats["rule_eval_ms"] = float(stats.get("rule_eval_ms", 0.0)) + float(result.rule_eval_ms)
        stats["model_eval_ms"] = float(stats.get("model_eval_ms", 0.0)) + float(result.model_eval_ms)
        stats["slot_matches"] = int(stats.get("slot_matches", 0)) + len(result.slots)
        stats["extractor_profile"] = pipeline.profile["mode"]
        stats["extractor_version"] = pipeline.version
        stats["ruleset_checksum"] = pipeline.ruleset_checksum
        stats["mapping_checksum"] = pipeline.mapping_checksum

    age_tag = _pick_tag(
        tag_defs,
        slot_key="age",
        schema_type=SchemaType.INT,
        keywords=("\ub098\uc774",),
    )
    if age_tag and "age" in result.slots:
        start, end, snippet, conf = _candidate_meta(result.candidates, "age")
        value = result.slots["age"]
        extracted.append(
            ExtractedFact(
                tag_def=age_tag,
                value=value,
                span_start=start,
                span_end=end,
                snippet_text=snippet or str(value),
                confidence=conf,
            )
        )

    time_tag = _pick_tag(
        tag_defs,
        slot_key="time",
        schema_type=SchemaType.TIME,
        keywords=("\uc2dc\uac04", "\uc2dc\uc810", "\ub0a0\uc9dc"),
    )
    if time_tag and "time" in result.slots:
        start, end, snippet, conf = _candidate_meta(result.candidates, "time")
        value = result.slots["time"]
        extracted.append(
            ExtractedFact(
                tag_def=time_tag,
                value=value,
                span_start=start,
                span_end=end,
                snippet_text=snippet or str(value),
                confidence=conf,
            )
        )

    place_tag = _pick_tag(
        tag_defs,
        slot_key="place",
        schema_type=SchemaType.LOC,
        keywords=("\uc7a5\uc18c", "\uc704\uce58"),
    )
    if place_tag and "place" in result.slots:
        start, end, snippet, conf = _candidate_meta(result.candidates, "place")
        value = result.slots["place"]
        extracted.append(
            ExtractedFact(
                tag_def=place_tag,
                value=value,
                span_start=start,
                span_end=end,
                snippet_text=snippet or str(value),
                confidence=conf,
            )
        )

    rel_tag = _pick_tag(
        tag_defs,
        slot_key="relation",
        schema_type=SchemaType.REL,
        keywords=("\uad00\uacc4",),
    )
    if rel_tag and "relation" in result.slots:
        start, end, snippet, conf = _candidate_meta(result.candidates, "relation")
        value = result.slots["relation"]
        extracted.append(
            ExtractedFact(
                tag_def=rel_tag,
                value=value,
                span_start=start,
                span_end=end,
                snippet_text=snippet or str(value),
                confidence=conf,
            )
        )

    affil_tag = _pick_tag(
        tag_defs,
        slot_key="affiliation",
        schema_type=SchemaType.STR,
        keywords=("\uc18c\uc18d",),
    )
    if affil_tag and "affiliation" in result.slots:
        start, end, snippet, conf = _candidate_meta(result.candidates, "affiliation")
        value = result.slots["affiliation"]
        extracted.append(
            ExtractedFact(
                tag_def=affil_tag,
                value=value,
                span_start=start,
                span_end=end,
                snippet_text=snippet or str(value),
                confidence=conf,
            )
        )

    job_tag = _pick_tag(
        tag_defs,
        slot_key="job",
        schema_type=SchemaType.STR,
        keywords=("\uc9c1\uc5c5", "\ud074\ub798\uc2a4"),
    )
    if job_tag and "job" in result.slots:
        start, end, snippet, conf = _candidate_meta(result.candidates, "job")
        value = result.slots["job"]
        extracted.append(
            ExtractedFact(
                tag_def=job_tag,
                value=value,
                span_start=start,
                span_end=end,
                snippet_text=snippet or str(value),
                confidence=conf,
            )
        )

    talent_tag = _pick_tag(
        tag_defs,
        slot_key="talent",
        schema_type=SchemaType.STR,
        keywords=("\uc7ac\ub2a5",),
    )
    if talent_tag and "talent" in result.slots:
        start, end, snippet, conf = _candidate_meta(result.candidates, "talent")
        value = result.slots["talent"]
        extracted.append(
            ExtractedFact(
                tag_def=talent_tag,
                value=value,
                span_start=start,
                span_end=end,
                snippet_text=snippet or str(value),
                confidence=conf,
            )
        )

    death_tag = _pick_tag(
        tag_defs,
        slot_key="death",
        schema_type=SchemaType.BOOL,
        keywords=("\uc0ac\ub9dd", "\uc0dd\uc874"),
    )
    if death_tag and "death" in result.slots:
        start, end, snippet, conf = _candidate_meta(result.candidates, "death")
        value = result.slots["death"]
        extracted.append(
            ExtractedFact(
                tag_def=death_tag,
                value=value,
                span_start=start,
                span_end=end,
                snippet_text=snippet or str(value),
                confidence=conf,
            )
        )

    return extracted
