from __future__ import annotations

from typing import Any, Protocol, TypedDict


class RetrievalRequest(TypedDict, total=False):
    project_id: str
    query: str
    filters: dict
    k: int
    stats: dict[str, Any]


class GraphSearchParams(TypedDict, total=False):
    enabled: bool
    max_hops: int
    rerank_weight: float


class RetrievalResult(TypedDict):
    source: str  # sync: "fts" only, async: "vector" allowed
    score: float
    evidence: dict


class FTSSearcher(Protocol):
    def search(self, req: RetrievalRequest) -> list[RetrievalResult]: ...


class VectorSearcher(Protocol):
    def search(self, req: RetrievalRequest) -> list[RetrievalResult]: ...
