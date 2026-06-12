from __future__ import annotations

import json
import uuid
from typing import Any

from .schema_rows import _now_ts


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def new_source_id() -> str:
    return str(uuid.uuid4())


def source_id_from_node_ref(node_ref: str) -> str | None:
    if not isinstance(node_ref, str) or not node_ref.startswith("ext:"):
        return None
    parts = node_ref.split(":", 2)
    if len(parts) != 3 or not parts[1]:
        return None
    return parts[1]


def _row_to_source(row: Any) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "project_id": row["project_id"],
        "source_kind": row["source_kind"],
        "source_label": row["source_label"],
        "linked_project_id": row["linked_project_id"],
        "schema_version": row["schema_version"],
        "adapter_version": row["adapter_version"],
        "color": row["color"],
        "enabled": bool(row["enabled"]),
        "warnings": _json_loads(row["warnings_json"], []),
        "metadata": _json_loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_node(row: Any) -> dict[str, Any]:
    return {
        "node_ref": row["node_ref"],
        "project_id": row["project_id"],
        "source_id": row["source_id"],
        "native_id": row["native_id"],
        "node_type": row["node_type"],
        "label": row["label"],
        "aliases": _json_loads(row["aliases_json"], []),
        "payload": _json_loads(row["payload_json"], {}),
        "evidence_refs": _json_loads(row["evidence_refs_json"], []),
        "status": row["status"],
        "confidence": float(row["confidence"]),
    }


def _row_to_edge(row: Any) -> dict[str, Any]:
    return {
        "edge_ref": row["edge_ref"],
        "project_id": row["project_id"],
        "source_id": row["source_id"],
        "native_id": row["native_id"],
        "src_node_ref": row["src_node_ref"],
        "dst_node_ref": row["dst_node_ref"],
        "edge_type": row["edge_type"],
        "label": row["label"],
        "payload": _json_loads(row["payload_json"], {}),
        "evidence_refs": _json_loads(row["evidence_refs_json"], []),
        "status": row["status"],
        "confidence": float(row["confidence"]),
    }


