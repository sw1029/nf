from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_VOLATILE_KEYS = {
    "job_id",
    "event_id",
    "ts",
    "timestamp",
    "started_at",
    "finished_at",
    "created_at",
    "updated_at",
    "elapsed_ms",
    "duration_ms",
}


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stable_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_obj(obj: Any) -> str:
    return hashlib.sha256(stable_dumps(obj).encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_semantic(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value.keys()):
            if key in _VOLATILE_KEYS:
                continue
            normalized[key] = normalize_semantic(value[key])
        return normalized
    if isinstance(value, list):
        return [normalize_semantic(item) for item in value]
    return value


def metrics_hash(metrics: dict[str, Any]) -> str:
    rounded: dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, float):
            rounded[key] = round(value, 4)
        else:
            rounded[key] = value
    return sha256_obj(rounded)


def coefficient_of_variation(values: list[float]) -> float:
    clean = [v for v in values if isinstance(v, (int, float))]
    if len(clean) < 2:
        return 0.0
    mean = sum(clean) / len(clean)
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in clean) / len(clean)
    return (variance ** 0.5) / mean


def get_git_sha(repo_root: Path | None = None) -> str:
    cwd = str(repo_root) if repo_root is not None else None
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, stderr=subprocess.DEVNULL)
    except Exception:
        return "unknown"
    return out.decode("utf-8", errors="ignore").strip() or "unknown"


def get_env_overrides(prefix: str = "NF_") -> dict[str, str]:
    items = {k: v for k, v in os.environ.items() if k.startswith(prefix)}
    return dict(sorted(items.items()))


def build_run_manifest(
    *,
    dataset_hash: str,
    config_snapshot: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "git_sha": get_git_sha(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "dataset_hash": dataset_hash,
        "env_overrides": get_env_overrides(),
        "created_at": now_ts(),
    }
    if config_snapshot:
        manifest["config_snapshot"] = config_snapshot
    if extra:
        manifest.update(extra)
    return manifest
