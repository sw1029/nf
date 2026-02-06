from __future__ import annotations

import sqlite3
from typing import Any

from modules.nf_retrieval.contracts import RetrievalRequest, RetrievalResult
from modules.nf_retrieval.fts.query_builder import build_query
from modules.nf_retrieval.fts.snippet import make_snippet
from modules.nf_shared.protocol.dtos import Chunk, EvidenceMatchType, FactStatus


def index_chunks(conn: sqlite3.Connection, *, snapshot_id: str, chunks: list[Chunk], text: str) -> None:
    conn.execute("DELETE FROM fts_docs WHERE snapshot_id = ?", (snapshot_id,))

    try:
        tag_rows = conn.execute(
            """
            SELECT span_start, span_end, tag_path
            FROM tag_assignment
            WHERE snapshot_id = ?
            ORDER BY span_start ASC
            """,
            (snapshot_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        tag_rows = []
    tag_spans: list[tuple[int, int, str]] = [
        (int(row["span_start"]), int(row["span_end"]), str(row["tag_path"] or "")) for row in tag_rows
    ]
    tag_i = 0
    for chunk in chunks:
        content = text[chunk.span_start : chunk.span_end]
        chunk_start = int(chunk.span_start)
        chunk_end = int(chunk.span_end)
        while tag_i < len(tag_spans) and tag_spans[tag_i][1] <= chunk_start:
            tag_i += 1
        overlap_scores: dict[str, int] = {}
        tag_j = tag_i
        while tag_j < len(tag_spans) and tag_spans[tag_j][0] < chunk_end:
            tag_start, tag_end, tag_path = tag_spans[tag_j]
            if chunk_start < tag_end and tag_start < chunk_end and tag_path:
                overlap = min(chunk_end, tag_end) - max(chunk_start, tag_start)
                prev = overlap_scores.get(tag_path, 0)
                if overlap > prev:
                    overlap_scores[tag_path] = overlap
            tag_j += 1
        tag_paths = [
            tag_path
            for tag_path, _score in sorted(
                overlap_scores.items(),
                key=lambda kv: (-kv[1], -len(kv[0]), kv[0]),
            )
        ]
        if not tag_paths:
            tag_paths = [""]
        for tag_path in tag_paths:
            conn.execute(
                """
                INSERT INTO fts_docs (
                    content, chunk_id, doc_id, snapshot_id, section_path,
                    tag_path, episode_id, span_start, span_end
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content,
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.snapshot_id,
                    chunk.section_path,
                    tag_path,
                    chunk.episode_id,
                    chunk.span_start,
                    chunk.span_end,
                ),
            )
    conn.commit()


def fts_search(conn: sqlite3.Connection, req: RetrievalRequest) -> list[RetrievalResult]:
    query_text = build_query(req.get("query", ""))
    if not query_text:
        return []

    filters = req.get("filters") or {}
    params: list[Any] = [query_text]

    where = "fts_docs MATCH ?"
    if isinstance(filters, dict) and isinstance(filters.get("doc_id"), str):
        where += " AND doc_id = ?"
        params.append(filters["doc_id"])
    if filters.get("tag_path"):
        where += " AND tag_path = ?"
        params.append(filters["tag_path"])
    if filters.get("section"):
        where += " AND section_path = ?"
        params.append(filters["section"])
    if filters.get("episode"):
        where += " AND episode_id = ?"
        params.append(filters["episode"])

    limit = int(req.get("k") or 10)
    fetch_limit = max(50, limit * 10)
    sql = f"""
        SELECT
            content, chunk_id, doc_id, snapshot_id, section_path, tag_path,
            span_start, span_end,
            bm25(fts_docs) AS score,
            snippet(fts_docs, 0, '[', ']', '...', 24) AS snippet
        FROM fts_docs
        WHERE {where}
        ORDER BY score
        LIMIT ?
    """
    params.append(fetch_limit)

    rows = conn.execute(sql, params).fetchall()
    entity_filter = filters.get("entity_id")
    time_key_filter = filters.get("time_key")
    timeline_idx_filter = filters.get("timeline_idx")
    if not isinstance(entity_filter, str):
        entity_filter = None
    if not isinstance(time_key_filter, str):
        time_key_filter = None
    if not isinstance(timeline_idx_filter, int):
        try:
            timeline_idx_filter = int(timeline_idx_filter)
        except (TypeError, ValueError):
            timeline_idx_filter = None

    entity_cache: dict[tuple[str, str], list[tuple[int, int]]] = {}
    time_cache: dict[tuple[str, str | None, int | None], list[tuple[int, int]]] = {}

    def span_overlaps(span_start: int, span_end: int, spans: list[tuple[int, int]]) -> bool:
        for other_start, other_end in spans:
            if span_start < other_end and other_start < span_end:
                return True
        return False

    def load_entity_spans(doc_id: str, entity_id: str) -> list[tuple[int, int]]:
        key = (doc_id, entity_id)
        if key in entity_cache:
            return entity_cache[key]
        rows_inner = conn.execute(
            """
            SELECT span_start, span_end
            FROM entity_mention_span
            WHERE project_id = ? AND doc_id = ? AND entity_id = ? AND status != ?
            """,
            (req.get("project_id"), doc_id, entity_id, FactStatus.REJECTED.value),
        ).fetchall()
        spans = [(row["span_start"], row["span_end"]) for row in rows_inner]
        entity_cache[key] = spans
        return spans

    def load_time_spans(doc_id: str, time_key: str | None, timeline_idx: int | None) -> list[tuple[int, int]]:
        key = (doc_id, time_key, timeline_idx)
        if key in time_cache:
            return time_cache[key]
        query_inner = """
            SELECT span_start, span_end
            FROM time_anchor
            WHERE project_id = ? AND doc_id = ? AND status != ?
        """
        params_inner: list[Any] = [req.get("project_id"), doc_id, FactStatus.REJECTED.value]
        if time_key is not None:
            query_inner += " AND time_key = ?"
            params_inner.append(time_key)
        if timeline_idx is not None:
            query_inner += " AND timeline_idx = ?"
            params_inner.append(timeline_idx)
        rows_inner = conn.execute(query_inner, params_inner).fetchall()
        spans = [(row["span_start"], row["span_end"]) for row in rows_inner]
        time_cache[key] = spans
        return spans
    best_rows_by_chunk_id: dict[str, sqlite3.Row] = {}
    for row in rows:
        if entity_filter or time_key_filter or timeline_idx_filter is not None:
            doc_id = row["doc_id"]
            span_start = row["span_start"]
            span_end = row["span_end"]
            if entity_filter:
                spans = load_entity_spans(doc_id, entity_filter)
                if not span_overlaps(span_start, span_end, spans):
                    continue
            if time_key_filter or timeline_idx_filter is not None:
                spans = load_time_spans(doc_id, time_key_filter, timeline_idx_filter)
                if not span_overlaps(span_start, span_end, spans):
                    continue
        chunk_id = row["chunk_id"]
        if not isinstance(chunk_id, str):
            continue
        existing = best_rows_by_chunk_id.get(chunk_id)
        if existing is None:
            best_rows_by_chunk_id[chunk_id] = row
            continue
        try:
            existing_score = float(existing["score"]) if existing["score"] is not None else 0.0
        except (TypeError, ValueError):
            existing_score = 0.0
        try:
            score = float(row["score"]) if row["score"] is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0
        existing_tag = existing["tag_path"] or ""
        tag_path = row["tag_path"] or ""
        if score < existing_score or (score == existing_score and len(tag_path) > len(existing_tag)):
            best_rows_by_chunk_id[chunk_id] = row

    unique_rows = list(best_rows_by_chunk_id.values())
    unique_rows.sort(key=lambda r: float(r["score"]) if r["score"] is not None else 0.0)
    unique_rows = unique_rows[:limit]

    results: list[RetrievalResult] = []
    for row in unique_rows:
        content = row["content"] or ""
        snippet = row["snippet"] or ""
        if not snippet:
            snippet = make_snippet(content, query_text)
        score = float(row["score"]) if row["score"] is not None else 0.0
        results.append(
            {
                "source": "fts",
                "score": score,
                "evidence": {
                    "doc_id": row["doc_id"],
                    "snapshot_id": row["snapshot_id"],
                    "chunk_id": row["chunk_id"],
                    "section_path": row["section_path"],
                    "tag_path": row["tag_path"],
                    "snippet_text": snippet,
                    "span_start": row["span_start"],
                    "span_end": row["span_end"],
                    "fts_score": score,
                    "match_type": EvidenceMatchType.EXACT.value,
                    "confirmed": False,
                },
            }
        )
    return results
