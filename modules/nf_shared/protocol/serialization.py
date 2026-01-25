from __future__ import annotations

import collections.abc
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, get_args, get_origin


def dump_json(obj: Any) -> Any:
    """
    Best-effort conversion to JSON-serializable structures.

    This is intentionally small and contract-focused (not a general serializer).
    """
    if obj is None:
        return None
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return {k: dump_json(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {dump_json(k): dump_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [dump_json(v) for v in obj]
    return obj


def load_json(tp: Any, data: Any) -> Any:
    """
    Minimal loader for contract DTOs.

    Supported:
    - dataclasses (including nested)
    - Enums (str -> Enum)
    - Optional[T], list[T], dict[K,V]
    """
    if data is None:
        return None

    origin = get_origin(tp)
    args = get_args(tp)

    # Optional[T] == Union[T, NoneType]
    if origin is None and hasattr(tp, "__args__") and getattr(tp, "__origin__", None) is None:
        # not a typing origin; continue
        pass

    if origin is list:
        (item_tp,) = args
        return [load_json(item_tp, v) for v in data]
    if origin in (dict, collections.abc.Mapping):
        key_tp, val_tp = args
        return {load_json(key_tp, k): load_json(val_tp, v) for k, v in data.items()}
    if origin is tuple:
        # tuple[T, ...] or tuple[T1, T2, ...]
        if len(args) == 2 and args[1] is Ellipsis:
            item_tp = args[0]
            return tuple(load_json(item_tp, v) for v in data)
        return tuple(load_json(t, v) for t, v in zip(args, data))
    if args and type(None) in args:
        non_none = next(a for a in args if a is not type(None))
        return load_json(non_none, data)

    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(data)

    if isinstance(tp, type) and is_dataclass(tp):
        kwargs: dict[str, Any] = {}
        for field in tp.__dataclass_fields__.values():  # type: ignore[attr-defined]
            kwargs[field.name] = load_json(field.type, data.get(field.name))
        return tp(**kwargs)

    return data
