from __future__ import annotations

import re

from modules.nf_shared.protocol.dtos import SchemaType

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_TRUE_VALUES = {"true", "yes", "y", "1"}
_FALSE_VALUES = {"false", "no", "n", "0"}


def normalize_value(schema_type: SchemaType, value: object) -> object:
    if value is None:
        return None

    if schema_type is SchemaType.INT:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            match = _NUMBER_RE.search(value)
            if match:
                return int(float(match.group(0)))
        return value

    if schema_type is SchemaType.FLOAT:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = _NUMBER_RE.search(value)
            if match:
                return float(match.group(0))
        return value

    if schema_type is SchemaType.BOOL:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _TRUE_VALUES:
                return True
            if lowered in _FALSE_VALUES:
                return False
        return value

    if schema_type in (SchemaType.STR, SchemaType.TIME, SchemaType.LOC, SchemaType.REL):
        if isinstance(value, str):
            return value.strip()
        return value

    return value
