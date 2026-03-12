from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

_MODEL_MANIFEST_FILENAME = "nf_model_manifest.json"
_HF_SEQUENCE_CLASSIFICATION_BACKEND = "hf_sequence_classification"
_WEIGHT_FILENAMES = (
    "model.safetensors",
    "pytorch_model.bin",
    "tf_model.h5",
    "model.bin",
)
_TOKENIZER_FILENAMES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "spiece.model",
    "sentencepiece.bpe.model",
)
_PAIR_TOKENIZER_FILENAMES = (
    ("vocab.json", "merges.txt"),
)


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


def read_model_manifest(model_path: Path) -> dict[str, Any]:
    manifest_path = Path(model_path) / _MODEL_MANIFEST_FILENAME
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def describe_model(model_id: str) -> dict[str, Any]:
    path = resolve_model_path(model_id)
    if path is None:
        return {
            "model_id": model_id,
            "path": None,
            "present": False,
            "manifest_backend": "",
            "runtime_ready": False,
            "reason": "missing",
        }
    return describe_model_path(path, model_id=model_id)


def describe_model_path(model_path: Path, *, model_id: str = "") -> dict[str, Any]:
    path = Path(model_path)
    manifest = read_model_manifest(path)
    backend = str(manifest.get("backend") or "").strip()
    config_path = path / "config.json"
    has_weight_file = any((path / filename).exists() for filename in _WEIGHT_FILENAMES)
    has_tokenizer_file = any((path / filename).exists() for filename in _TOKENIZER_FILENAMES) or any(
        (path / left).exists() and (path / right).exists() for left, right in _PAIR_TOKENIZER_FILENAMES
    )
    runtime_deps_ready = bool(importlib.util.find_spec("transformers")) and bool(importlib.util.find_spec("torch"))
    runtime_ready = (
        backend == _HF_SEQUENCE_CLASSIFICATION_BACKEND
        and config_path.exists()
        and has_weight_file
        and has_tokenizer_file
        and runtime_deps_ready
    )
    if runtime_ready:
        reason = "ok"
    elif not path.exists():
        reason = "missing"
    elif backend != _HF_SEQUENCE_CLASSIFICATION_BACKEND:
        reason = "manifest_missing_or_unsupported_backend"
    elif not runtime_deps_ready:
        reason = "runtime_dependency_missing"
    elif not config_path.exists():
        reason = "config_missing"
    elif not has_weight_file:
        reason = "weights_missing"
    elif not has_tokenizer_file:
        reason = "tokenizer_missing"
    else:
        reason = "unusable"
    return {
        "model_id": model_id,
        "path": path,
        "present": path.exists(),
        "manifest_backend": backend,
        "runtime_ready": runtime_ready,
        "reason": reason,
    }
