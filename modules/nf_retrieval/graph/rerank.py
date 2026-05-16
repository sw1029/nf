from __future__ import annotations

import heapq
import re
import sqlite3
import time
import unicodedata
from typing import Any

from modules.nf_retrieval.graph.materialized import build_project_graph, load_project_graph

_SEED_WEIGHT_FILTER = 1.0
_SEED_WEIGHT_ALIAS = 0.7
_SEED_WEIGHT_TERM = 0.45
_SEED_WEIGHT_TIME = 0.5
_HOP_BOOST_DECAY = {1: 1.0, 2: 0.5}
_GRAPH_TELEMETRY_DOC_LIMIT = 200
_WORD_BOUNDARY_RE = re.compile(r"[0-9A-Za-z\uac00-\ud7a3]+")
_SIGNAL_KINDS = ("alias", "term", "time")
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


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _load_graph_for_query(
    conn: sqlite3.Connection,
    project_id: str,
    graph: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if graph is not None:
        return graph, {"graph_source": "provided", "graph_load_ms": 0.0, "graph_build_ms": 0.0}
    build_start = time.perf_counter()
    try:
        built = build_project_graph(conn, project_id)
        return built, {"graph_source": "kg", "graph_load_ms": 0.0, "graph_build_ms": _elapsed_ms(build_start)}
    except Exception:  # noqa: BLE001 - JSON graph is a compatibility fallback.
        load_start = time.perf_counter()
        loaded = load_project_graph(project_id)
        load_ms = _elapsed_ms(load_start)
        if loaded is not None:
            return loaded, {"graph_source": "materialized", "graph_load_ms": load_ms, "graph_build_ms": 0.0}
        raise


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


def _append_runtime_signal(
    signal_doc_ids: dict[str, dict[str, set[str]]],
    signal_token_index: dict[str, dict[str, set[str]]],
    *,
    kind: str,
    signal: str,
    doc_ids: list[str],
) -> None:
    normalized = _normalize_query(signal)
    if kind not in _SIGNAL_KINDS or not normalized or not doc_ids:
        return
    docs = signal_doc_ids.setdefault(kind, {}).setdefault(normalized, set())
    docs.update(doc_ids)
    for token in _query_token_set(normalized):
        bucket = signal_token_index.setdefault(token, {key: set() for key in _SIGNAL_KINDS})
        bucket.setdefault(kind, set()).add(normalized)


def _normalize_signal_doc_ids(value: Any) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {kind: {} for kind in _SIGNAL_KINDS}
    if not isinstance(value, dict):
        return out
    for kind in _SIGNAL_KINDS:
        raw_kind = value.get(kind)
        if not isinstance(raw_kind, dict):
            continue
        for signal, doc_ids in raw_kind.items():
            normalized = _normalize_query(str(signal))
            docs = _as_str_list(doc_ids)
            if normalized and docs:
                out[kind][normalized] = docs
    return out


def _normalize_signal_token_index(value: Any) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    if not isinstance(value, dict):
        return out
    for token, raw_bucket in value.items():
        normalized_token = _normalize_query(str(token))
        if not normalized_token or not isinstance(raw_bucket, dict):
            continue
        bucket: dict[str, list[str]] = {}
        for kind in _SIGNAL_KINDS:
            signals = []
            for signal in _as_str_list(raw_bucket.get(kind)):
                normalized = _normalize_query(signal)
                if normalized:
                    signals.append(normalized)
            if signals:
                bucket[kind] = signals
        if bucket:
            out[normalized_token] = bucket
    return out


def _build_runtime_signal_indexes(
    graph: dict[str, Any],
) -> tuple[dict[str, dict[str, list[str]]], dict[str, dict[str, list[str]]]]:
    entity_doc_ids = graph.get("entity_doc_ids") or {}
    time_doc_ids = graph.get("time_doc_ids") or {}
    entity_aliases = graph.get("entity_aliases") or {}
    entity_terms = graph.get("entity_terms") or {}
    signal_doc_sets: dict[str, dict[str, set[str]]] = {kind: {} for kind in _SIGNAL_KINDS}
    token_index_sets: dict[str, dict[str, set[str]]] = {}

    if isinstance(entity_aliases, dict) and isinstance(entity_doc_ids, dict):
        for key, aliases in entity_aliases.items():
            docs = _as_str_list(entity_doc_ids.get(key))
            for alias in _as_str_list(aliases):
                _append_runtime_signal(signal_doc_sets, token_index_sets, kind="alias", signal=alias, doc_ids=docs)

    if isinstance(entity_terms, dict) and isinstance(entity_doc_ids, dict):
        for key, terms in entity_terms.items():
            docs = _as_str_list(entity_doc_ids.get(key))
            for term in _as_str_list(terms):
                _append_runtime_signal(signal_doc_sets, token_index_sets, kind="term", signal=term, doc_ids=docs)

    if isinstance(time_doc_ids, dict):
        for time_key_value, doc_ids in time_doc_ids.items():
            docs = _as_str_list(doc_ids)
            for signal in _time_signal_variants(str(time_key_value)):
                _append_runtime_signal(signal_doc_sets, token_index_sets, kind="time", signal=signal, doc_ids=docs)

    signal_doc_ids = {
        kind: {signal: sorted(docs) for signal, docs in signals.items()}
        for kind, signals in signal_doc_sets.items()
    }
    signal_token_index = {
        token: {kind: sorted(signals) for kind, signals in bucket.items() if signals}
        for token, bucket in token_index_sets.items()
    }
    return signal_doc_ids, signal_token_index


def _ensure_signal_indexes(
    graph: dict[str, Any],
) -> tuple[dict[str, dict[str, list[str]]], dict[str, dict[str, list[str]]]]:
    cached = graph.get("_runtime_signal_indexes")
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and isinstance(cached[0], dict)
        and isinstance(cached[1], dict)
    ):
        return cached[0], cached[1]

    signal_doc_ids = _normalize_signal_doc_ids(graph.get("signal_doc_ids"))
    signal_token_index = _normalize_signal_token_index(graph.get("signal_token_index"))
    if not any(signal_doc_ids.get(kind) for kind in _SIGNAL_KINDS):
        signal_doc_ids, signal_token_index = _build_runtime_signal_indexes(graph)
    elif not signal_token_index:
        token_sets: dict[str, dict[str, set[str]]] = {}
        for kind in _SIGNAL_KINDS:
            for signal in signal_doc_ids.get(kind, {}):
                for token in _query_token_set(signal):
                    bucket = token_sets.setdefault(token, {key: set() for key in _SIGNAL_KINDS})
                    bucket.setdefault(kind, set()).add(signal)
        signal_token_index = {
            token: {kind: sorted(signals) for kind, signals in bucket.items() if signals}
            for token, bucket in token_sets.items()
        }

    graph["_runtime_signal_indexes"] = (signal_doc_ids, signal_token_index)
    return signal_doc_ids, signal_token_index


