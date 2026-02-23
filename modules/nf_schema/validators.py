from __future__ import annotations

import re

from modules.nf_shared.protocol.dtos import SchemaType


def validate_tag_path(tag_path: str) -> None:
    if not tag_path or tag_path.strip() == "":
        raise ValueError("tag_path is empty")
    if tag_path.startswith("/") or tag_path.endswith("/"):
        raise ValueError("tag_path must not start/end with /")
    if "//" in tag_path:
        raise ValueError("tag_path must not contain empty segments")
    segments = [seg.strip() for seg in tag_path.split("/")]
    if any(not seg for seg in segments):
        raise ValueError("tag_path must not contain empty segments")


def validate_constraints(schema_type: SchemaType, constraints: dict) -> None:
    if schema_type is SchemaType.ENUM:
        choices = constraints.get("choices")
        if choices is None:
            raise ValueError("enum constraints require choices")
        if not isinstance(choices, list) or not all(isinstance(choice, str) for choice in choices):
            raise ValueError("choices must be list[str]")
    if schema_type in (SchemaType.INT, SchemaType.FLOAT):
        for key in ("min", "max"):
            if key in constraints and not isinstance(constraints[key], (int, float)):
                raise ValueError(f"{key} must be numeric")
    for key in ("min_length", "max_length"):
        if key in constraints and not isinstance(constraints[key], int):
            raise ValueError(f"{key} must be int")
    if "pattern" in constraints and not isinstance(constraints["pattern"], str):
        raise ValueError("pattern must be str")
    for key in ("required", "allow_null", "allow_empty"):
        if key in constraints and not isinstance(constraints[key], bool):
            raise ValueError(f"{key} must be bool")
    if "requires" in constraints:
        requires = constraints["requires"]
        if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
            raise ValueError("requires must be list[str]")


def _check_numeric_constraints(value: float, constraints: dict) -> None:
    if "min" in constraints and value < float(constraints["min"]):
        raise ValueError("value below min")
    if "max" in constraints and value > float(constraints["max"]):
        raise ValueError("value above max")


def validate_fact_value(schema_type: SchemaType, value: object, constraints: dict | None = None) -> None:
    constraints = constraints or {}
    if value is None:
        if constraints.get("allow_null"):
            return
        raise ValueError("value missing")
    if isinstance(value, str) and value.strip() == "":
        if constraints.get("allow_empty"):
            return
        raise ValueError("value empty")
    if schema_type is SchemaType.INT and not isinstance(value, int):
        raise ValueError("value must be int")
    if schema_type is SchemaType.FLOAT and not isinstance(value, (int, float)):
        raise ValueError("value must be float")
    if schema_type is SchemaType.BOOL and not isinstance(value, bool):
        raise ValueError("value must be bool")
    if schema_type in (SchemaType.STR, SchemaType.TIME, SchemaType.LOC, SchemaType.REL) and not isinstance(
        value, str
    ):
        raise ValueError("value must be str")
    if schema_type is SchemaType.INT:
        _check_numeric_constraints(float(value), constraints)
    if schema_type is SchemaType.FLOAT:
        _check_numeric_constraints(float(value), constraints)
    if schema_type in (SchemaType.STR, SchemaType.TIME, SchemaType.LOC, SchemaType.REL):
        min_len = constraints.get("min_length")
        if isinstance(min_len, int) and len(value) < min_len:
            raise ValueError("value shorter than min_length")
        max_len = constraints.get("max_length")
        if isinstance(max_len, int) and len(value) > max_len:
            raise ValueError("value longer than max_length")
        pattern = constraints.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            raise ValueError("value does not match pattern")
    if schema_type is SchemaType.ENUM:
        choices = constraints.get("choices", [])
        if value not in choices:
            raise ValueError("value not in choices")
