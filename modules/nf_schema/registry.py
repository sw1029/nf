from __future__ import annotations

from modules.nf_shared.protocol.dtos import SchemaType, TagKind


DEFAULT_TAG_DEFS = [
    {
        "tag_path": "설정/인물/주인공/나이",
        "kind": TagKind.EXPLICIT,
        "schema_type": SchemaType.INT,
        "constraints": {"min": 0},
    },
    {
        "tag_path": "설정/인물/주인공/사망여부",
        "kind": TagKind.EXPLICIT,
        "schema_type": SchemaType.BOOL,
        "constraints": {},
    },
    {
        "tag_path": "설정/인물/주인공/소속",
        "kind": TagKind.EXPLICIT,
        "schema_type": SchemaType.STR,
        "constraints": {},
    },
    {
        "tag_path": "설정/인물/주인공/관계",
        "kind": TagKind.EXPLICIT,
        "schema_type": SchemaType.REL,
        "constraints": {},
    },
    {
        "tag_path": "설정/시간",
        "kind": TagKind.EXPLICIT,
        "schema_type": SchemaType.TIME,
        "constraints": {},
    },
    {
        "tag_path": "설정/장소",
        "kind": TagKind.EXPLICIT,
        "schema_type": SchemaType.LOC,
        "constraints": {},
    },
    {
        "tag_path": "설정/세계/분위기",
        "kind": TagKind.IMPLICIT,
        "schema_type": SchemaType.STR,
        "constraints": {},
    },
]


def load_schema_registry() -> dict:
    """
    스키마 레지스트리 초기화(최소).
    """
    return {"default_tags": DEFAULT_TAG_DEFS}


def default_tag_defs() -> list[dict]:
    return list(DEFAULT_TAG_DEFS)
