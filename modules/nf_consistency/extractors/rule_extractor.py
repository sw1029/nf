from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .contracts import ExtractionCandidate, ExtractionRule


_FLAG_MAP = {
    "I": re.IGNORECASE,
    "M": re.MULTILINE,
    "S": re.DOTALL,
    "U": re.UNICODE,
    "A": re.ASCII,
}


def compile_regex_flags(flags: str) -> int:
    value = 0
    for ch in flags:
        value |= _FLAG_MAP.get(ch.upper(), 0)
    return value


def validate_regex_pattern(pattern: str) -> None:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty string")
    if len(pattern) > 256:
        raise ValueError("pattern is too long")
    # Guard against common catastrophic backtracking shapes.
    dangerous = (
        r"(.*)+",
        r"(.+)+",
        r"(.+)*",
        r"(.*)*",
        r"(?:.*)+",
        r"(?:.+)+",
    )
    lowered = pattern.replace(" ", "")
    for token in dangerous:
        if token in lowered:
            raise ValueError("pattern rejected due to unsafe nested quantifier")
    re.compile(pattern)


def _normalize_bool_from_text(text: str) -> bool | None:
    normalized = text.strip().lower()
    true_values = {"사망", "죽음", "죽었다", "죽었", "사망함", "사망했다"}
    false_values = {"생존", "살아있다", "살아있음", "살아있", "생존중"}
    if normalized in true_values:
        return True
    if normalized in false_values:
        return False
    return None


def apply_transform(value: str, transform: str) -> object:
    text = value.strip()
    mode = (transform or "identity").strip().lower()
    if mode in {"identity", "raw"}:
        return text
    if mode == "strip":
        return text
    if mode == "lower":
        return text.lower()
    if mode == "int":
        match = re.search(r"-?\d+", text)
        if not match:
            return text
        try:
            return int(match.group(0))
        except ValueError:
            return text
    if mode == "bool":
        parsed = _normalize_bool_from_text(text)
        return parsed if parsed is not None else text
    if mode == "death_flag":
        lowered = text.lower()
        if any(token in lowered for token in ("사망", "죽")):
            return True
        if any(token in lowered for token in ("생존", "살아있")):
            return False
        return text
    return text


@dataclass(frozen=True)
class _CompiledRule:
    slot_key: str
    regex: re.Pattern[str]
    priority: int
    transform: str
    keywords: tuple[str, ...]


class RuleExtractor:
    def __init__(self, rules: Iterable[ExtractionRule]) -> None:
        compiled: list[_CompiledRule] = []
        for rule in rules:
            validate_regex_pattern(rule.pattern)
            flags = compile_regex_flags(rule.flags)
            compiled.append(
                _CompiledRule(
                    slot_key=rule.slot_key,
                    regex=re.compile(rule.pattern, flags),
                    priority=rule.priority,
                    transform=rule.transform,
                    keywords=tuple(rule.keywords or ()),
                )
            )
        self._rules = sorted(compiled, key=lambda item: item.priority, reverse=True)

    def extract(self, segment: str, *, source: str, confidence: float) -> list[ExtractionCandidate]:
        if not segment:
            return []
        normalized = segment.lower()
        candidates: list[ExtractionCandidate] = []
        for rule in self._rules:
            if rule.keywords and not any(keyword in normalized for keyword in rule.keywords):
                continue
            match = rule.regex.search(segment)
            if not match:
                continue
            value_text = match.group(1) if match.lastindex else match.group(0)
            value = apply_transform(value_text, rule.transform)
            candidates.append(
                ExtractionCandidate(
                    slot_key=rule.slot_key,
                    value=value,
                    confidence=confidence,
                    source=source,
                    span_start=match.start(1) if match.lastindex else match.start(0),
                    span_end=match.end(1) if match.lastindex else match.end(0),
                    matched_text=value_text,
                )
            )
        return candidates


def builtin_rules() -> list[ExtractionRule]:
    return [
        ExtractionRule("age", r"(\d{1,3})\s*(?:살|세)", priority=200, transform="int", keywords=("살", "세")),
        ExtractionRule(
            "time",
            r"(\d{1,2}:\d{2}|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{1,2}월\s*\d{1,2}일)",
            priority=180,
            transform="strip",
            keywords=("년", "월", ":"),
        ),
        ExtractionRule(
            "place",
            r"(?:장소|위치)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)",
            priority=170,
            transform="strip",
            keywords=("장소", "위치"),
        ),
        ExtractionRule(
            "relation",
            r"(?:관계)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)",
            priority=165,
            transform="strip",
            keywords=("관계",),
        ),
        ExtractionRule(
            "affiliation",
            r"(?:소속)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)",
            priority=165,
            transform="strip",
            keywords=("소속",),
        ),
        ExtractionRule(
            "job",
            r"(?:직업|클래스)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)",
            priority=160,
            transform="strip",
            keywords=("직업", "클래스"),
        ),
        ExtractionRule("job", r"(노\s*클래스)", priority=150, transform="strip", keywords=("노 클래스",)),
        ExtractionRule("job", r"(\d+\s*서클\s*마법사)", priority=145, transform="strip", keywords=("서클", "마법사")),
        ExtractionRule(
            "talent",
            r"(?:재능)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)",
            priority=160,
            transform="strip",
            keywords=("재능",),
        ),
        ExtractionRule("talent", r"(재능\s*(?:이|은|는)?\s*없(?:음|다))", priority=150, transform="identity", keywords=("재능", "없")),
        ExtractionRule("talent", r"(천재)", priority=140, transform="strip", keywords=("천재",)),
        ExtractionRule("death", r"(사망|죽었|죽었다|사망했다|사망함)", priority=160, transform="death_flag", keywords=("사망", "죽")),
        ExtractionRule("death", r"(생존|살아있)", priority=150, transform="death_flag", keywords=("생존", "살아있")),
    ]

