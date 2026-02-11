from __future__ import annotations

import re
from dataclasses import dataclass

from modules.nf_shared.protocol.dtos import SchemaType, TagDef, TagKind


@dataclass(frozen=True)
class ExtractedFact:
    tag_def: TagDef
    value: object
    span_start: int
    span_end: int
    snippet_text: str
    confidence: float


_AGE_RE = re.compile(r"(\d{1,3})\s*살")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{1,2}월\s*\d{1,2}일)")
_PLACE_RE = re.compile(r"(?:장소|위치)[:\s]+([^\n,.]+)")
_REL_RE = re.compile(r"(?:관계)[:\s]+([^\n,.]+)")
_AFFIL_RE = re.compile(r"(?:소속)[:\s]+([^\n,.]+)")
_JOB_RE = re.compile(r"(?:직업|클래스)[:\s]+([^\n,.]+)")
_TALENT_RE = re.compile(r"(?:재능)[:\s]+([^\n,.]+)")
_DEATH_RE = re.compile(r"(사망|죽었|죽었다|사망했다|사망함)")
_ALIVE_RE = re.compile(r"(생존|살아있)")


def _pick_tag(tag_defs: list[TagDef], schema_type: SchemaType, keywords: tuple[str, ...]) -> TagDef | None:
    for tag_def in tag_defs:
        if tag_def.kind not in (TagKind.EXPLICIT, TagKind.USER):
            continue
        if tag_def.schema_type is not schema_type:
            continue
        if any(keyword in tag_def.tag_path for keyword in keywords):
            return tag_def
    return None


def extract_explicit_candidates(text: str, tag_defs: list[TagDef]) -> list[ExtractedFact]:
    extracted: list[ExtractedFact] = []

    age_tag = _pick_tag(tag_defs, SchemaType.INT, ("나이",))
    if age_tag:
        match = _AGE_RE.search(text)
        if not match:
            match = re.search(r"(\d{1,3})\s*세", text)
        if match:
            extracted.append(
                ExtractedFact(
                    tag_def=age_tag,
                    value=int(match.group(1)),
                    span_start=match.start(),
                    span_end=match.end(),
                    snippet_text=match.group(0),
                    confidence=0.4,
                )
            )

    time_tag = _pick_tag(tag_defs, SchemaType.TIME, ("시간",))
    if time_tag:
        match = _TIME_RE.search(text)
        if match:
            extracted.append(
                ExtractedFact(
                    tag_def=time_tag,
                    value=match.group(1),
                    span_start=match.start(),
                    span_end=match.end(),
                    snippet_text=match.group(0),
                    confidence=0.3,
                )
            )

    place_tag = _pick_tag(tag_defs, SchemaType.LOC, ("장소", "위치"))
    if place_tag:
        match = _PLACE_RE.search(text)
        if match:
            extracted.append(
                ExtractedFact(
                    tag_def=place_tag,
                    value=match.group(1).strip(),
                    span_start=match.start(1),
                    span_end=match.end(1),
                    snippet_text=match.group(0),
                    confidence=0.3,
                )
            )

    rel_tag = _pick_tag(tag_defs, SchemaType.REL, ("관계",))
    if rel_tag:
        match = _REL_RE.search(text)
        if match:
            extracted.append(
                ExtractedFact(
                    tag_def=rel_tag,
                    value=match.group(1).strip(),
                    span_start=match.start(1),
                    span_end=match.end(1),
                    snippet_text=match.group(0),
                    confidence=0.3,
                )
            )

    affil_tag = _pick_tag(tag_defs, SchemaType.STR, ("소속",))
    if affil_tag:
        match = _AFFIL_RE.search(text)
        if match:
            extracted.append(
                ExtractedFact(
                    tag_def=affil_tag,
                    value=match.group(1).strip(),
                    span_start=match.start(1),
                    span_end=match.end(1),
                    snippet_text=match.group(0),
                    confidence=0.3,
                )
            )

    job_tag = _pick_tag(tag_defs, SchemaType.STR, ("직업", "클래스"))
    if job_tag:
        match = _JOB_RE.search(text)
        if match:
            extracted.append(
                ExtractedFact(
                    tag_def=job_tag,
                    value=match.group(1).strip(),
                    span_start=match.start(1),
                    span_end=match.end(1),
                    snippet_text=match.group(0),
                    confidence=0.3,
                )
            )
        else:
            # Narrative-style fallback for common phrases.
            if "노 클래스" in text:
                idx = text.find("노 클래스")
                extracted.append(
                    ExtractedFact(
                        tag_def=job_tag,
                        value="노 클래스",
                        span_start=idx,
                        span_end=idx + len("노 클래스"),
                        snippet_text="노 클래스",
                        confidence=0.2,
                    )
                )
            elif re.search(r"\d+\s*서클\s*마법사", text):
                m = re.search(r"(\d+\s*서클\s*마법사)", text)
                if m:
                    extracted.append(
                        ExtractedFact(
                            tag_def=job_tag,
                            value=m.group(1),
                            span_start=m.start(1),
                            span_end=m.end(1),
                            snippet_text=m.group(1),
                            confidence=0.2,
                        )
                    )

    talent_tag = _pick_tag(tag_defs, SchemaType.STR, ("재능",))
    if talent_tag:
        match = _TALENT_RE.search(text)
        if match:
            extracted.append(
                ExtractedFact(
                    tag_def=talent_tag,
                    value=match.group(1).strip(),
                    span_start=match.start(1),
                    span_end=match.end(1),
                    snippet_text=match.group(0),
                    confidence=0.3,
                )
            )
        else:
            if re.search(r"재능\s*없(음|다)", text):
                m = re.search(r"재능\s*없(음|다)", text)
                if m:
                    extracted.append(
                        ExtractedFact(
                            tag_def=talent_tag,
                            value="재능 없음",
                            span_start=m.start(),
                            span_end=m.end(),
                            snippet_text=m.group(0),
                            confidence=0.2,
                        )
                    )
            elif "천재" in text:
                idx = text.find("천재")
                extracted.append(
                    ExtractedFact(
                        tag_def=talent_tag,
                        value="천재",
                        span_start=idx,
                        span_end=idx + len("천재"),
                        snippet_text="천재",
                        confidence=0.2,
                    )
                )

    death_tag = _pick_tag(tag_defs, SchemaType.BOOL, ("사망",))
    if death_tag:
        match = _DEATH_RE.search(text)
        if match:
            extracted.append(
                ExtractedFact(
                    tag_def=death_tag,
                    value=True,
                    span_start=match.start(),
                    span_end=match.end(),
                    snippet_text=match.group(0),
                    confidence=0.3,
                )
            )
        else:
            match = _ALIVE_RE.search(text)
            if match:
                extracted.append(
                    ExtractedFact(
                        tag_def=death_tag,
                        value=False,
                        span_start=match.start(),
                        span_end=match.end(),
                        snippet_text=match.group(0),
                        confidence=0.2,
                    )
                )

    return extracted
