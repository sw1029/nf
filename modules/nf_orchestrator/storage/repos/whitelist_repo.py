from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_whitelist_item(
    conn,
    *,
    project_id: str,
    claim_fingerprint: str,
    scope: str,
    note: str | None = None,
) -> dict[str, Any]:
    wid = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO whitelist_item (wid, project_id, claim_fingerprint, scope, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (wid, project_id, claim_fingerprint, scope, note, ts),
    )
    conn.commit()
    return {
        "wid": wid,
        "project_id": project_id,
        "claim_fingerprint": claim_fingerprint,
        "scope": scope,
        "note": note,
        "created_at": ts,
    }


def delete_whitelist_item(conn, project_id: str, claim_fingerprint: str) -> bool:
    cur = conn.execute(
        "DELETE FROM whitelist_item WHERE project_id = ? AND claim_fingerprint = ?",
        (project_id, claim_fingerprint),
    )
    conn.commit()
    return cur.rowcount > 0


def is_whitelisted(conn, project_id: str, claim_fingerprint: str) -> bool:
    row = conn.execute(
        "SELECT wid FROM whitelist_item WHERE project_id = ? AND claim_fingerprint = ?",
        (project_id, claim_fingerprint),
    ).fetchone()
    return row is not None
