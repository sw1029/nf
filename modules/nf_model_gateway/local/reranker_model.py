from __future__ import annotations

import re
from typing import Any

from modules.nf_model_gateway.local.model_store import ensure_model

_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text or "") if token}


def score_text_pair(query: str, snippet: str) -> float:
    query_tokens = _tokens(query)
    snippet_tokens = _tokens(snippet)
    if not query_tokens or not snippet_tokens:
        return 0.0
    overlap = query_tokens.intersection(snippet_tokens)
    if not overlap:
        return 0.0
    coverage = len(overlap) / float(max(1, len(query_tokens)))
    precision = len(overlap) / float(max(1, len(snippet_tokens)))
    query_norm = " ".join(str(query or "").lower().split())
    snippet_norm = " ".join(str(snippet or "").lower().split())
    phrase_bonus = 0.25 if query_norm and query_norm in snippet_norm else 0.0
    return _clamp01(0.10 + (0.60 * coverage) + (0.20 * precision) + phrase_bonus)


def rerank_snippets(
    query: str,
    snippets: list[str],
    *,
    enabled: bool = False,
    model_id: str | None = None,
) -> tuple[list[float], bool]:
    if not isinstance(snippets, list) or not snippets:
        return [], False
    fallback_used = bool(enabled and model_id and ensure_model(model_id) is None)
    scores: list[float] = []
    for snippet in snippets:
        score = score_text_pair(query, str(snippet or ""))
        scores.append(score)
    return scores, fallback_used


def rerank_results(
    query: str,
    rows: list[dict[str, Any]],
    *,
    enabled: bool = False,
    model_id: str | None = None,
) -> tuple[list[tuple[int, float]], bool]:
    snippets: list[str] = []
    for row in rows:
        evidence = row.get("evidence") if isinstance(row, dict) else {}
        if not isinstance(evidence, dict):
            evidence = {}
        snippets.append(str(evidence.get("snippet_text", "") or ""))
    scores, fallback_used = rerank_snippets(query, snippets, enabled=enabled, model_id=model_id)
    indexed = [(idx, score) for idx, score in enumerate(scores)]
    indexed.sort(key=lambda item: item[1], reverse=True)
    return indexed, fallback_used
