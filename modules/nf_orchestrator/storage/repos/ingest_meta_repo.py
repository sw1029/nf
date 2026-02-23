from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_state(conn: sqlite3.Connection, doc_id: str) -> tuple[str, str] | None:
    try:
        row = conn.execute(
            "SELECT snapshot_id, checksum FROM ingest_meta WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    snapshot_id = row["snapshot_id"]
    checksum = row["checksum"]
    if not isinstance(snapshot_id, str) or not isinstance(checksum, str):
        return None
    if not snapshot_id or not checksum:
        return None
    return snapshot_id, checksum


def upsert(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    snapshot_id: str,
    checksum: str,
    commit: bool = True,
) -> None:
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO ingest_meta (doc_id, snapshot_id, checksum, last_ingested_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET
            snapshot_id = excluded.snapshot_id,
            checksum = excluded.checksum,
            last_ingested_at = excluded.last_ingested_at
        """,
        (doc_id, snapshot_id, checksum, ts),
    )
    if commit:
        conn.commit()
