from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Any

from modules.nf_retrieval.graph.materialized import build_project_graph, load_project_graph

_SEED_WEIGHT_FILTER = 1.0
_SEED_WEIGHT_ALIAS = 0.7
_SEED_WEIGHT_TERM = 0.45
_HOP_BOOST_DECAY = {1: 1.0, 2: 0.5}
_WORD_BOUNDARY_RE = re.compile(r"[0-9A-Za-z\uac00-\ud7a3]+")
_SHORT_ALIAS_SUFFIXES = {
    "\uc740",
    "\ub294",
    "\uc774",
    "\uac00",
    "\uc744",
    "\ub97c",
    "\uc640",
    "\uacfc",
    "\uc758",
    "\uc5d0",
    "\ub85c",
    "\uc73c\ub85c",
    "\uc5d0\uc11c",
    "\uc5d0\uac8c",
    "\ub3c4",
    "\ub9cc",
    "\uaed8",
}


def _normalize_query(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    return " ".join(normalized.strip().split())


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            out.append(item)
    return out


def _query_token_set(query_norm: str) -> set[str]:
    tokens = {match.group(0) for match in _WORD_BOUNDARY_RE.finditer(query_norm)}
    if not tokens and query_norm:
        tokens.add(query_norm)
    return tokens


def _matches_signal(query_norm: str, query_tokens: set[str], raw_signal: str) -> bool:
    signal = _normalize_query(raw_signal)
    if not signal:
        return False
    signal_tokens = _query_token_set(signal)
    if len(signal.replace(" ", "")) <= 2:
        if signal in query_tokens:
            return True
        if len(signal_tokens) == 1:
            normalized_token = next(iter(signal_tokens))
            if normalized_token in query_tokens:
                return True
        for token in query_tokens:
            if not token.startswith(signal):
                continue
            suffix = token[len(signal) :]
            if suffix in _SHORT_ALIAS_SUFFIXES:
                return True
        return False
    boundary_pattern = rf"(?<![0-9A-Za-z\uac00-\ud7a3]){re.escape(signal)}(?![0-9A-Za-z\uac00-\ud7a3])"
    if re.search(boundary_pattern, query_norm):
        return True
    # Space-normalized exact token phrase.
    if signal in query_tokens:
        return True
    # For multi-token signals, require all tokens to be present.
    return bool(signal_tokens) and all(token in query_tokens for token in signal_tokens)


def _apply_seed_weight(target: dict[str, float], doc_ids: list[str], weight: float) -> None:
    if weight <= 0:
        return
    for doc_id in doc_ids:
        prev = target.get(doc_id, 0.0)
        # Keep max signal for deterministic filter > alias > term behavior.
        if weight > prev:
            target[doc_id] = weight


def _collect_seed_doc_weights(graph: dict[str, Any], query: str, filters: dict[str, Any]) -> dict[str, float]:
    seed_doc_weights: dict[str, float] = {}
    entity_doc_ids = graph.get("entity_doc_ids") or {}
    time_doc_ids = graph.get("time_doc_ids") or {}
    timeline_doc_ids = graph.get("timeline_doc_ids") or {}
    entity_aliases = graph.get("entity_aliases") or {}
    entity_terms = graph.get("entity_terms") or {}

    entity_id = filters.get("entity_id")
    if isinstance(entity_id, str):
        _apply_seed_weight(seed_doc_weights, _as_str_list(entity_doc_ids.get(entity_id)), _SEED_WEIGHT_FILTER)

    time_key = filters.get("time_key")
    if isinstance(time_key, str):
        _apply_seed_weight(seed_doc_weights, _as_str_list(time_doc_ids.get(time_key)), _SEED_WEIGHT_FILTER)

    timeline_idx = filters.get("timeline_idx")
    if timeline_idx is not None:
        try:
            _apply_seed_weight(
                seed_doc_weights,
                _as_str_list(timeline_doc_ids.get(str(int(timeline_idx)))),
                _SEED_WEIGHT_FILTER,
            )
        except (TypeError, ValueError):
            pass

    query_norm = _normalize_query(query)
    if not query_norm:
        return seed_doc_weights
    query_tokens = _query_token_set(query_norm)

    for key, aliases in entity_aliases.items():
        for alias in _as_str_list(aliases):
            if _matches_signal(query_norm, query_tokens, alias):
                _apply_seed_weight(seed_doc_weights, _as_str_list(entity_doc_ids.get(key)), _SEED_WEIGHT_ALIAS)
                break

    for key, terms in entity_terms.items():
        for term in _as_str_list(terms):
            if _matches_signal(query_norm, query_tokens, term):
                _apply_seed_weight(seed_doc_weights, _as_str_list(entity_doc_ids.get(key)), _SEED_WEIGHT_TERM)
                break

    return seed_doc_weights


def _collect_seed_docs(graph: dict[str, Any], query: str, filters: dict[str, Any]) -> set[str]:
    return set(_collect_seed_doc_weights(graph, query, filters))


def _expand_docs(graph: dict[str, Any], seeds: set[str], max_hops: int) -> dict[str, int]:
    distance: dict[str, int] = {doc_id: 1 for doc_id in seeds}
    if max_hops <= 1:
        return distance

    doc_entities = graph.get("doc_entities") or {}
    doc_times = graph.get("doc_times") or {}
    doc_timelines = graph.get("doc_timelines") or {}
    entity_doc_ids = graph.get("entity_doc_ids") or {}
    time_doc_ids = graph.get("time_doc_ids") or {}
    timeline_doc_ids = graph.get("timeline_doc_ids") or {}

    for doc_id in list(seeds):
        for entity_id in _as_str_list(doc_entities.get(doc_id)):
            for candidate in _as_str_list(entity_doc_ids.get(entity_id)):
                distance.setdefault(candidate, 2)
        for time_key in _as_str_list(doc_times.get(doc_id)):
            for candidate in _as_str_list(time_doc_ids.get(time_key)):
                distance.setdefault(candidate, 2)
        for timeline_idx in _as_str_list(doc_timelines.get(doc_id)):
            for candidate in _as_str_list(timeline_doc_ids.get(timeline_idx)):
                distance.setdefault(candidate, 2)
    return distance


def expand_candidate_docs_with_graph(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    query: str,
    filters: dict[str, Any],
    max_hops: int = 1,
    doc_cap: int = 200,
) -> tuple[list[str], dict[str, Any]]:
    max_hops = 1 if max_hops < 1 else min(2, max_hops)
    doc_cap = max(1, int(doc_cap))

    graph = load_project_graph(project_id)
    if graph is None:
        graph = build_project_graph(conn, project_id)

    seed_doc_weights = _collect_seed_doc_weights(graph, query, filters)
    seeds = set(seed_doc_weights)
    if not seeds:
        return [], {
            "applied": False,
            "reason": "no_seeds",
            "seed_docs": [],
            "expanded_docs": [],
            "doc_distances": {},
            "seed_doc_weights": {},
            "seed_doc_count": 0,
            "expanded_doc_count": 0,
            "candidate_doc_count": 0,
            "max_hops": max_hops,
            "doc_cap": doc_cap,
        }

    distances = _expand_docs(graph, seeds, max_hops=max_hops)
    if not distances:
        return [], {
            "applied": False,
            "reason": "no_reachable_docs",
            "seed_docs": sorted(seeds),
            "expanded_docs": [],
            "doc_distances": {},
            "seed_doc_weights": {doc_id: float(weight) for doc_id, weight in seed_doc_weights.items()},
            "seed_doc_count": len(seeds),
            "expanded_doc_count": 0,
            "candidate_doc_count": 0,
            "max_hops": max_hops,
            "doc_cap": doc_cap,
        }

    ordered = sorted(
        distances.items(),
        key=lambda item: (
            item[1],
            -float(seed_doc_weights.get(item[0], 0.0)),
            item[0],
        ),
    )
    candidate_doc_ids = [doc_id for doc_id, _distance in ordered[:doc_cap]]
    seed_docs = sorted(seeds)
    expanded_docs = sorted(distances.keys())
    return candidate_doc_ids, {
        "applied": True,
        "reason": "",
        "seed_docs": seed_docs,
        "expanded_docs": expanded_docs,
        "doc_distances": {doc_id: int(distance) for doc_id, distance in distances.items()},
        "seed_doc_weights": {doc_id: float(weight) for doc_id, weight in seed_doc_weights.items()},
        "seed_doc_count": len(seed_docs),
        "expanded_doc_count": len(expanded_docs),
        "candidate_doc_count": len(candidate_doc_ids),
        "max_hops": max_hops,
        "doc_cap": doc_cap,
    }


def rerank_results_with_graph(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    query: str,
    results: list[dict[str, Any]],
    filters: dict[str, Any],
    max_hops: int = 1,
    rerank_weight: float = 0.25,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    max_hops = 1 if max_hops < 1 else min(2, max_hops)
    rerank_weight = max(0.0, min(0.5, rerank_weight))
    if not results or rerank_weight <= 0:
        return results, {
            "applied": False,
            "reason": "empty_or_zero_weight",
            "seed_docs": [],
            "expanded_docs": [],
            "boosted_results": 0,
            "seed_doc_count": 0,
            "boosted_result_count": 0,
        }

    graph = load_project_graph(project_id)
    if graph is None:
        graph = build_project_graph(conn, project_id)

    seed_doc_weights = _collect_seed_doc_weights(graph, query, filters)
    seeds = set(seed_doc_weights)
    if not seeds:
        return results, {
            "applied": False,
            "reason": "no_seeds",
            "seed_docs": [],
            "expanded_docs": [],
            "seed_doc_weights": {},
            "boosted_results": 0,
            "seed_doc_count": 0,
            "boosted_result_count": 0,
        }

    distances = _expand_docs(graph, seeds, max_hops=max_hops)
    if not distances:
        return results, {
            "applied": False,
            "reason": "no_reachable_docs",
            "seed_docs": sorted(seeds),
            "expanded_docs": [],
            "seed_doc_weights": {doc_id: float(weight) for doc_id, weight in seed_doc_weights.items()},
            "boosted_results": 0,
            "seed_doc_count": len(seeds),
            "boosted_result_count": 0,
        }

    reranked: list[dict[str, Any]] = []
    boosted = 0
    for item in results:
        evidence = item.get("evidence") or {}
        doc_id = evidence.get("doc_id")
        base_score = float(item.get("score") or 0.0)
        if not isinstance(doc_id, str):
            reranked.append(item)
            continue
        distance = distances.get(doc_id)
        if distance is None:
            reranked.append(item)
            continue
        hop_decay = _HOP_BOOST_DECAY.get(int(distance), 0.5)
        signal_weight = float(seed_doc_weights.get(doc_id, 0.0))
        signal_scale = 0.6 + (0.4 * max(0.0, min(1.0, signal_weight)))
        boost = rerank_weight * hop_decay * signal_scale
        updated = dict(item)
        updated["score"] = base_score + boost
        reranked.append(updated)
        boosted += 1

    reranked.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    seed_docs = sorted(seeds)
    expanded_docs = sorted(distances.keys())
    return reranked, {
        "applied": True,
        "max_hops": max_hops,
        "rerank_weight": rerank_weight,
        "seed_docs": seed_docs,
        "expanded_docs": expanded_docs,
        "seed_doc_weights": {doc_id: float(weight) for doc_id, weight in seed_doc_weights.items()},
        "boosted_results": boosted,
        # Backward compatible aliases.
        "seed_doc_count": len(seed_docs),
        "boosted_result_count": boosted,
    }
