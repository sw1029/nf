from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

from modules.nf_retrieval.contracts import RetrievalRequest, RetrievalResult
from modules.nf_retrieval.fts.snippet import make_snippet
from modules.nf_retrieval.vector.embedder import overlap_score, tokenize
from modules.nf_retrieval.vector.shard_store import DEFAULT_VECTOR_PATH, load_shard
from modules.nf_shared.config import load_config
from modules.nf_shared.protocol.dtos import EvidenceMatchType

_MANIFEST_CACHE: dict[str, Any] = {"mtime_ns": None, "manifest": None}
_SHARD_CACHE: "OrderedDict[str, tuple[int, list[dict[str, Any]]]]" = OrderedDict()
_SHARD_CACHE_MAX = 64


def manifest_path() -> Path:
    return DEFAULT_VECTOR_PATH / "vector_manifest.json"


def _normalize_cache_limit(value: int) -> int:
    return max(4, min(256, value))


def _cache_limit() -> int:
    settings = load_config()
    return _normalize_cache_limit(max(4, settings.max_loaded_shards * 2))


def _read_manifest_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"embedding_model_id": "token-overlap-v1", "dim": None, "shards": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest() -> dict[str, Any]:
    path = manifest_path()
    try:
        mtime_ns = path.stat().st_mtime_ns if path.exists() else -1
    except OSError:
        mtime_ns = -1

    cached_mtime = _MANIFEST_CACHE.get("mtime_ns")
    cached_manifest = _MANIFEST_CACHE.get("manifest")
    if cached_manifest is not None and cached_mtime == mtime_ns:
        return cached_manifest

    manifest = _read_manifest_file(path)
    _MANIFEST_CACHE["mtime_ns"] = mtime_ns
    _MANIFEST_CACHE["manifest"] = manifest
    return manifest


def save_manifest(manifest: dict[str, Any]) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = None
    _MANIFEST_CACHE["mtime_ns"] = mtime_ns
    _MANIFEST_CACHE["manifest"] = manifest


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
    doc_ids = filters.get("doc_ids") if isinstance(filters, dict) else None
    if isinstance(doc_id, str):
        return [shard for shard in shards if shard.get("shard_id") == doc_id]
    if isinstance(doc_ids, list):
        allowed = {item for item in doc_ids if isinstance(item, str) and item}
        if allowed:
            return [
                shard
                for shard in shards
                if isinstance(shard.get("shard_id"), str) and shard.get("shard_id") in allowed
            ]
    settings = load_config()
    max_shards = max(1, settings.max_loaded_shards)
    return sorted(shards, key=lambda s: s.get("built_at", ""), reverse=True)[:max_shards]


def _load_shard_cached(path_value: str | Path) -> tuple[list[dict[str, Any]], bool]:
    path = Path(path_value)
    if not path.exists():
        return [], False
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = -1
    key = str(path.resolve())

    cached = _SHARD_CACHE.get(key)
    if cached is not None and cached[0] == mtime_ns:
        _SHARD_CACHE.move_to_end(key)
        return cached[1], False

    entries = load_shard(path)
    _SHARD_CACHE[key] = (mtime_ns, entries)
    _SHARD_CACHE.move_to_end(key)
    max_items = _cache_limit()
    while len(_SHARD_CACHE) > max_items:
        _SHARD_CACHE.popitem(last=False)
    return entries, True


def vector_search(req: RetrievalRequest) -> list[RetrievalResult]:
    manifest = load_manifest()
    filters = req.get("filters") or {}
    shards = _select_shards(manifest, filters if isinstance(filters, dict) else {})
    query = req.get("query", "")
    query_tokens = tokenize(query)
    snapshot_id_filter = filters.get("snapshot_id") if isinstance(filters, dict) else None
    snapshot_ids_filter = filters.get("snapshot_ids") if isinstance(filters, dict) else None
    tag_path_filter = filters.get("tag_path") if isinstance(filters, dict) else None
    section_filter = filters.get("section") if isinstance(filters, dict) else None
    episode_filter = filters.get("episode") if isinstance(filters, dict) else None
    doc_ids_filter = filters.get("doc_ids") if isinstance(filters, dict) else None
    allowed_doc_ids = (
        {item for item in doc_ids_filter if isinstance(item, str) and item}
        if isinstance(doc_ids_filter, list)
        else set()
    )
    allowed_snapshot_ids = (
        {item for item in snapshot_ids_filter if isinstance(item, str) and item}
        if isinstance(snapshot_ids_filter, list)
        else set()
    )
    stats_raw = req.get("stats")
    stats = stats_raw if isinstance(stats_raw, dict) else None
    if stats is not None:
        stats.setdefault("rows_scanned", 0)
        stats.setdefault("chunks_processed", 0)
        stats.setdefault("shards_loaded", 0)
        stats["shards_selected"] = len(shards)

    results: list[RetrievalResult] = []
    for shard in shards:
        entries, loaded_from_disk = _load_shard_cached(shard.get("path", ""))
        if stats is not None and loaded_from_disk:
            stats["shards_loaded"] = int(stats.get("shards_loaded", 0)) + 1
        for entry in entries:
            if stats is not None:
                stats["rows_scanned"] = int(stats.get("rows_scanned", 0)) + 1
            if allowed_doc_ids and entry.get("doc_id") not in allowed_doc_ids:
                continue
            if isinstance(snapshot_id_filter, str) and snapshot_id_filter:
                if entry.get("snapshot_id") != snapshot_id_filter:
                    continue
            if allowed_snapshot_ids and entry.get("snapshot_id") not in allowed_snapshot_ids:
                continue
            if isinstance(tag_path_filter, str) and tag_path_filter:
                primary = entry.get("tag_path") or ""
                if primary != tag_path_filter:
                    all_paths = entry.get("tag_paths")
                    if not isinstance(all_paths, list) or tag_path_filter not in all_paths:
                        continue
            if isinstance(section_filter, str) and section_filter:
                if entry.get("section_path") != section_filter:
                    continue
            if isinstance(episode_filter, str) and episode_filter:
                if entry.get("episode_id") != episode_filter:
                    continue
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
    sliced = results[:limit]
    if stats is not None:
        stats["chunks_processed"] = int(stats.get("chunks_processed", 0)) + len(sliced)
    return sliced
