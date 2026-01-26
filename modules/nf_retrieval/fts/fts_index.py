from __future__ import annotations

import sqlite3
from typing import Any

from modules.nf_retrieval.contracts import RetrievalRequest, RetrievalResult
from modules.nf_retrieval.fts.query_builder import build_query
from modules.nf_retrieval.fts.snippet import make_snippet
from modules.nf_shared.protocol.dtos import Chunk, EvidenceMatchType


def index_chunks(conn: sqlite3.Connection, *, snapshot_id: str, chunks: list[Chunk], text: str) -> None:
    conn.execute("DELETE FROM fts_docs WHERE snapshot_id = ?", (snapshot_id,))
    for chunk in chunks:
        content = text[chunk.span_start : chunk.span_end]
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
                "",
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
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    results: list[RetrievalResult] = []
    for row in rows:
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
