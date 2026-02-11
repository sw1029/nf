from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from modules.nf_retrieval.contracts import RetrievalRequest, RetrievalResult
from modules.nf_retrieval.fts.query_builder import build_fallback_query, build_query
from modules.nf_retrieval.fts.snippet import make_snippet
from modules.nf_shared.protocol.dtos import Chunk, EvidenceMatchType, FactStatus


def index_chunks(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    chunks: list[Chunk],
    text: str,
    commit: bool = True,
) -> None:
    conn.execute("DELETE FROM fts_docs WHERE snapshot_id = ?", (snapshot_id,))
    insert_sql = """
        INSERT INTO fts_docs (
            content, chunk_id, doc_id, snapshot_id, section_path,
            tag_path, episode_id, span_start, span_end
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

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
    inserted_rows = 0
    row_buffer: list[tuple[Any, ...]] = []
    buffer_limit = 2000

    def flush_rows() -> None:
        nonlocal inserted_rows
        if not row_buffer:
            return
        conn.executemany(insert_sql, row_buffer)
        inserted_rows += len(row_buffer)
        row_buffer.clear()

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
            row_buffer.append(
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
                )
            )
            if len(row_buffer) >= buffer_limit:
                flush_rows()

    flush_rows()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        conn.execute(
            """
            INSERT INTO fts_snapshot_meta (snapshot_id, row_count, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(snapshot_id) DO UPDATE SET
                row_count = excluded.row_count,
                updated_at = excluded.updated_at
            """,
            (snapshot_id, inserted_rows, ts),
        )
    except sqlite3.OperationalError:
        pass
    if commit:
        conn.commit()


def fts_search(conn: sqlite3.Connection, req: RetrievalRequest) -> list[RetrievalResult]:
    raw_query = req.get("query", "")
    raw_query_text = raw_query if isinstance(raw_query, str) else str(raw_query)
    query_text = build_query(raw_query)
    stats_raw = req.get("stats")
    stats = stats_raw if isinstance(stats_raw, dict) else None
    if stats is not None:
        stats.setdefault("rows_scanned", 0)
        stats.setdefault("chunks_processed", 0)
        stats.setdefault("query_mode", "fts")
    if not query_text:
        return []

    filters_raw = req.get("filters")
    filters = filters_raw if isinstance(filters_raw, dict) else {}

    def normalize_str_list(value: object, *, limit: int = 200) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            token = item.strip()
            if not token:
                continue
            if token in seen:
                continue
            seen.add(token)
            items.append(token)
            if len(items) >= limit:
                break
        return items

    params: list[Any] = [query_text]
    project_id = req.get("project_id")
    from_clause = "fts_docs"

    where = "fts_docs MATCH ?"
    project_scoped = False
    if isinstance(project_id, str) and project_id:
        try:
            has_chunk = conn.execute(
                "SELECT 1 FROM chunks WHERE project_id = ? LIMIT 1",
                (project_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            has_chunk = None
        project_scoped = has_chunk is not None
    if project_scoped:
        from_clause = "fts_docs JOIN chunks c ON c.chunk_id = fts_docs.chunk_id"
        where += " AND c.project_id = ?"
        params.append(project_id)
    if isinstance(filters.get("doc_id"), str):
        where += " AND doc_id = ?"
        params.append(filters["doc_id"])
    if isinstance(filters.get("snapshot_id"), str):
        where += " AND snapshot_id = ?"
        params.append(filters["snapshot_id"])
    doc_ids = normalize_str_list(filters.get("doc_ids"))
    if doc_ids:
        placeholders = ",".join("?" for _ in doc_ids)
        where += f" AND doc_id IN ({placeholders})"
        params.extend(doc_ids)
    snapshot_ids = normalize_str_list(filters.get("snapshot_ids"))
    if snapshot_ids:
        placeholders = ",".join("?" for _ in snapshot_ids)
        where += f" AND snapshot_id IN ({placeholders})"
        params.extend(snapshot_ids)
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
    fetch_limit = max(30, limit * 6)
    max_fetch_limit = max(fetch_limit, 240)
    sql = f"""
        SELECT
            content, chunk_id, doc_id, snapshot_id, section_path, tag_path,
            span_start, span_end,
            bm25(fts_docs) AS score,
            snippet(fts_docs, 0, '[', ']', '...', 24) AS snippet
        FROM {from_clause}
        WHERE {where}
        ORDER BY score
        LIMIT ?
    """
    query_params = list(params)

    def query_rows(limit_value: int) -> list[sqlite3.Row]:
        params_with_limit = [*query_params, limit_value]
        try:
            return conn.execute(sql, params_with_limit).fetchall()
        except sqlite3.OperationalError:
            fallback_query = build_fallback_query(raw_query_text)
            if not fallback_query or fallback_query == query_text:
                return []
            fallback_params = [fallback_query, *params_with_limit[1:]]
            try:
                rows_inner = conn.execute(sql, fallback_params).fetchall()
                if stats is not None:
                    stats["query_mode"] = "fts_fallback"
                return rows_inner
            except sqlite3.OperationalError:
                return []

    rows = query_rows(fetch_limit)
    if stats is not None:
        stats["rows_scanned"] = int(stats.get("rows_scanned", 0)) + len(rows)
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

    def fold_rows(rows_to_fold: list[sqlite3.Row]) -> None:
        for row in rows_to_fold:
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

    fold_rows(rows)
    while len(best_rows_by_chunk_id) < limit and fetch_limit < max_fetch_limit and len(rows) >= fetch_limit:
        fetch_limit = min(max_fetch_limit, fetch_limit * 2)
        rows = query_rows(fetch_limit)
        if stats is not None:
            stats["rows_scanned"] = int(stats.get("rows_scanned", 0)) + len(rows)
        fold_rows(rows)

    unique_rows = list(best_rows_by_chunk_id.values())
    unique_rows.sort(key=lambda r: float(r["score"]) if r["score"] is not None else 0.0)
    unique_rows = unique_rows[:limit]
    if stats is not None:
        stats["chunks_processed"] = int(stats.get("chunks_processed", 0)) + len(unique_rows)

    results: list[RetrievalResult] = []
    for row in unique_rows:
        content = row["content"] or ""
        snippet = row["snippet"] or ""
        if not snippet:
            snippet = make_snippet(content, raw_query_text)
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
