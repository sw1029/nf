from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_checksum(conn: sqlite3.Connection, doc_id: str) -> str | None:
    try:
        row = conn.execute("SELECT checksum FROM fts_meta WHERE doc_id = ?", (doc_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    checksum = row["checksum"]
    return checksum if isinstance(checksum, str) and checksum else None


def upsert(conn: sqlite3.Connection, doc_id: str, checksum: str) -> None:
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO fts_meta (doc_id, checksum, last_indexed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET checksum = excluded.checksum, last_indexed_at = excluded.last_indexed_at
        """,
        (doc_id, checksum, ts),
    )
    conn.commit()