def _query_lookup_tokens(query_tokens: set[str], query_norm: str) -> set[str]:
    tokens = set(query_tokens)
    if query_norm:
        tokens.add(query_norm)
    for token in list(query_tokens):
        for suffix in _SHORT_ALIAS_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix):
                stripped = token[: -len(suffix)]
                if stripped:
                    tokens.add(stripped)
    return tokens


def _candidate_signals_for_query(
    signal_doc_ids: dict[str, dict[str, list[str]]],
    signal_token_index: dict[str, dict[str, list[str]]],
    query_norm: str,
    query_tokens: set[str],
) -> dict[str, set[str]]:
    candidates: dict[str, set[str]] = {kind: set() for kind in _SIGNAL_KINDS}
    for kind in _SIGNAL_KINDS:
        if query_norm in signal_doc_ids.get(kind, {}):
            candidates[kind].add(query_norm)
    for token in _query_lookup_tokens(query_tokens, query_norm):
        bucket = signal_token_index.get(token)
        if not isinstance(bucket, dict):
            continue
        for kind in _SIGNAL_KINDS:
            for signal in _as_str_list(bucket.get(kind)):
                candidates[kind].add(signal)
    return candidates


def _apply_seed_weight(target: dict[str, float], doc_ids: list[str], weight: float) -> None:
    if weight <= 0:
        return
    for doc_id in doc_ids:
        prev = target.get(doc_id, 0.0)
        # Keep max signal for deterministic filter > alias > term behavior.
        if weight > prev:
            target[doc_id] = weight


