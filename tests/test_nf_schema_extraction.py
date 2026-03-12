from __future__ import annotations

import pytest

from modules.nf_schema.extraction import extract_explicit_candidates
from modules.nf_shared.protocol.dtos import SchemaType, TagDef, TagKind


def _tag_def(*, tag_path: str, slot_key: str, schema_type: SchemaType) -> TagDef:
    return TagDef(
        tag_id=f"tag:{slot_key}",
        project_id="project-1",
        tag_path=tag_path,
        kind=TagKind.EXPLICIT,
        schema_type=schema_type,
        constraints={"slot_key": slot_key},
    )


@pytest.mark.unit
def test_extract_explicit_candidates_rejects_descriptive_relation_phrase() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/관계",
            slot_key="relation",
            schema_type=SchemaType.REL,
        )
    ]
    extracted = extract_explicit_candidates(
        "관계: 주인공을 돕는 조력자, 다음 문장",
        tag_defs,
    )

    assert extracted == []


@pytest.mark.unit
def test_extract_explicit_candidates_keeps_possessive_relation_phrase() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/관계",
            slot_key="relation",
            schema_type=SchemaType.REL,
        )
    ]
    extracted = extract_explicit_candidates(
        "관계: 주인공의 동생, 다음 문장",
        tag_defs,
    )

    assert len(extracted) == 1
    assert extracted[0].value == "주인공의 동생"


@pytest.mark.unit
def test_extract_explicit_candidates_rejects_descriptive_job_phrase() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/직업",
            slot_key="job",
            schema_type=SchemaType.STR,
        )
    ]
    extracted = extract_explicit_candidates(
        "직업: 사람을 돕는 조력자, 다음 문장",
        tag_defs,
    )

    assert extracted == []


@pytest.mark.unit
def test_extract_explicit_candidates_requires_explicit_line_prefix_for_schema_fact() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/직업",
            slot_key="job",
            schema_type=SchemaType.STR,
        )
    ]
    extracted = extract_explicit_candidates(
        "그의 직업은 마법사다.",
        tag_defs,
    )

    assert extracted == []


@pytest.mark.unit
def test_extract_explicit_candidates_accepts_keyword_led_line_with_copula() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/직업",
            slot_key="job",
            schema_type=SchemaType.STR,
        )
    ]
    extracted = extract_explicit_candidates(
        "직업은 마법사다.",
        tag_defs,
    )

    assert len(extracted) == 1
    assert extracted[0].value == "마법사"


@pytest.mark.unit
def test_extract_explicit_candidates_accepts_narrative_relation_identity_phrase() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/관계",
            slot_key="relation",
            schema_type=SchemaType.REL,
        )
    ]
    extracted = extract_explicit_candidates(
        "그의 정체는 고 유명찬 공의 손녀딸이었다.",
        tag_defs,
    )

    assert len(extracted) == 1
    assert extracted[0].value == "고 유명찬 공의 손녀딸"


@pytest.mark.unit
def test_extract_explicit_candidates_accepts_narrative_affiliation_title_phrase() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/소속",
            slot_key="affiliation",
            schema_type=SchemaType.STR,
        )
    ]
    extracted = extract_explicit_candidates(
        "라인시스 제국의 제1황녀이자, 제국의 유일한 희망이었던 자.",
        tag_defs,
    )

    assert len(extracted) == 1
    assert extracted[0].value == "라인시스 제국"


@pytest.mark.unit
def test_extract_explicit_candidates_accepts_narrative_affiliation_title_phrase_without_suffix_entity() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/소속",
            slot_key="affiliation",
            schema_type=SchemaType.STR,
        )
    ]
    extracted = extract_explicit_candidates(
        "그녀는 라인시스의 제1황녀였다.",
        tag_defs,
    )

    assert len(extracted) == 1
    assert extracted[0].value == "라인시스"


@pytest.mark.unit
def test_extract_explicit_candidates_accepts_generic_narrative_affiliation_org_title_phrase() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/소속",
            slot_key="affiliation",
            schema_type=SchemaType.STR,
        )
    ]
    extracted = extract_explicit_candidates(
        "그는 사도련의 백전귀였다.",
        tag_defs,
    )

    assert len(extracted) == 1
    assert extracted[0].value == "사도련"


@pytest.mark.unit
def test_extract_explicit_candidates_accepts_narrative_job_from_affiliation_phrase() -> None:
    tag_defs = [
        _tag_def(
            tag_path="설정/인물/주인공/직업",
            slot_key="job",
            schema_type=SchemaType.STR,
        )
    ]
    extracted = extract_explicit_candidates(
        "저는 황궁 소속의 시녀입니다.",
        tag_defs,
    )

    assert len(extracted) == 1
    assert extracted[0].value == "시녀"
