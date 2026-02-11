from __future__ import annotations

import re
import unicodedata

_MAX_TERMS = 24
_MAX_TERM_CHARS = 48
_MAX_FALLBACK_CHARS = 180


def _normalize_text(text: object) -> str:
    if text is None:
        base = ""
    elif isinstance(text, str):
        base = text
    else:
        base = str(text)
    normalized = unicodedata.normalize("NFKC", base)
    normalized = re.sub(r"[\x00-\x1f\x7f]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _tokenize(text: object) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    raw_tokens = re.findall(r"\w+", normalized, flags=re.UNICODE)
    tokens: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        token = token.strip()
        if not token:
            continue
        if len(token) > _MAX_TERM_CHARS:
            token = token[:_MAX_TERM_CHARS]
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        tokens.append(token)
        if len(tokens) >= _MAX_TERMS:
            break
    return tokens


def _quote_term(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


def build_query(text: object) -> str:
    tokens = _tokenize(text)
    if not tokens:
        return ""
    # Quote every term to keep FTS5 parser-safe even when tokens resemble operators.
    return " OR ".join(_quote_term(token) for token in tokens)


def build_fallback_query(text: object) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    if len(normalized) > _MAX_FALLBACK_CHARS:
        normalized = normalized[:_MAX_FALLBACK_CHARS]
    return _quote_term(normalized)
