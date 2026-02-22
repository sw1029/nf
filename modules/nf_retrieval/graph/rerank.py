from __future__ import annotations

import sqlite3
from typing import Any

from modules.nf_retrieval.graph.materialized import build_project_graph, load_project_graph


def _normalize_query(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            out.append(item)
    return out


def _collect_seed_docs(graph: dict[str, Any], query: str, filters: dict[str, Any]) -> set[str]:
    seed_docs: set[str] = set()
    entity_doc_ids = graph.get("entity_doc_ids") or {}
    time_doc_ids = graph.get("time_doc_ids") or {}
    timeline_doc_ids = graph.get("timeline_doc_ids") or {}
    entity_aliases = graph.get("entity_aliases") or {}
    entity_terms = graph.get("entity_terms") or {}

    entity_id = filters.get("entity_id")
    if isinstance(entity_id, str):
        seed_docs.update(_as_str_list(entity_doc_ids.get(entity_id)))

    time_key = filters.get("time_key")
    if isinstance(time_key, str):
        seed_docs.update(_as_str_list(time_doc_ids.get(time_key)))

    timeline_idx = filters.get("timeline_idx")
    if timeline_idx is not None:
        try:
            seed_docs.update(_as_str_list(timeline_doc_ids.get(str(int(timeline_idx)))))
        except (TypeError, ValueError):
            pass

    query_norm = _normalize_query(query)
    if not query_norm:
        return seed_docs

    for key, aliases in entity_aliases.items():
        for alias in _as_str_list(aliases):
            if alias and alias in query_norm:
                seed_docs.update(_as_str_list(entity_doc_ids.get(key)))
                break

    for key, terms in entity_terms.items():
        for term in _as_str_list(terms):
            if term and term in query_norm:
                seed_docs.update(_as_str_list(entity_doc_ids.get(key)))
                break

    return seed_docs


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

    seeds = _collect_seed_docs(graph, query, filters)
    if not seeds:
        return [], {
            "applied": False,
            "reason": "no_seeds",
            "seed_docs": [],
            "expanded_docs": [],
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
            "seed_doc_count": len(seeds),
            "expanded_doc_count": 0,
            "candidate_doc_count": 0,
            "max_hops": max_hops,
            "doc_cap": doc_cap,
        }

    ordered = sorted(distances.items(), key=lambda item: (item[1], item[0]))
    candidate_doc_ids = [doc_id for doc_id, _distance in ordered[:doc_cap]]
    seed_docs = sorted(seeds)
    expanded_docs = sorted(distances.keys())
    return candidate_doc_ids, {
        "applied": True,
        "reason": "",
        "seed_docs": seed_docs,
        "expanded_docs": expanded_docs,
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

    seeds = _collect_seed_docs(graph, query, filters)
    if not seeds:
        return results, {
            "applied": False,
            "reason": "no_seeds",
            "seed_docs": [],
            "expanded_docs": [],
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
        if distance <= 1:
            boost = rerank_weight
        else:
            boost = rerank_weight * 0.5
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
        "boosted_results": boosted,
        # Backward compatible aliases.
        "seed_doc_count": len(seed_docs),
        "boosted_result_count": boosted,
    }
