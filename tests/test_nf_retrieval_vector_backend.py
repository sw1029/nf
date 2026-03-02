from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_retrieval.vector import manifest
from modules.nf_retrieval.vector.backends import (
    HashedEmbeddingBackend,
    TokenOverlapBackend,
    create_vector_search_backend,
    supported_vector_search_backends,
)
from modules.nf_shared.config import Settings


@pytest.mark.unit
def test_vector_backend_factory_defaults_to_token_overlap() -> None:
    backend = create_vector_search_backend("unknown")
    assert isinstance(backend, TokenOverlapBackend)
    assert "token_overlap" in supported_vector_search_backends()
    assert "hashed_embedding" in supported_vector_search_backends()


@pytest.mark.unit
def test_settings_default_vector_backend_is_hashed_embedding() -> None:
    assert Settings().vector_search_backend == "hashed_embedding"


@pytest.mark.unit
def test_hashed_embedding_backend_scores_similar_text_higher() -> None:
    backend = HashedEmbeddingBackend()
    close_score = backend.score(
        query_text="hero protects village",
        query_tokens=[],
        entry={"text": "The hero protects the village at dawn."},
    )
    far_score = backend.score(
        query_text="hero protects village",
        query_tokens=[],
        entry={"text": "A spaceship launches from orbit."},
    )
    assert close_score > far_score
    assert close_score >= 0.0
    assert far_score >= 0.0


@pytest.mark.unit
def test_vector_search_uses_configured_backend_and_emits_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats: dict[str, object] = {}
    monkeypatch.setattr(
        manifest,
        "load_config",
        lambda: Settings(vector_search_backend="hashed_embedding", max_loaded_shards=1),
    )
    monkeypatch.setattr(
        manifest,
        "load_manifest",
        lambda: {"shards": [{"path": str(tmp_path / "dummy.json"), "shard_id": "doc-1"}]},
    )
    monkeypatch.setattr(
        manifest,
        "_select_shards",
        lambda _manifest, _filters: [{"path": str(tmp_path / "dummy.json"), "shard_id": "doc-1"}],
    )
    monkeypatch.setattr(
        manifest,
        "_load_shard_cached",
        lambda _path: (
            [
                {
                    "doc_id": "doc-1",
                    "snapshot_id": "snap-1",
                    "chunk_id": "chunk-1",
                    "section_path": "body",
                    "tag_path": "character.hero.age",
                    "span_start": 0,
                    "span_end": 20,
                    "text": "hero protects village at dawn",
                    "tokens": ["hero", "protects", "village", "dawn"],
                }
            ],
            True,
        ),
    )

    results = manifest.vector_search(
        {
            "project_id": "project-1",
            "query": "hero protects village",
            "k": 5,
            "filters": {},
            "stats": stats,
        }
    )

    assert results
    assert stats.get("vector_backend") == "hashed_embedding"
    assert results[0]["source"] == "vector"
