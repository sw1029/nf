from __future__ import annotations

import hashlib
import os
from pathlib import Path


DEFAULT_DOCSTORE_PATH = Path(os.environ.get("NF_DOCSTORE_PATH", "data/docstore"))
DEFAULT_EXPORT_PATH = Path(os.environ.get("NF_EXPORT_PATH", "data/exports"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def checksum_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def write_raw_text(project_id: str, doc_id: str, *, version: int, text: str) -> Path:
    base = DEFAULT_DOCSTORE_PATH / project_id / doc_id
    ensure_dir(base)
    path = base / f"raw_v{version}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def write_snapshot_text(
    project_id: str,
    doc_id: str,
    *,
    snapshot_id: str,
    version: int,
    text: str,
) -> Path:
    base = DEFAULT_DOCSTORE_PATH / project_id / doc_id
    ensure_dir(base)
    path = base / f"snapshot_{version}_{snapshot_id}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def export_path(project_id: str, job_id: str | None, filename: str) -> Path:
    base = DEFAULT_EXPORT_PATH / project_id
    ensure_dir(base)
    prefix = job_id or "manual"
    return base / f"{prefix}_{filename}"