def _increment_counter(counter: dict[str, int], key: str, amount: int = 1) -> None:
    if not key:
        return
    counter[key] = int(counter.get(key, 0)) + int(amount)


def _time_signal_variants(time_key: str) -> list[str]:
    normalized = _normalize_query(time_key)
    if not normalized:
        return []
    variants: list[str] = [normalized]
    marker = "/rel:"
    if marker in normalized:
        rel = normalized.split(marker, 1)[1].strip()
        if rel and rel not in variants:
            variants.append(rel)
    return variants


def _seed_hint_texts(
    *,
    slots: dict[str, Any] | None,
    seed_hints: list[str] | None,
    slot_key: str | None,
    claim_text: str | None,
) -> list[str]:
    hints: list[str] = []
    for hint in seed_hints or []:
        if isinstance(hint, str) and hint.strip():
            hints.append(hint.strip())
    if isinstance(claim_text, str) and claim_text.strip():
        hints.append(claim_text.strip())
    if isinstance(slots, dict):
        for key, value in slots.items():
            if slot_key and key != slot_key and key not in {"time", "place", "relation", "affiliation", "job", "talent"}:
                continue
            if isinstance(value, str) and value.strip():
                hints.append(value.strip())
            elif isinstance(value, (int, float)):
                hints.append(str(value))
    out: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        normalized = _normalize_query(hint)
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(hint)
    return out


def _apply_signal_candidates(
    *,
    seed_doc_weights: dict[str, float],
    seed_source_counts: dict[str, int],
    signal_doc_ids: dict[str, dict[str, list[str]]],
    signal_token_index: dict[str, dict[str, list[str]]],
    text: str,
    source_for_kind: dict[str, str],
) -> None:
    query_norm = _normalize_query(text)
    if not query_norm:
        return
    query_tokens = _query_token_set(query_norm)
    candidates = _candidate_signals_for_query(signal_doc_ids, signal_token_index, query_norm, query_tokens)
    for signal in candidates.get("alias", set()):
        if _matches_signal(query_norm, query_tokens, signal):
            docs = signal_doc_ids.get("alias", {}).get(signal, [])
            _apply_seed_weight(seed_doc_weights, docs, _SEED_WEIGHT_ALIAS)
            if docs:
                _increment_counter(seed_source_counts, source_for_kind.get("alias", "alias_match"))
    for signal in candidates.get("term", set()):
        if _matches_signal(query_norm, query_tokens, signal):
            docs = signal_doc_ids.get("term", {}).get(signal, [])
            _apply_seed_weight(seed_doc_weights, docs, _SEED_WEIGHT_TERM)
            if docs:
                _increment_counter(seed_source_counts, source_for_kind.get("term", "fact_term_match"))
    for signal in candidates.get("time", set()):
        if _matches_signal(query_norm, query_tokens, signal):
            docs = signal_doc_ids.get("time", {}).get(signal, [])
            _apply_seed_weight(seed_doc_weights, docs, _SEED_WEIGHT_TIME)
            if docs:
                _increment_counter(seed_source_counts, source_for_kind.get("time", "timeline_signal"))


