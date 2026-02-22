from __future__ import annotations

from dataclasses import dataclass

import pytest

from modules.nf_consistency import engine as consistency_engine


@dataclass(frozen=True)
class _TagDef:
    tag_path: str
    constraints: dict
    schema_type: object


@dataclass(frozen=True)
class _Fact:
    tag_path: str
    entity_id: str | None
    value: object
    evidence_eid: str


@pytest.mark.unit
def test_fact_slot_key_prefers_constraints_slot_key_over_tag_path() -> None:
    tag_def = _TagDef(
        tag_path="custom/path/without-keyword",
        constraints={"slot_key": "job"},
        schema_type="str",
    )
    slot_key = consistency_engine._fact_slot_key("custom/path/without-keyword", tag_def=tag_def)
    assert slot_key == "job"


@pytest.mark.unit
def test_build_fact_index_uses_tag_def_mapping_even_when_tag_path_changes() -> None:
    fact = _Fact(
        tag_path="renamed/tag/path",
        entity_id=None,
        value="wizard",
        evidence_eid="ev-1",
    )
    tag_def = _TagDef(
        tag_path="renamed/tag/path",
        constraints={"slot_key": "job"},
        schema_type="str",
    )
    index = consistency_engine._build_fact_index([fact], tag_defs=[tag_def])
    assert ("job", consistency_engine._FACT_ALL_KEY) in index
    assert index[("job", consistency_engine._FACT_ALL_KEY)][0].evidence_eid == "ev-1"
