from __future__ import annotations

from collections import defaultdict
import re
from typing import Iterable
import unicodedata

from modules.nf_shared.protocol.dtos import Entity, EntityAlias

_WORD_TOKEN_RE = re.compile(r"[0-9A-Za-z\uac00-\ud7a3]+")
_SHORT_ALIAS_SUFFIXES = {
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "의",
    "에",
    "로",
    "으로",
    "에서",
    "에게",
    "도",
    "만",
    "께",
}
_BOUNDARY_CLASS = r"[0-9A-Za-z\uac00-\ud7a3]"


def normalize_alias_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = " ".join(normalized.strip().split())
    return normalized.lower()


def _query_token_set(text: str) -> set[str]:
    return {match.group(0) for match in _WORD_TOKEN_RE.finditer(text)}


def alias_matches_text(text: str, alias_text: str, *, normalize_input: bool = True) -> bool:
    query = normalize_alias_text(text) if normalize_input else text
    alias = normalize_alias_text(alias_text)
    if not query or not alias:
        return False

    query_tokens = _query_token_set(query)
    compact_alias = alias.replace(" ", "")
    if len(compact_alias) <= 2:
        if alias in query_tokens:
            return True
        if not query_tokens:
            return False
        for token in query_tokens:
            if not token.startswith(alias):
                continue
            suffix = token[len(alias) :]
            if suffix in _SHORT_ALIAS_SUFFIXES:
                return True
        return False

    boundary_pattern = rf"(?<!{_BOUNDARY_CLASS}){re.escape(alias)}(?!{_BOUNDARY_CLASS})"
    if re.search(boundary_pattern, query):
        return True

    alias_tokens = _query_token_set(alias)
    return bool(alias_tokens) and all(token in query_tokens for token in alias_tokens)


def build_alias_index(entities: Iterable[Entity], aliases: Iterable[EntityAlias]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for entity in entities:
        normalized = normalize_alias_text(entity.canonical_name)
        if normalized:
            index[normalized].add(entity.entity_id)
    for alias in aliases:
        normalized = normalize_alias_text(alias.alias_text)
        if normalized:
            index[normalized].add(alias.entity_id)
    return dict(index)


def resolve_entity_id(tag_path: str, alias_index: dict[str, set[str]]) -> str | None:
    segments = [segment.strip() for segment in tag_path.split("/")]
    matched: set[str] = set()
    for segment in segments:
        normalized = normalize_alias_text(segment)
        if normalized:
            matched.update(alias_index.get(normalized, set()))
        # Backward compatibility for non-normalized alias indexes.
        if segment:
            matched.update(alias_index.get(segment, set()))
    if len(matched) == 1:
        return next(iter(matched))
    return None


def find_entity_candidates(text: str, alias_index: dict[str, set[str]]) -> set[str]:
    matched: set[str] = set()
    normalized_text = normalize_alias_text(text)
    for alias_text, entity_ids in alias_index.items():
        if alias_matches_text(normalized_text, alias_text, normalize_input=False):
            matched.update(entity_ids)
    return matched
