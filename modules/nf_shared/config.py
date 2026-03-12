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
    enable_local_nli: bool = False
    enable_local_reranker: bool = False
    enable_test_judge_local_nli: bool = False
    enable_test_judge_remote_api: bool = False
    enable_local_generator: bool = False  # 李⑥닚??遺꾧린)
    enable_debug_web_ui: bool = False

    local_nli_model_id: str = 'nli-lite-v1'
    local_reranker_model_id: str = 'reranker-lite-v1'
    test_judge_local_nli_model_id: str = 'nli-lite-v1'
    test_judge_timeout_ms: int = 3000
    test_judge_min_confidence: float = 0.80

    sync_retrieval_mode: str = "FTS_ONLY"
    vector_index_mode: str = "SHARDED"
    vector_search_backend: str = "hashed_embedding"

    max_loaded_shards: int = 2
    max_ram_mb: int = 2048
    max_heavy_jobs: int = 1

    evidence_required_for_model_output: bool = True
    implicit_fact_auto_approve: bool = False
    explicit_fact_auto_approve: bool = False  # 李⑥닚???좏깮)
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
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return tomllib.loads(raw.decode("utf-8"))
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    raise ValueError(f"吏?먰븯吏 ?딅뒗 ?ㅼ젙 ?뺤떇: {path}")


def load_config(path: Path | str | None = None, *, env: Mapping[str, str] | None = None) -> Settings:
    """
    湲곕낯媛?+ ?좏깮 ?뚯씪 + ?섍꼍蹂???ㅻ쾭?쇱씠?쒕줈 ?ㅼ젙??濡쒕뱶?쒕떎.

    ?뚯씪 ?먯깋 ?쒖꽌:
    1) 紐낆떆 寃쎈줈(?쒓났??寃쎌슦)
    2) DEFAULT_CONFIG_PATHS 以?理쒖큹濡?議댁옱?섎뒗 寃쎈줈
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
