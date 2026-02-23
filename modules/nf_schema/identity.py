from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from modules.nf_shared.protocol.dtos import Entity, EntityAlias


def build_alias_index(entities: Iterable[Entity], aliases: Iterable[EntityAlias]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for entity in entities:
        if entity.canonical_name:
            index[entity.canonical_name].add(entity.entity_id)
    for alias in aliases:
        if alias.alias_text:
            index[alias.alias_text].add(alias.entity_id)
    return dict(index)


def resolve_entity_id(tag_path: str, alias_index: dict[str, set[str]]) -> str | None:
    segments = [segment.strip() for segment in tag_path.split("/")]
    matched: set[str] = set()
    for segment in segments:
        matched.update(alias_index.get(segment, set()))
    if len(matched) == 1:
        return next(iter(matched))
    return None


def find_entity_candidates(text: str, alias_index: dict[str, set[str]]) -> set[str]:
    matched: set[str] = set()
    for alias_text, entity_ids in alias_index.items():
        if alias_text and alias_text in text:
            matched.update(entity_ids)
    return matched
