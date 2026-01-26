from __future__ import annotations

from pathlib import Path

from modules.nf_model_gateway.local.model_store import resolve_model_path


def load_model(path_or_id: str) -> object:
    resolved = resolve_model_path(path_or_id)
    path = resolved if resolved is not None else Path(path_or_id)
    return {"path": str(path), "resolved": resolved is not None}
