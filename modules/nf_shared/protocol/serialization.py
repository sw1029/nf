from __future__ import annotations

import collections.abc
import dataclasses
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin


def dump_json(obj: Any) -> Any:
    """
    JSON 직렬화 가능한 구조로 최대한 변환한다.

    일반 범용 직렬화기가 아니라, 계약 중심의 최소 구현이다.
    """
    if obj is None:
        return None
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj):
        return {k: dump_json(v) for k, v in asdict(obj).items()}
    if isinstance(obj, collections.abc.Mapping):
        return {dump_json(k): dump_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [dump_json(v) for v in obj]
    return obj


def load_json(tp: Any, data: Any) -> Any:
    """
    계약 DTO용 최소 로더.

    지원:
    - dataclasses(중첩 포함)
    - Enums (str -> Enum)
    - Optional[T], list[T], dict[K,V]
    """
    if data is None:
        return None

    origin = get_origin(tp)
    args = get_args(tp)

    # Optional[T]는 Union[T, NoneType]과 동일
    if origin is None and hasattr(tp, "__args__") and getattr(tp, "__origin__", None) is None:
        # typing origin이 아님; 계속 진행
        pass

    if origin is list:
        (item_tp,) = args
        return [load_json(item_tp, v) for v in data]
    if origin in (dict, collections.abc.Mapping):
        key_tp, val_tp = args
        return {load_json(key_tp, k): load_json(val_tp, v) for k, v in data.items()}
    if origin is tuple:
        # tuple[T, ...] 또는 tuple[T1, T2, ...]
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
        for field in dataclasses.fields(tp):
            if isinstance(data, collections.abc.Mapping) and field.name in data:
                kwargs[field.name] = load_json(field.type, data.get(field.name))
            elif field.default is not dataclasses.MISSING:
                kwargs[field.name] = field.default
            elif field.default_factory is not dataclasses.MISSING:  # type: ignore[attr-defined]
                kwargs[field.name] = field.default_factory()  # type: ignore[misc]
            else:
                kwargs[field.name] = None
        return tp(**kwargs)

    return data