def _row_to_link(row: Any) -> dict[str, Any]:
    return {
        "link_id": row["link_id"],
        "project_id": row["project_id"],
        "source_id": row["source_id"],
        "src_node_ref": row["src_node_ref"],
        "dst_node_ref": row["dst_node_ref"],
        "relation_type": row["relation_type"],
        "label": row["label"],
        "note": row["note"],
        "confidence": float(row["confidence"]),
        "status": row["status"],
        "payload": _json_loads(row["payload_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_favorite(row: Any) -> dict[str, Any]:
    return {
        "project_id": row["project_id"],
        "node_ref": row["node_ref"],
        "node_kind": row["node_kind"],
        "source_id": row["source_id"],
        "label_snapshot": row["label_snapshot"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def replace_external_graph_source(
    conn,
    *,
    project_id: str,
    bundle: dict[str, Any],
    color: str = "#14b8a6",
    enabled: bool = True,
    commit: bool = True,
) -> dict[str, Any]:
    source_id = str(bundle["source_id"])
    now = _now_ts()
    metadata = dict(bundle.get("metadata") or {})
    linked_project_id = metadata.get("linked_project_id")
    if linked_project_id is not None:
        linked_project_id = str(linked_project_id)
    existing = conn.execute(
        "SELECT created_at FROM external_graph_source WHERE project_id = ? AND source_id = ?",
        (project_id, source_id),
    ).fetchone()
    created_at = existing["created_at"] if existing is not None else now
    conn.execute(
        """
        INSERT INTO external_graph_source (
            source_id, project_id, source_kind, source_label, linked_project_id,
            schema_version, adapter_version, color, enabled, warnings_json,
            metadata_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            source_kind = excluded.source_kind,
            source_label = excluded.source_label,
            linked_project_id = excluded.linked_project_id,
            schema_version = excluded.schema_version,
            adapter_version = excluded.adapter_version,
            color = excluded.color,
            enabled = excluded.enabled,
            warnings_json = excluded.warnings_json,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        (
            source_id,
            project_id,
            str(bundle.get("source_kind") or "dataset_artifact_set"),
            str(bundle.get("source_label") or "외부 작품"),
            linked_project_id,
            str(bundle.get("schema_version") or "unknown"),
            str(bundle.get("adapter_version") or "unknown"),
            color,
            1 if enabled else 0,
            _json_dumps(bundle.get("warnings") or []),
            _json_dumps(metadata),
            created_at,
            now,
        ),
    )
    conn.execute("DELETE FROM external_graph_edge WHERE project_id = ? AND source_id = ?", (project_id, source_id))
    conn.execute("DELETE FROM external_graph_node WHERE project_id = ? AND source_id = ?", (project_id, source_id))

    node_rows = []
    for node in bundle.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_rows.append(
            (
                str(node["node_ref"]),
                project_id,
                source_id,
                str(node.get("native_id") or ""),
                str(node.get("node_type") or "Fact"),
                str(node.get("label") or ""),
                _json_dumps(node.get("aliases") or []),
                _json_dumps(node.get("payload") or {}),
                _json_dumps(node.get("evidence_refs") or []),
                str(node.get("status") or "ACTIVE"),
                float(node.get("confidence", 1.0) or 1.0),
            )
        )
    if node_rows:
        conn.executemany(
            """
            INSERT INTO external_graph_node (
                node_ref, project_id, source_id, native_id, node_type, label,
                aliases_json, payload_json, evidence_refs_json, status, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            node_rows,
        )

    edge_rows = []
    for edge in bundle.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        edge_rows.append(
            (
                str(edge["edge_ref"]),
                project_id,
                source_id,
                str(edge.get("native_id") or ""),
                str(edge.get("src_node_ref") or ""),
                str(edge.get("dst_node_ref") or ""),
                str(edge.get("edge_type") or "RELATED"),
                str(edge.get("label") or edge.get("edge_type") or "RELATED"),
                _json_dumps(edge.get("payload") or {}),
                _json_dumps(edge.get("evidence_refs") or []),
                str(edge.get("status") or "ACTIVE"),
                float(edge.get("confidence", 1.0) or 1.0),
            )
        )
    if edge_rows:
        conn.executemany(
            """
            INSERT INTO external_graph_edge (
                edge_ref, project_id, source_id, native_id, src_node_ref,
                dst_node_ref, edge_type, label, payload_json,
                evidence_refs_json, status, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            edge_rows,
        )
    if commit:
        conn.commit()
    loaded = get_external_source(conn, project_id=project_id, source_id=source_id)
    return loaded or {}


def list_external_sources(conn, project_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    where = "project_id = ?"
    params: list[Any] = [project_id]
    if enabled_only:
        where += " AND enabled = 1"
    rows = conn.execute(
        f"""
        SELECT *
        FROM external_graph_source
        WHERE {where}
        ORDER BY updated_at DESC, source_label ASC
        """,
        tuple(params),
    ).fetchall()
    return [_row_to_source(row) for row in rows]


def get_external_source(conn, *, project_id: str, source_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM external_graph_source WHERE project_id = ? AND source_id = ?",
        (project_id, source_id),
    ).fetchone()
    return _row_to_source(row) if row is not None else None


def update_external_source(
    conn,
    *,
    project_id: str,
    source_id: str,
    enabled: bool | None = None,
    color: str | None = None,
    source_label: str | None = None,
    commit: bool = True,
) -> dict[str, Any] | None:
    existing = get_external_source(conn, project_id=project_id, source_id=source_id)
    if existing is None:
        return None
    conn.execute(
        """
        UPDATE external_graph_source
        SET enabled = ?, color = ?, source_label = ?, updated_at = ?
        WHERE project_id = ? AND source_id = ?
        """,
        (
            1 if (existing["enabled"] if enabled is None else enabled) else 0,
            color if color is not None else existing["color"],
            source_label if source_label is not None else existing["source_label"],
            _now_ts(),
            project_id,
            source_id,
        ),
    )
    if commit:
        conn.commit()
    return get_external_source(conn, project_id=project_id, source_id=source_id)


def delete_external_source(conn, *, project_id: str, source_id: str, commit: bool = True) -> bool:
    conn.execute("DELETE FROM external_graph_link WHERE project_id = ? AND source_id = ?", (project_id, source_id))
    conn.execute("DELETE FROM external_graph_edge WHERE project_id = ? AND source_id = ?", (project_id, source_id))
    conn.execute("DELETE FROM external_graph_node WHERE project_id = ? AND source_id = ?", (project_id, source_id))
    cur = conn.execute(
        "DELETE FROM external_graph_source WHERE project_id = ? AND source_id = ?",
        (project_id, source_id),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0


def list_external_nodes(conn, project_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    join = ""
    where = "n.project_id = ?"
    if enabled_only:
        join = "JOIN external_graph_source s ON s.project_id = n.project_id AND s.source_id = n.source_id"
        where += " AND s.enabled = 1"
    rows = conn.execute(
        f"""
        SELECT n.*
        FROM external_graph_node n
        {join}
        WHERE {where}
        ORDER BY n.source_id ASC, n.node_type ASC, n.label ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_node(row) for row in rows]


def list_external_edges(conn, project_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    join = ""
    where = "e.project_id = ?"
    if enabled_only:
        join = "JOIN external_graph_source s ON s.project_id = e.project_id AND s.source_id = e.source_id"
        where += " AND s.enabled = 1"
    rows = conn.execute(
        f"""
        SELECT e.*
        FROM external_graph_edge e
        {join}
        WHERE {where}
        ORDER BY e.source_id ASC, e.edge_type ASC, e.src_node_ref ASC, e.dst_node_ref ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_edge(row) for row in rows]


def list_external_links(
    conn,
    project_id: str,
    *,
    active_only: bool = False,
    enabled_sources_only: bool = False,
) -> list[dict[str, Any]]:
    join = ""
    where = "l.project_id = ?"
    if active_only:
        where += " AND l.status = 'ACTIVE'"
    if enabled_sources_only:
        join = "JOIN external_graph_source s ON s.project_id = l.project_id AND s.source_id = l.source_id"
        where += " AND s.enabled = 1"
    rows = conn.execute(
        f"""
        SELECT l.*
        FROM external_graph_link l
        {join}
        WHERE {where}
        ORDER BY l.updated_at DESC, l.created_at DESC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_link(row) for row in rows]


def get_external_node(conn, *, project_id: str, node_ref: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM external_graph_node WHERE project_id = ? AND node_ref = ?",
        (project_id, node_ref),
    ).fetchone()
    return _row_to_node(row) if row is not None else None


def create_external_link(
    conn,
    *,
    project_id: str,
    source_id: str,
    src_node_ref: str,
    dst_node_ref: str,
    relation_type: str,
    label: str,
    note: str | None = None,
    confidence: float = 0.75,
    payload: dict[str, Any] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    link_id = str(uuid.uuid4())
    now = _now_ts()
    conn.execute(
        """
        INSERT INTO external_graph_link (
            link_id, project_id, source_id, src_node_ref, dst_node_ref,
            relation_type, label, note, confidence, status, payload_json,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            link_id,
            project_id,
            source_id,
            src_node_ref,
            dst_node_ref,
            relation_type,
            label,
            note,
            float(confidence),
            "ACTIVE",
            _json_dumps(payload or {}),
            now,
            now,
        ),
    )
    if commit:
        conn.commit()
    return get_external_link(conn, project_id=project_id, link_id=link_id) or {}


def get_external_link(conn, *, project_id: str, link_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM external_graph_link WHERE project_id = ? AND link_id = ?",
        (project_id, link_id),
    ).fetchone()
    return _row_to_link(row) if row is not None else None


def update_external_link(
    conn,
    *,
    project_id: str,
    link_id: str,
    relation_type: str | None = None,
    label: str | None = None,
    note: str | None = None,
    confidence: float | None = None,
    status: str | None = None,
    commit: bool = True,
) -> dict[str, Any] | None:
    existing = get_external_link(conn, project_id=project_id, link_id=link_id)
    if existing is None:
        return None
    conn.execute(
        """
        UPDATE external_graph_link
        SET relation_type = ?, label = ?, note = ?, confidence = ?, status = ?, updated_at = ?
        WHERE project_id = ? AND link_id = ?
        """,
        (
            relation_type if relation_type is not None else existing["relation_type"],
            label if label is not None else existing["label"],
            note if note is not None else existing["note"],
            float(confidence if confidence is not None else existing["confidence"]),
            status if status is not None else existing["status"],
            _now_ts(),
            project_id,
            link_id,
        ),
    )
    if commit:
        conn.commit()
    return get_external_link(conn, project_id=project_id, link_id=link_id)


def delete_external_link(conn, *, project_id: str, link_id: str, commit: bool = True) -> bool:
    cur = conn.execute(
        "DELETE FROM external_graph_link WHERE project_id = ? AND link_id = ?",
        (project_id, link_id),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0


def list_graph_favorites(conn, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM graph_favorite
        WHERE project_id = ?
        ORDER BY created_at DESC, label_snapshot ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_favorite(row) for row in rows]


def get_graph_favorite(conn, *, project_id: str, node_ref: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM graph_favorite WHERE project_id = ? AND node_ref = ?",
        (project_id, node_ref),
    ).fetchone()
    return _row_to_favorite(row) if row is not None else None


def upsert_graph_favorite(
    conn,
    *,
    project_id: str,
    node_ref: str,
    node_kind: str,
    label_snapshot: str,
    source_id: str | None = None,
    note: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    now = _now_ts()
    conn.execute(
        """
        INSERT INTO graph_favorite (
            project_id, node_ref, node_kind, source_id, label_snapshot, note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, node_ref) DO UPDATE SET
            node_kind = excluded.node_kind,
            source_id = excluded.source_id,
            label_snapshot = excluded.label_snapshot,
            note = excluded.note
        """,
        (project_id, node_ref, node_kind, source_id, label_snapshot, note, now),
    )
    if commit:
        conn.commit()
    return get_graph_favorite(conn, project_id=project_id, node_ref=node_ref) or {
        "project_id": project_id,
        "node_ref": node_ref,
        "node_kind": node_kind,
        "source_id": source_id,
        "label_snapshot": label_snapshot,
        "note": note,
        "created_at": now,
    }


def delete_graph_favorite(conn, *, project_id: str, node_ref: str, commit: bool = True) -> bool:
    cur = conn.execute(
        "DELETE FROM graph_favorite WHERE project_id = ? AND node_ref = ?",
        (project_id, node_ref),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0


def load_external_graph_overlay(conn, project_id: str, *, enabled_only: bool = False) -> dict[str, Any]:
    return {
        "sources": list_external_sources(conn, project_id, enabled_only=enabled_only),
        "nodes": list_external_nodes(conn, project_id, enabled_only=enabled_only),
        "edges": list_external_edges(conn, project_id, enabled_only=enabled_only),
        "links": list_external_links(
            conn,
            project_id,
            active_only=enabled_only,
            enabled_sources_only=enabled_only,
        ),
        "favorites": list_graph_favorites(conn, project_id),
    }
