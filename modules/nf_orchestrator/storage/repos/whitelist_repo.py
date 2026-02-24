from __future__ import annotations

import json
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


def set_whitelist_annotation(
    conn,
    *,
    project_id: str,
    claim_fingerprint: str,
    scope: str,
    intent_type: str,
    reason: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    annotation_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        DELETE FROM whitelist_annotation
        WHERE project_id = ? AND claim_fingerprint = ? AND scope = ?
        """,
        (project_id, claim_fingerprint, scope),
    )
    conn.execute(
        """
        INSERT INTO whitelist_annotation (
            annotation_id, project_id, claim_fingerprint, scope, intent_type, reason, meta_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            annotation_id,
            project_id,
            claim_fingerprint,
            scope,
            intent_type,
            reason,
            json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else None,
            ts,
        ),
    )
    conn.commit()
    return {
        "annotation_id": annotation_id,
        "project_id": project_id,
        "claim_fingerprint": claim_fingerprint,
        "scope": scope,
        "intent_type": intent_type,
        "reason": reason,
        "meta": dict(meta) if isinstance(meta, dict) else None,
        "created_at": ts,
    }


def delete_whitelist_annotations(conn, project_id: str, claim_fingerprint: str) -> int:
    cur = conn.execute(
        "DELETE FROM whitelist_annotation WHERE project_id = ? AND claim_fingerprint = ?",
        (project_id, claim_fingerprint),
    )
    conn.commit()
    return cur.rowcount


def get_whitelist_annotation(
    conn,
    project_id: str,
    claim_fingerprint: str,
    *,
    scope: str | None = None,
) -> dict[str, Any] | None:
    if isinstance(scope, str) and scope:
        row = conn.execute(
            """
            SELECT *
            FROM whitelist_annotation
            WHERE project_id = ? AND claim_fingerprint = ?
              AND (scope = ? OR scope = 'global')
            ORDER BY CASE WHEN scope = ? THEN 0 ELSE 1 END ASC, created_at DESC
            LIMIT 1
            """,
            (project_id, claim_fingerprint, scope, scope),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT *
            FROM whitelist_annotation
            WHERE project_id = ? AND claim_fingerprint = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, claim_fingerprint),
        ).fetchone()
    if row is None:
        return None

    meta_raw = row["meta_json"] if "meta_json" in row.keys() else None
    meta: dict[str, Any] | None = None
    if isinstance(meta_raw, str) and meta_raw:
        try:
            parsed = json.loads(meta_raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            meta = parsed

    reason_raw = row["reason"] if "reason" in row.keys() else None
    return {
        "annotation_id": row["annotation_id"],
        "project_id": row["project_id"],
        "claim_fingerprint": row["claim_fingerprint"],
        "scope": row["scope"],
        "intent_type": row["intent_type"],
        "reason": reason_raw if isinstance(reason_raw, str) and reason_raw else None,
        "meta": meta,
        "created_at": row["created_at"],
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
