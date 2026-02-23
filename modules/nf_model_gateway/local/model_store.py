from __future__ import annotations

import os
from pathlib import Path


def model_store_root() -> Path:
    return Path(os.environ.get("NF_MODEL_STORE", "data/models"))


def resolve_model_path(model_id: str) -> Path | None:
    root = model_store_root()
    candidate = root / model_id
    if candidate.exists():
        return candidate
    return None


def ensure_model(model_id: str) -> Path | None:
    return resolve_model_path(model_id)
