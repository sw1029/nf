from __future__ import annotations

import pytest

from modules.nf_schema.identity import build_alias_index, find_entity_candidates
from modules.nf_shared.protocol.dtos import Entity, EntityAlias, EntityKind, FactSource
from modules.nf_workers import runner


def _entity(entity_id: str, name: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        project_id="project-1",
        kind=EntityKind.CHAR,
        canonical_name=name,
        created_at="2026-03-02T00:00:00Z",
    )


def _alias(entity_id: str, text: str) -> EntityAlias:
    return EntityAlias(
        alias_id=f"alias-{entity_id}-{text}",
        project_id="project-1",
        entity_id=entity_id,
        alias_text=text,
        created_by=FactSource.USER,
        created_at="2026-03-02T00:00:00Z",
    )


@pytest.mark.unit
def test_find_entity_candidates_short_alias_does_not_match_inside_token() -> None:
    index = build_alias_index([_entity("entity-ai", "AI")], [])
    matched = find_entity_candidates("sailing scene", index)
    assert matched == set()


@pytest.mark.unit
def test_find_entity_candidates_short_alias_allows_particle_suffix() -> None:
    index = build_alias_index([_entity("entity-cheol", "철")], [])
    matched = find_entity_candidates("철은 도착했다.", index)
    assert matched == {"entity-cheol"}


@pytest.mark.unit
def test_find_entity_candidates_long_alias_requires_boundary_match() -> None:
    index = build_alias_index([_entity("entity-siro", "시로")], [_alias("entity-siro", "시로")])
    matched = find_entity_candidates("시로네는 웃었다.", index)
    assert matched == set()


@pytest.mark.unit
def test_extract_entity_mentions_reuses_strict_alias_boundary_rules() -> None:
    index = build_alias_index([_entity("entity-ai", "AI")], [])
    spans = [(0, 13, "sailing scene"), (14, 22, "AI는 왔다")]
    mentions = runner._extract_entity_mentions(spans, index)
    assert mentions == [("entity-ai", 14, 22)]
