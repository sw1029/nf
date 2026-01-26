from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from modules.nf_retrieval.vector.embedder import tokenize
from modules.nf_shared.protocol.dtos import Chunk


DEFAULT_VECTOR_PATH = Path(os.environ.get("NF_VECTOR_PATH", "data/vector"))


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_vector_dirs() -> Path:
    shards_dir = DEFAULT_VECTOR_PATH / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    return shards_dir


def shard_path(doc_id: str) -> Path:
    shards_dir = ensure_vector_dirs()
    return shards_dir / f"shard_{doc_id}.json"


def build_shard(
    *,
    doc_id: str,
    snapshot_id: str,
    chunks: list[Chunk],
    text: str,
) -> tuple[Path, dict]:
    path = shard_path(doc_id)
    entries = []
    for chunk in chunks:
        chunk_text = text[chunk.span_start : chunk.span_end]
        entries.append(
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "snapshot_id": snapshot_id,
                "section_path": chunk.section_path,
                "tag_path": "",
                "span_start": chunk.span_start,
                "span_end": chunk.span_end,
                "text": chunk_text,
                "tokens": tokenize(chunk_text),
            }
        )
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    meta = {
        "shard_id": doc_id,
        "path": str(path),
        "doc_ids": [doc_id],
        "chunk_count_est": len(entries),
        "built_at": _now_ts(),
    }
    return path, meta


def load_shard(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
