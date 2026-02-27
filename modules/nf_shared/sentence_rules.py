from __future__ import annotations

import re
from typing import Any

SENTENCE_END_CHARS: tuple[str, ...] = (
    ".",
    "!",
    "?",
    "\n",
    "\u3002",
    "\uff01",
    "\uff1f",
    "\u2026",
    "\uff0e",
)
SENTENCE_TAIL_CHARS: tuple[str, ...] = (
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
)
SENTENCE_ABBREVIATION_TOKENS: tuple[str, ...] = (
    "a.m.",
    "cf.",
    "co.",
    "dr.",
    "e.g.",
    "etc.",
    "fig.",
    "i.e.",
    "inc.",
    "jr.",
    "ltd.",
    "mr.",
    "mrs.",
    "ms.",
    "no.",
    "p.m.",
    "prof.",
    "sr.",
    "st.",
    "u.k.",
    "u.s.",
    "vs.",
)
SENTENCE_DECIMAL_GUARD = True
SENTENCE_ORDINAL_GUARD = True
SENTENCE_MAX_TAIL_SCAN = 24

_ABBREVIATION_LOOKUP = {token.lower() for token in SENTENCE_ABBREVIATION_TOKENS}
_ORDINAL_PATTERN = re.compile(r"\d+(st|nd|rd|th)\.$", re.IGNORECASE)
_INITIAL_PATTERN = re.compile(r"[a-z]\.$", re.IGNORECASE)


def build_sentence_rules_payload() -> dict[str, Any]:
    return {
        "end_chars": list(SENTENCE_END_CHARS),
        "tail_chars": list(SENTENCE_TAIL_CHARS),
        "abbreviation_tokens": list(SENTENCE_ABBREVIATION_TOKENS),
        "decimal_guard": SENTENCE_DECIMAL_GUARD,
        "ordinal_guard": SENTENCE_ORDINAL_GUARD,
        "max_tail_scan": SENTENCE_MAX_TAIL_SCAN,
    }


def is_decimal_boundary(text: str, idx: int) -> bool:
    if not SENTENCE_DECIMAL_GUARD:
        return False
    if idx <= 0 or idx >= len(text) - 1:
        return False
    return text[idx - 1].isdigit() and text[idx + 1].isdigit()


def is_abbreviation_boundary(text: str, idx: int) -> bool:
    if idx < 0 or idx >= len(text) or text[idx] != ".":
        return False

    token_start = idx - 1
    while token_start >= 0 and (
        text[token_start].isalnum() or text[token_start] in {"_", "."}
    ):
        token_start -= 1
    token = text[token_start + 1 : idx + 1].strip().lower()
    if not token:
        return False
    if token in _ABBREVIATION_LOOKUP:
        return True
    if SENTENCE_ORDINAL_GUARD and _ORDINAL_PATTERN.fullmatch(token):
        return True
    if _INITIAL_PATTERN.fullmatch(token):
        next_idx = idx + 1
        if next_idx < len(text):
            next_char = text[next_idx]
            if next_char.isalpha() and next_char.isupper():
                return True
    return False
