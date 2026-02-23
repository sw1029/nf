from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from modules.nf_retrieval.vector.embedder import hashed_embedding_score, overlap_score, tokenize

_BACKEND_TOKEN_OVERLAP = "token_overlap"
_BACKEND_HASHED_EMBEDDING = "hashed_embedding"


class VectorSearchBackend(Protocol):
    name: str

    def score(self, *, query_text: str, query_tokens: list[str], entry: dict[str, Any]) -> float:
        ...


@dataclass(frozen=True)
class TokenOverlapBackend:
    name: str = _BACKEND_TOKEN_OVERLAP

    def score(self, *, query_text: str, query_tokens: list[str], entry: dict[str, Any]) -> float:
        raw_tokens = entry.get("tokens")
        if isinstance(raw_tokens, list):
            doc_tokens = [str(item) for item in raw_tokens if isinstance(item, str) and item]
        else:
            doc_tokens = tokenize(str(entry.get("text", "")))
        return overlap_score(query_tokens, doc_tokens)


@dataclass(frozen=True)
class HashedEmbeddingBackend:
    dim: int = 96
    name: str = _BACKEND_HASHED_EMBEDDING

    def score(self, *, query_text: str, query_tokens: list[str], entry: dict[str, Any]) -> float:
        doc_text = entry.get("text")
        if not isinstance(doc_text, str) or not doc_text:
            return 0.0
        return hashed_embedding_score(query_text, doc_text, dim=self.dim)


def normalize_backend_name(raw: Any) -> str:
    if not isinstance(raw, str):
        return _BACKEND_TOKEN_OVERLAP
    token = raw.strip().lower()
    if token in {"", _BACKEND_TOKEN_OVERLAP, "token-overlap"}:
        return _BACKEND_TOKEN_OVERLAP
    if token in {_BACKEND_HASHED_EMBEDDING, "hashed-embedding"}:
        return _BACKEND_HASHED_EMBEDDING
    return _BACKEND_TOKEN_OVERLAP


def create_vector_search_backend(raw: Any) -> VectorSearchBackend:
    normalized = normalize_backend_name(raw)
    if normalized == _BACKEND_HASHED_EMBEDDING:
        return HashedEmbeddingBackend()
    return TokenOverlapBackend()


def supported_vector_search_backends() -> tuple[str, ...]:
    return (_BACKEND_TOKEN_OVERLAP, _BACKEND_HASHED_EMBEDDING)
