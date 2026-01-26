from __future__ import annotations

from dataclasses import replace
from typing import Any

from modules.nf_schema.units import normalize_value
from modules.nf_shared.protocol.dtos import FactStatus, SchemaFact, SchemaType, TagDef


def _hashable(value: Any) -> Any:
    try:
        hash(value)
        return value
    except TypeError:
        return str(value)


def resolve_conflicts(facts: list[SchemaFact], tag_defs: list[TagDef]) -> list[SchemaFact]:
    tag_map = {tag.tag_path: tag for tag in tag_defs}
    existing_paths = {fact.tag_path for fact in facts}
    grouped: dict[tuple[str, str | None], list[SchemaFact]] = {}
    for fact in facts:
        key = (fact.tag_path, fact.entity_id)
        grouped.setdefault(key, []).append(fact)

    resolved: list[SchemaFact] = []
    for (tag_path, _entity_id), group in grouped.items():
        tag_def = tag_map.get(tag_path)
        schema_type = tag_def.schema_type if tag_def else SchemaType.UNKNOWN
        normalized_values = {_hashable(normalize_value(schema_type, fact.value)) for fact in group}
        if len(normalized_values) <= 1:
            resolved.extend(group)
            continue

        for fact in group:
            new_value = fact.value
            if schema_type in (SchemaType.STR, SchemaType.TIME, SchemaType.LOC, SchemaType.REL):
                new_value = "unknown"
            resolved.append(replace(fact, status=FactStatus.PROPOSED, value=new_value))

    gated: list[SchemaFact] = []
    for fact in resolved:
        tag_def = tag_map.get(fact.tag_path)
        schema_type = tag_def.schema_type if tag_def else SchemaType.UNKNOWN
        requires = tag_def.constraints.get("requires") if tag_def else None
        if isinstance(requires, list) and any(req not in existing_paths for req in requires):
            new_value = fact.value
            if schema_type in (SchemaType.STR, SchemaType.TIME, SchemaType.LOC, SchemaType.REL):
                new_value = "unknown"
            gated.append(replace(fact, status=FactStatus.PROPOSED, value=new_value))
        else:
            gated.append(fact)

    return gated
