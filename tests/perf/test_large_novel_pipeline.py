from __future__ import annotations

import os
from pathlib import Path

import pytest

from modules.nf_retrieval.vector import manifest as vector_manifest
from modules.nf_retrieval.vector import shard_store
from modules.nf_retrieval.vector.manifest import update_manifest, vector_search
from modules.nf_retrieval.vector.shard_store import build_shard
from modules.nf_schema.chunking import build_chunks

RUN_PERF = os.environ.get("NF_RUN_PERF_TESTS") == "1"


def _load_large_text() -> str:
    candidates = sorted(Path("test_files").glob("*.txt"))
    if not candidates:
        pytest.skip("test_files/*.txt not found")
    # Prefer the larger corpus file.
    target = max(candidates, key=lambda p: p.stat().st_size)
    for enc in ("utf-8", "utf-16", "cp949"):
        try:
            return target.read_text(encoding=enc)
        except UnicodeError:
            continue
    return target.read_text(errors="ignore")


@pytest.mark.perf
@pytest.mark.skipif(not RUN_PERF, reason="set NF_RUN_PERF_TESTS=1 to run perf tests")
def test_large_novel_chunking_density_regression() -> None:
    text = _load_large_text()
    text = text[: min(len(text), 2_000_000)]
    if len(text) < 100_000:
        pytest.skip("input text too small for perf-style chunking check")

    sizes = [200_000, 500_000, min(1_000_000, len(text))]
    stats: list[tuple[int, int, float]] = []
    for size in sizes:
        subset = text[:size]
        chunks = build_chunks(
            project_id="project-1",
            doc_id=f"doc-{size}",
            snapshot_id=f"snap-{size}",
            text=subset,
        )
        chunk_count = len(chunks)
        avg_chars = size / max(1, chunk_count)
        stats.append((size, chunk_count, avg_chars))

    # Monotonic growth, but avoid extreme tiny-chunk explosion.
    assert stats[0][1] <= stats[1][1] <= stats[2][1]
    assert stats[0][2] >= 180
    assert stats[1][2] >= 180
    assert stats[2][2] >= 180


@pytest.mark.perf
@pytest.mark.skipif(not RUN_PERF, reason="set NF_RUN_PERF_TESTS=1 to run perf tests")
def test_vector_search_uses_warm_shard_cache(tmp_path: Path) -> None:
    # Isolate vector storage path for this test.
    vector_base = tmp_path / "vector"
    shard_store.DEFAULT_VECTOR_PATH = vector_base
    vector_manifest.DEFAULT_VECTOR_PATH = vector_base
    vector_manifest._MANIFEST_CACHE["mtime_ns"] = None
    vector_manifest._MANIFEST_CACHE["manifest"] = None
    vector_manifest._SHARD_CACHE.clear()

    text = _load_large_text()
    text = text[: min(len(text), 300_000)]
    chunks = build_chunks(
        project_id="project-1",
        doc_id="doc-1",
        snapshot_id="snap-1",
        text=text,
    )
    _, meta = build_shard(
        doc_id="doc-1",
        snapshot_id="snap-1",
        chunks=chunks,
        text=text,
    )
    update_manifest([meta])

    cold_stats: dict[str, int] = {}
    cold = vector_search(
        {
            "project_id": "project-1",
            "query": text[:200],
            "filters": {"doc_id": "doc-1"},
            "k": 10,
            "stats": cold_stats,
        }
    )
    warm_stats: dict[str, int] = {}
    warm = vector_search(
        {
            "project_id": "project-1",
            "query": text[:200],
            "filters": {"doc_id": "doc-1"},
            "k": 10,
            "stats": warm_stats,
        }
    )

    assert cold
    assert warm
    assert int(cold_stats.get("shards_loaded", 0)) >= 1
    assert int(warm_stats.get("shards_loaded", 0)) == 0
