import pytest

from modules.nf_schema.extraction import extract_explicit_candidates
from modules.nf_schema.registry import default_tag_defs
from modules.nf_shared.protocol.dtos import TagDef


@pytest.mark.unit
def test_default_tag_defs_use_expected_slot_keys() -> None:
    tags = {str(item["tag_path"]): dict(item.get("constraints") or {}) for item in default_tag_defs()}

    assert tags["설정/인물/주인공/나이"]["slot_key"] == "age"
    assert tags["설정/인물/주인공/사망여부"]["slot_key"] == "death"
    assert tags["설정/인물/주인공/소속"]["slot_key"] == "affiliation"
    assert tags["설정/인물/주인공/직업"]["slot_key"] == "job"
    assert tags["설정/인물/주인공/재능"]["slot_key"] == "talent"
    assert tags["설정/인물/주인공/관계"]["slot_key"] == "relation"
    assert tags["설정/시간"]["slot_key"] == "time"
    assert tags["설정/장소"]["slot_key"] == "place"
    assert tags["설정/세계/분위기"] == {}


@pytest.mark.unit
def test_default_tag_defs_extract_affiliation_to_affiliation_tag() -> None:
    tag_defs = [
        TagDef(
            tag_id=f"tag:{idx}",
            project_id="project-1",
            tag_path=str(item["tag_path"]),
            kind=item["kind"],
            schema_type=item["schema_type"],
            constraints=dict(item.get("constraints") or {}),
        )
        for idx, item in enumerate(default_tag_defs())
    ]

    extracted = extract_explicit_candidates("소속: 사도련 백전귀(百戰鬼)", tag_defs)

    assert len(extracted) == 1
    assert extracted[0].tag_def.tag_path == "설정/인물/주인공/소속"
    assert extracted[0].value == "사도련"
