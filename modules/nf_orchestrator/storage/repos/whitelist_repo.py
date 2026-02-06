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


def is_whitelisted(conn, project_id: str, claim_fingerprint: str, *, scope: str | None = None) -> bool:
    if scope is None:
        row = conn.execute(
            "SELECT wid FROM whitelist_item WHERE project_id = ? AND claim_fingerprint = ?",
            (project_id, claim_fingerprint),
        ).fetchone()
        return row is not None
    row = conn.execute(
        """
        SELECT wid
        FROM whitelist_item
        WHERE project_id = ? AND claim_fingerprint = ?
          AND (scope = 'global' OR scope = ?)
        """,
        (project_id, claim_fingerprint, scope),
    ).fetchone()
    return row is not None


def recompute_verdict_whitelist_flags(conn, project_id: str, *, claim_fingerprint: str | None = None) -> int:
    query = """
        UPDATE verdict_log
        SET whitelist_applied = CASE WHEN EXISTS (
            SELECT 1
            FROM whitelist_item w
            WHERE w.project_id = verdict_log.project_id
              AND w.claim_fingerprint = verdict_log.claim_fingerprint
              AND (w.scope = 'global' OR w.scope = verdict_log.input_doc_id)
        ) THEN 1 ELSE 0 END
        WHERE verdict_log.project_id = ?
    """
    params: list[Any] = [project_id]
    if claim_fingerprint is not None:
        query += " AND verdict_log.claim_fingerprint = ?"
        params.append(claim_fingerprint)
    cur = conn.execute(query, params)
    conn.commit()
    return cur.rowcount