def _collect_seed_doc_weights_with_meta(
    graph: dict[str, Any],
    query: str,
    filters: dict[str, Any],
    *,
    slots: dict[str, Any] | None = None,
    seed_hints: list[str] | None = None,
    slot_key: str | None = None,
    claim_text: str | None = None,
) -> tuple[dict[str, float], dict[str, int]]:
    seed_doc_weights: dict[str, float] = {}
    seed_source_counts: dict[str, int] = {}
    entity_doc_ids = graph.get("entity_doc_ids") or {}
    time_doc_ids = graph.get("time_doc_ids") or {}
    timeline_doc_ids = graph.get("timeline_doc_ids") or {}

    entity_id = filters.get("entity_id")
    if isinstance(entity_id, str):
        docs = _as_str_list(entity_doc_ids.get(entity_id))
        _apply_seed_weight(seed_doc_weights, docs, _SEED_WEIGHT_FILTER)
        if docs:
            _increment_counter(seed_source_counts, "filter_entity")

    time_key = filters.get("time_key")
    if isinstance(time_key, str):
        docs = _as_str_list(time_doc_ids.get(time_key))
        _apply_seed_weight(seed_doc_weights, docs, _SEED_WEIGHT_FILTER)
        if docs:
            _increment_counter(seed_source_counts, "filter_time")

    timeline_idx = filters.get("timeline_idx")
    if timeline_idx is not None:
        try:
            docs = _as_str_list(timeline_doc_ids.get(str(int(timeline_idx))))
            _apply_seed_weight(
                seed_doc_weights,
                docs,
                _SEED_WEIGHT_FILTER,
            )
            if docs:
                _increment_counter(seed_source_counts, "filter_timeline")
        except (TypeError, ValueError):
            pass

    signal_doc_ids, signal_token_index = _ensure_signal_indexes(graph)
    _apply_signal_candidates(
        seed_doc_weights=seed_doc_weights,
        seed_source_counts=seed_source_counts,
        signal_doc_ids=signal_doc_ids,
        signal_token_index=signal_token_index,
        text=query,
        source_for_kind={"alias": "alias_match", "term": "fact_term_match", "time": "timeline_signal"},
    )
    for hint in _seed_hint_texts(slots=slots, seed_hints=seed_hints, slot_key=slot_key, claim_text=claim_text):
        _apply_signal_candidates(
            seed_doc_weights=seed_doc_weights,
            seed_source_counts=seed_source_counts,
            signal_doc_ids=signal_doc_ids,
            signal_token_index=signal_token_index,
            text=hint,
            source_for_kind={"alias": "slot_hint_match", "term": "slot_hint_match", "time": "timeline_signal"},
        )

    return seed_doc_weights, seed_source_counts



def _collect_seed_doc_weights(graph: dict[str, Any], query: str, filters: dict[str, Any]) -> dict[str, float]:
    seed_doc_weights, _seed_source_counts = _collect_seed_doc_weights_with_meta(graph, query, filters)
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

    expanded_entities: set[str] = set()
    expanded_times: set[str] = set()
    expanded_timelines: set[str] = set()
    for doc_id in list(seeds):
        for entity_id in _as_str_list(doc_entities.get(doc_id)):
            if entity_id in expanded_entities:
                continue
            expanded_entities.add(entity_id)
            for candidate in _as_str_list(entity_doc_ids.get(entity_id)):
                distance.setdefault(candidate, 2)
        for time_key in _as_str_list(doc_times.get(doc_id)):
            if time_key in expanded_times:
                continue
            expanded_times.add(time_key)
            for candidate in _as_str_list(time_doc_ids.get(time_key)):
                distance.setdefault(candidate, 2)
        for timeline_idx in _as_str_list(doc_timelines.get(doc_id)):
            if timeline_idx in expanded_timelines:
                continue
            expanded_timelines.add(timeline_idx)
            for candidate in _as_str_list(timeline_doc_ids.get(timeline_idx)):
                distance.setdefault(candidate, 2)
    return distance


def _distance_sort_key(seed_doc_weights: dict[str, float]):
    return lambda item: (
        item[1],
        -float(seed_doc_weights.get(item[0], 0.0)),
        item[0],
    )


def _ordered_distance_items(
    distances: dict[str, int],
    seed_doc_weights: dict[str, float],
    *,
    limit: int,
) -> list[tuple[str, int]]:
    key = _distance_sort_key(seed_doc_weights)
    if len(distances) <= limit:
        return sorted(distances.items(), key=key)
    return heapq.nsmallest(limit, distances.items(), key=key)


