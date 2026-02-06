from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_ignore_item(
    conn,
    *,
    project_id: str,
    claim_fingerprint: str,
    scope: str,
    kind: str,
    note: str | None = None,
) -> dict[str, Any]:
    iid = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO ignore_item (iid, project_id, claim_fingerprint, scope, kind, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (iid, project_id, claim_fingerprint, scope, kind, note, ts),
    )
    conn.commit()
    return {
        "iid": iid,
        "project_id": project_id,
        "claim_fingerprint": claim_fingerprint,
        "scope": scope,
        "kind": kind,
        "note": note,
        "created_at": ts,
    }


def delete_ignore_item(
    conn,
    project_id: str,
    claim_fingerprint: str,
    *,
    scope: str | None = None,
    kind: str | None = None,
) -> bool:
    query = "DELETE FROM ignore_item WHERE project_id = ? AND claim_fingerprint = ?"
    params: list[Any] = [project_id, claim_fingerprint]
    if scope is not None:
        query += " AND scope = ?"
        params.append(scope)
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    cur = conn.execute(query, params)
    conn.commit()
    return cur.rowcount > 0


def is_ignored(
    conn,
    project_id: str,
    claim_fingerprint: str,
    *,
    scope: str | None = None,
    kind: str | None = None,
) -> bool:
    query = "SELECT iid FROM ignore_item WHERE project_id = ? AND claim_fingerprint = ?"
    params: list[Any] = [project_id, claim_fingerprint]
    if scope is not None:
        query += " AND (scope = 'global' OR scope = ?)"
        params.append(scope)
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    row = conn.execute(query, params).fetchone()
    return row is not None

