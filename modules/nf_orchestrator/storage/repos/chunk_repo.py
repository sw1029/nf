from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from modules.nf_shared.protocol.dtos import Chunk, FactSource


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_chunk(row: Any) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"],
        project_id=row["project_id"],
        doc_id=row["doc_id"],
        snapshot_id=row["snapshot_id"],
        section_path=row["section_path"],
        episode_id=row["episode_id"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        token_count_est=row["token_count_est"],
        created_by=FactSource(row["created_by"]),
        created_at=row["created_at"],
    )


def replace_chunks_for_snapshot(conn, snapshot_id: str, chunks: list[Chunk], *, commit: bool = True) -> None:
    conn.execute("DELETE FROM chunks WHERE snapshot_id = ?", (snapshot_id,))
    for chunk in chunks:
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, project_id, doc_id, snapshot_id, section_path, episode_id,
                span_start, span_end, token_count_est, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.project_id,
                chunk.doc_id,
                chunk.snapshot_id,
                chunk.section_path,
                chunk.episode_id,
                chunk.span_start,
                chunk.span_end,
                chunk.token_count_est,
                chunk.created_by.value,
                chunk.created_at,
            ),
        )
    if commit:
        conn.commit()


def new_chunk_id() -> str:
    return str(uuid.uuid4())


def build_chunk(
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    section_path: str,
    span_start: int,
    span_end: int,
    episode_id: str | None = None,
    token_count_est: int | None = None,
    created_by: FactSource = FactSource.AUTO,
) -> Chunk:
    return Chunk(
        chunk_id=new_chunk_id(),
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        section_path=section_path,
        episode_id=episode_id,
        span_start=span_start,
        span_end=span_end,
        token_count_est=token_count_est,
        created_by=created_by,
        created_at=_now_ts(),
    )


def list_chunks_for_snapshot(conn, snapshot_id: str) -> list[Chunk]:
    rows = conn.execute(
        "SELECT * FROM chunks WHERE snapshot_id = ? ORDER BY span_start ASC",
        (snapshot_id,),
    ).fetchall()
    return [_row_to_chunk(row) for row in rows]