def _graph_timing_defaults(meta: dict[str, Any]) -> dict[str, Any]:
    out = {
        "graph_source": "unknown",
        "graph_load_ms": 0.0,
        "graph_build_ms": 0.0,
        "graph_seed_scan_ms": 0.0,
        "graph_expand_ms": 0.0,
        "graph_sort_ms": 0.0,
        "graph_rerank_ms": 0.0,
        "graph_payload_doc_count": 0,
    }
    out.update(meta)
    return out


def _graph_trace_meta(
    graph: dict[str, Any],
    *,
    seed_source_counts: dict[str, int] | None = None,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    source_health = graph.get("source_health")
    edge_type_counts = graph.get("kg_edge_counts")
    skip_reason_counts: dict[str, int] = {}
    if skip_reason:
        skip_reason_counts[skip_reason] = 1
    if skip_reason and not graph.get("kg_build_id"):
        skip_reason_counts["kg_unavailable"] = 1
    sparse_reasons = source_health.get("sparse_reason_counts") if isinstance(source_health, dict) else {}
    if skip_reason and isinstance(sparse_reasons, dict):
        if any(str(key).startswith("entity") for key in sparse_reasons):
            skip_reason_counts["kg_sparse_entity"] = 1
        if any(str(key).startswith("timeline") for key in sparse_reasons):
            skip_reason_counts["kg_sparse_timeline"] = 1
    out = {
        "kg_build_id": graph.get("kg_build_id"),
        "kg_source_health_snapshot": dict(source_health) if isinstance(source_health, dict) else {},
        "seed_source_counts": dict(seed_source_counts or {}),
        "skip_reason_counts": skip_reason_counts,
        "edge_type_counts": dict(edge_type_counts) if isinstance(edge_type_counts, dict) else {},
    }
    return out


def expand_candidate_docs_with_graph(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    query: str,
    filters: dict[str, Any],
    max_hops: int = 1,
    doc_cap: int = 200,
    graph: dict[str, Any] | None = None,
    slots: dict[str, Any] | None = None,
    seed_hints: list[str] | None = None,
    slot_key: str | None = None,
    claim_text: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    max_hops = 1 if max_hops < 1 else min(2, max_hops)
    doc_cap = max(1, int(doc_cap))

    graph, timing_meta = _load_graph_for_query(conn, project_id, graph)

    seed_started = time.perf_counter()
    seed_doc_weights, seed_source_counts = _collect_seed_doc_weights_with_meta(
        graph,
        query,
        filters,
        slots=slots,
        seed_hints=seed_hints,
        slot_key=slot_key,
        claim_text=claim_text,
    )
    timing_meta["graph_seed_scan_ms"] = _elapsed_ms(seed_started)
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
            "expanded_doc_total_count": 0,
            "expanded_doc_sample_count": 0,
            "candidate_doc_count": 0,
            "max_hops": max_hops,
            "doc_cap": doc_cap,
            **_graph_trace_meta(graph, seed_source_counts=seed_source_counts, skip_reason="no_seeds"),
            **_graph_timing_defaults(timing_meta),
        }

    expand_started = time.perf_counter()
    distances = _expand_docs(graph, seeds, max_hops=max_hops)
    timing_meta["graph_expand_ms"] = _elapsed_ms(expand_started)
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
            "expanded_doc_total_count": 0,
            "expanded_doc_sample_count": 0,
            "candidate_doc_count": 0,
            "max_hops": max_hops,
            "doc_cap": doc_cap,
            **_graph_trace_meta(graph, seed_source_counts=seed_source_counts, skip_reason="no_reachable_docs"),
            **_graph_timing_defaults(timing_meta),
        }

    sort_started = time.perf_counter()
    telemetry_limit = max(doc_cap, _GRAPH_TELEMETRY_DOC_LIMIT)
    ordered = _ordered_distance_items(
        distances,
        seed_doc_weights,
        limit=telemetry_limit,
    )
    timing_meta["graph_sort_ms"] = _elapsed_ms(sort_started)
    candidate_doc_ids = [doc_id for doc_id, _distance in ordered[:doc_cap]]
    seed_docs = sorted(seeds)
    expanded_docs = [doc_id for doc_id, _distance in ordered]
    return candidate_doc_ids, {
        "applied": True,
        "reason": "",
        "seed_docs": seed_docs,
        "expanded_docs": expanded_docs,
        "doc_distances": {doc_id: int(distances[doc_id]) for doc_id in expanded_docs},
        "seed_doc_weights": {doc_id: float(weight) for doc_id, weight in seed_doc_weights.items()},
        "seed_doc_count": len(seed_docs),
        "expanded_doc_count": len(distances),
        "expanded_doc_total_count": len(distances),
        "expanded_doc_sample_count": len(expanded_docs),
        "candidate_doc_count": len(candidate_doc_ids),
        "max_hops": max_hops,
        "doc_cap": doc_cap,
        **_graph_trace_meta(graph, seed_source_counts=seed_source_counts),
        **_graph_timing_defaults(
            {
                **timing_meta,
                "graph_payload_doc_count": len(expanded_docs),
            }
        ),
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
    graph: dict[str, Any] | None = None,
    slots: dict[str, Any] | None = None,
    seed_hints: list[str] | None = None,
    slot_key: str | None = None,
    claim_text: str | None = None,
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
            "seed_source_counts": {},
            "skip_reason_counts": {"empty_or_zero_weight": 1},
            "edge_type_counts": {},
            "kg_build_id": None,
            "kg_source_health_snapshot": {},
            **_graph_timing_defaults({}),
        }

    graph, timing_meta = _load_graph_for_query(conn, project_id, graph)

    seed_started = time.perf_counter()
    seed_doc_weights, seed_source_counts = _collect_seed_doc_weights_with_meta(
        graph,
        query,
        filters,
        slots=slots,
        seed_hints=seed_hints,
        slot_key=slot_key,
        claim_text=claim_text,
    )
    timing_meta["graph_seed_scan_ms"] = _elapsed_ms(seed_started)
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
            **_graph_trace_meta(graph, seed_source_counts=seed_source_counts, skip_reason="no_seeds"),
            **_graph_timing_defaults(timing_meta),
        }

    expand_started = time.perf_counter()
    distances = _expand_docs(graph, seeds, max_hops=max_hops)
    timing_meta["graph_expand_ms"] = _elapsed_ms(expand_started)
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
            **_graph_trace_meta(graph, seed_source_counts=seed_source_counts, skip_reason="no_reachable_docs"),
            **_graph_timing_defaults(timing_meta),
        }

    rerank_started = time.perf_counter()
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

    timing_meta["graph_rerank_ms"] = _elapsed_ms(rerank_started)
    sort_started = time.perf_counter()
    reranked.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    ordered = _ordered_distance_items(
        distances,
        seed_doc_weights,
        limit=_GRAPH_TELEMETRY_DOC_LIMIT,
    )
    timing_meta["graph_sort_ms"] = _elapsed_ms(sort_started)
    seed_docs = sorted(seeds)
    expanded_docs = [doc_id for doc_id, _distance in ordered]
    return reranked, {
        "applied": True,
        "max_hops": max_hops,
        "rerank_weight": rerank_weight,
        "seed_docs": seed_docs,
        "expanded_docs": expanded_docs,
        "expanded_doc_total_count": len(distances),
        "expanded_doc_sample_count": len(expanded_docs),
        "seed_doc_weights": {doc_id: float(weight) for doc_id, weight in seed_doc_weights.items()},
        "boosted_results": boosted,
        # Backward compatible aliases.
        "seed_doc_count": len(seed_docs),
        "boosted_result_count": boosted,
        **_graph_trace_meta(graph, seed_source_counts=seed_source_counts),
        **_graph_timing_defaults(
            {
                **timing_meta,
                "graph_payload_doc_count": len(expanded_docs),
            }
        ),
    }
