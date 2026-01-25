from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class Settings:
    enable_remote_api: bool = False
    enable_layer3_model: bool = False
    enable_local_generator: bool = False  # 차순위(분기)

    sync_retrieval_mode: str = "FTS_ONLY"
    vector_index_mode: str = "SHARDED"

    max_loaded_shards: int = 2
    max_ram_mb: int = 2048

    evidence_required_for_model_output: bool = True
    implicit_fact_auto_approve: bool = False
    explicit_fact_auto_approve: bool = False  # 차순위(선택)


def load_config(path: Path | None = None) -> Mapping[str, Any]:
    """
    Load configuration (placeholder).

    Planned: central config schema and defaults shared across modules.
    """
    _ = path
    raise NotImplementedError("nf_shared.load_config is a placeholder.")
