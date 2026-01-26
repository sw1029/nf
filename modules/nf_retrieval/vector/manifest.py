from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.nf_retrieval.contracts import RetrievalRequest, RetrievalResult
from modules.nf_retrieval.fts.snippet import make_snippet
from modules.nf_retrieval.vector.embedder import overlap_score, tokenize
from modules.nf_retrieval.vector.shard_store import DEFAULT_VECTOR_PATH, load_shard
from modules.nf_shared.config import load_config
from modules.nf_shared.protocol.dtos import EvidenceMatchType


def manifest_path() -> Path:
    return DEFAULT_VECTOR_PATH / "vector_manifest.json"


def load_manifest() -> dict[str, Any]:
    path = manifest_path()
    if not path.exists():
        return {"embedding_model_id": "token-overlap-v1", "dim": None, "shards": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(manifest: dict[str, Any]) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def update_manifest(new_shards: list[dict[str, Any]]) -> None:
    manifest = load_manifest()
    existing = {shard["shard_id"]: shard for shard in manifest.get("shards", [])}
    for shard in new_shards:
        existing[shard["shard_id"]] = shard
    manifest["shards"] = list(existing.values())
    save_manifest(manifest)


def _select_shards(manifest: dict[str, Any], filters: dict[str, Any]) -> list[dict[str, Any]]:
    shards = manifest.get("shards", [])
    doc_id = filters.get("doc_id") if isinstance(filters, dict) else None
    if isinstance(doc_id, str):
        return [shard for shard in shards if shard.get("shard_id") == doc_id]
    settings = load_config()
    max_shards = max(1, settings.max_loaded_shards)
    return sorted(shards, key=lambda s: s.get("built_at", ""), reverse=True)[:max_shards]


def vector_search(req: RetrievalRequest) -> list[RetrievalResult]:
    manifest = load_manifest()
    shards = _select_shards(manifest, req.get("filters") or {})
    query = req.get("query", "")
    query_tokens = tokenize(query)

    results: list[RetrievalResult] = []
    for shard in shards:
        entries = load_shard(shard.get("path", ""))
        for entry in entries:
            score = overlap_score(query_tokens, entry.get("tokens", []))
            if score <= 0:
                continue
            snippet = make_snippet(entry.get("text", ""), query)
            results.append(
                {
                    "source": "vector",
                    "score": score,
                    "evidence": {
                        "doc_id": entry.get("doc_id", ""),
                        "snapshot_id": entry.get("snapshot_id", ""),
                        "chunk_id": entry.get("chunk_id", ""),
                        "section_path": entry.get("section_path", ""),
                        "tag_path": entry.get("tag_path", ""),
                        "snippet_text": snippet,
                        "span_start": entry.get("span_start", 0),
                        "span_end": entry.get("span_end", 0),
                        "fts_score": score,
                        "match_type": EvidenceMatchType.FUZZY.value,
                        "confirmed": False,
                    },
                }
            )
    results.sort(key=lambda r: r.get("score", 0), reverse=True)
    limit = int(req.get("k") or 10)
    return results[:limit]
