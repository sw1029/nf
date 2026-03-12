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
        ExtractionRule(
            "age",
            r"(?:나이)(?:\s*[:]\s*|(?:은|는|이|가)\s*|\s+)(\d{1,3}\s*(?:살|세))",
            priority=200,
            transform="int",
            keywords=("나이",),
        ),
        ExtractionRule(
            "age",
            r"(?:(?:그|그녀|주인공|[A-Za-z\uac00-\ud7a3]{2,12})(?:은|는|이|가)\s*)(?:올해\s*)?(\d{1,3}\s*세)(?=(?:가\s*되었다|가\s*됐다|가\s*된다|였다|이다|입니다|이며|이고|$|[\"'”’)\]}!?.,]))",
            priority=198,
            transform="int",
            keywords=("세",),
        ),
        ExtractionRule(
            "age",
            r"(?:(?:그|그녀|주인공|[A-Za-z\uac00-\ud7a3]{2,12})(?:은|는|이|가)\s*)(\d{1,3}\s*살)(?=(?:의\b|였다|이다|입니다|$|[\"'”’)\]}!?.,]))",
            priority=197,
            transform="int",
            keywords=("살",),
        ),
        ExtractionRule(
            "age",
            r"(?:(?:그|그녀|주인공|[A-Za-z\uac00-\ud7a3]{2,12})(?:은|는|이|가)\s*)(\d{1,3}\s*세)(?=(?:였다|이다|입니다|이며|이고|$|[\"'”’)\]}!?.,]))",
            priority=196,
            transform="int",
            keywords=("세",),
        ),
        ExtractionRule(
            "time",
            r"(?:시간|시점|날짜)\s*(?:[:]|(?:은|는|이|가))\s*(\d{1,2}:\d{2}|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{1,2}월\s*\d{1,2}일)",
            priority=180,
            transform="strip",
            keywords=("시간", "시점", "날짜"),
        ),
        ExtractionRule(
            "time",
            r"\[(?:AM|PM\s*)?(\d{1,2}:\d{2})(?:\s*경)?\]",
            priority=178,
            transform="strip",
            keywords=("[", ":"),
        ),
        ExtractionRule(
            "time",
            r"\[(?:AM|PM\s*)?(\d{1,2}:\d{2})(?:\s*경)?(?:[.。]|(?=\]))",
            priority=177,
            transform="strip",
            keywords=("[", ":"),
        ),
        ExtractionRule(
            "place",
            r"^\s*(?:장소|위치)\s*(?:[:]|(?:은|는))\s*([^\n,.!?]{1,48}?)(?=(?:이었다|였다|이다)?(?:$|[\n,.!?]))",
            priority=170,
            transform="strip",
            keywords=("장소", "위치"),
        ),
        ExtractionRule(
            "relation",
            r"^\s*(?:관계)\s*(?:[:]|(?:은|는))\s*([^\n,.!?]{1,48}?)(?=(?:이었다|였다|이다)?(?:$|[\n,.!?]))",
            priority=165,
            transform="strip",
            keywords=("관계",),
        ),
        ExtractionRule(
            "affiliation",
            r"^\s*(?:소속)\s*(?:[:]|(?:은|는))\s*([^\n,.!?]{1,48}?)(?=(?:이었다|였다|이다)?(?:$|[\n,.!?]))",
            priority=165,
            transform="strip",
            keywords=("소속",),
        ),
        ExtractionRule(
            "affiliation",
            r"(?:(?:저|나|그|그녀|주인공)(?:는|은|이|가)\s+)?([A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 ]{1,24})\s+소속의\s+[A-Za-z\uac00-\ud7a3]{1,16}(?:입니다|이다|였다|였구나|였고|였으니|이자|이며)",
            priority=164,
            transform="strip",
            keywords=("소속",),
        ),
        ExtractionRule(
            "affiliation",
            r"(?:(?:저|나|그|그녀|주인공)(?:는|은|이|가)\s+)?([A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 ]{1,24})의\s+(?:제?\d+황녀|황녀|왕자|왕녀|공주)(?=(?:이자|이다|입니다|였다|였고|였으니|$|[\"'”’)\]}!?.,]))",
            priority=163,
            transform="strip",
            keywords=("황녀", "왕자", "왕녀", "공주"),
        ),
        ExtractionRule(
            "affiliation",
            r"(?:(?:저|나|그|그녀|주인공)(?:는|은|이|가)\s+)?([A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 ]{1,24})의\s+(?:제?\d+황녀|황녀|왕자|왕녀|공주)\s+[A-Za-z\uac00-\ud7a3]{2,12}",
            priority=162,
            transform="strip",
            keywords=("황녀", "왕자", "왕녀", "공주"),
        ),
        ExtractionRule(
            "affiliation",
            r"(?:(?:저|나|그|그녀|주인공)(?:는|은|이|가)\s+)?([A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 ]{1,24})의\s+[A-Za-z\uac00-\ud7a3]{2,12}(?=(?:이자|이다|입니다|였다|였고|였으니|$|[\"'”’)\]}!?.,]))",
            priority=161,
            transform="strip",
            keywords=(),
        ),
        ExtractionRule(
            "affiliation",
            r"(?:(?:저|나|그|그녀|주인공)(?:는|은|이|가)\s+)?([A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 ]{1,24})의\s+[A-Za-z\uac00-\ud7a3]{2,12}\s+[A-Za-z\uac00-\ud7a3]{2,12}",
            priority=160,
            transform="strip",
            keywords=(),
        ),
        ExtractionRule(
            "job",
            r"(?:직업|클래스)\s*(?:[:]|(?:은|는))\s*([^\n,.!?]{1,48}?)(?=(?:이었다|였다|이다|다)?(?:$|[\n,.!?]))",
            priority=160,
            transform="strip",
            keywords=("직업", "클래스"),
        ),
        ExtractionRule(
            "job",
            r"([A-Za-z\uac00-\ud7a3]{1,20})\s*클래스(?:였구나|였다|입니다|이다|이었(?:다|나)|였고|였으니|이니까)",
            priority=159,
            transform="strip",
            keywords=("클래스",),
        ),
        ExtractionRule(
            "job",
            r"(?:(?:저|나|그|그녀|주인공)(?:는|은|이|가)\s+)?(?:[A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 ]{1,24})\s+소속의\s+([A-Za-z\uac00-\ud7a3]{1,16})(?:입니다|이다|였다|였구나|였고|였으니|이자|이며)",
            priority=158,
            transform="strip",
            keywords=("소속",),
        ),
        ExtractionRule("job", r"(노\s*클래스)", priority=150, transform="strip", keywords=("노 클래스",)),
        ExtractionRule("job", r"(\d+\s*서클\s*마법사)", priority=145, transform="strip", keywords=("서클", "마법사")),
        ExtractionRule(
            "talent",
            r"^\s*(?:재능)\s*(?:[:]|(?:은|는))\s*([^\n,.!?]{1,48}?)(?=(?:이었다|였다|이다)?(?:$|[\n,.!?]))",
            priority=160,
            transform="strip",
            keywords=("재능",),
        ),
        ExtractionRule("talent", r"(재능\s*(?:이|은|는)?\s*없(?:음|다))", priority=150, transform="identity", keywords=("재능", "없")),
        ExtractionRule(
            "relation",
            r"(?:정체(?:는|가)\s*)?([A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 ]{0,24}의\s*(?:아들|딸|동생|형제|손녀딸|손자|사제|조력자|배신자))(?=(?:이었다|였다|이다|입니다|였고|였으니|$|[\"'”’)\]}!?.,]))",
            priority=139,
            transform="strip",
            keywords=("아들", "딸", "동생", "형제", "손녀딸", "손자", "사제", "조력자", "배신자"),
        ),
        ExtractionRule(
            "relation",
            r"(?:정체(?:는|가)\s*)([^\n,.!?]{1,24}의\s*(?:아들|딸|동생|형제|손녀딸|손자|사제|조력자|배신자))(?=(?:이었다|였다|이다|입니다|였고|였으니|$|[\"'”’)\]}!?.,]))",
            priority=138,
            transform="strip",
            keywords=("정체", "아들", "딸", "동생", "형제", "손녀딸", "손자", "사제", "조력자", "배신자"),
        ),
        ExtractionRule(
            "relation",
            r"([A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 ]{0,24}의\s*(?:아들|딸|동생|형제|손녀딸|손자))\s+[A-Za-z\uac00-\ud7a3]{2,12}",
            priority=137,
            transform="strip",
            keywords=("아들", "딸", "동생", "형제", "손녀딸", "손자"),
        ),
        ExtractionRule(
            "death",
            r"(?:(?:그|그녀|주인공|[A-Za-z\uac00-\ud7a3]{2,12})(?:은|는|이|가)\s*)((?:이미\s*)?(?:사망했다|사망한 상태다|사망함|죽었다|죽었어|죽었네))(?=(?:$|[\"'”’)\]}!?.,]))",
            priority=160,
            transform="death_flag",
            keywords=("사망", "죽었"),
        ),
        ExtractionRule(
            "death",
            r"(?:(?:그|그녀|주인공|[A-Za-z\uac00-\ud7a3]{2,12})(?:은|는|이|가)\s*)((?:아직\s*)?살아\s*있(?:다|음|네))(?=(?:$|[\"'”’)\]}!?.,]))",
            priority=150,
            transform="death_flag",
            keywords=("살아있", "살아 있"),
        ),
        ExtractionRule(
            "death",
            r"(생존\s*(?:중|했다|해\s*있다))",
            priority=145,
            transform="death_flag",
            keywords=("생존",),
        ),
    ]
