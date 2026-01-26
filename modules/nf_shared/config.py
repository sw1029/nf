from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping, get_type_hints


@dataclass(frozen=True)
class Settings:
    enable_remote_api: bool = False
    enable_layer3_model: bool = False
    enable_local_generator: bool = False  # 차순위(분기)
    enable_debug_web_ui: bool = False

    sync_retrieval_mode: str = "FTS_ONLY"
    vector_index_mode: str = "SHARDED"

    max_loaded_shards: int = 2
    max_ram_mb: int = 2048

    evidence_required_for_model_output: bool = True
    implicit_fact_auto_approve: bool = False
    explicit_fact_auto_approve: bool = False  # 차순위(선택)
    debug_web_ui_token: str = ""


DEFAULT_CONFIG_PATHS: tuple[Path, ...] = (
    Path("nf_config.toml"),
    Path("config/nf_config.toml"),
    Path("nf_config.json"),
    Path("config/nf_config.json"),
)

_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}
_FALSE_VALUES = {"0", "false", "no", "off", "n", "f"}


def _coerce(field_type: type[Any], raw: Any) -> Any:
    if raw is None:
        return None
    if field_type is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        lowered = str(raw).strip().lower()
        if lowered in _TRUE_VALUES:
            return True
        if lowered in _FALSE_VALUES:
            return False
        return bool(raw)
    if field_type is int:
        return int(raw)
    if field_type is str:
        return str(raw)
    return raw


def _load_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.suffix.lower() == ".toml":
        with path.open("rb") as fp:
            return tomllib.load(fp)
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    raise ValueError(f"지원하지 않는 설정 형식: {path}")


def load_config(path: Path | str | None = None, *, env: Mapping[str, str] | None = None) -> Settings:
    """
    기본값 + 선택 파일 + 환경변수 오버라이드로 설정을 로드한다.

    파일 탐색 순서:
    1) 명시 경로(제공된 경우)
    2) DEFAULT_CONFIG_PATHS 중 최초로 존재하는 경로
    """
    env_map: Mapping[str, str] = env or os.environ

    candidate_paths: tuple[Path, ...]
    if path is not None:
        candidate_paths = (Path(path),)
    else:
        candidate_paths = DEFAULT_CONFIG_PATHS

    raw: dict[str, Any] = {}
    for candidate in candidate_paths:
        if candidate.exists():
            raw = _load_file(candidate)
            break

    merged: dict[str, Any] = {}
    type_hints = get_type_hints(Settings)
    for field in fields(Settings):
        target_type = type_hints.get(field.name, field.type)
        if field.name in raw:
            merged[field.name] = raw[field.name]

        env_key = f"NF_{field.name.upper()}"
        if env_key in env_map:
            merged[field.name] = env_map[env_key]

        if field.name in merged:
            merged[field.name] = _coerce(target_type, merged[field.name])

    return Settings(**merged)
