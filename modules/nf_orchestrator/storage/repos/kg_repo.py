from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

from .schema_rows import _now_ts


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def replace_project_kg_build(
    conn,
    *,
    project_id: str,
    source_checksum: str,
    source_health: dict[str, Any],
    stats: dict[str, Any],
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    build_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    build_id = build_id or str(uuid.uuid4())
    built_at = _now_ts()
    conn.execute("DELETE FROM kg_edge WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM kg_node WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM kg_build WHERE project_id = ?", (project_id,))
    conn.execute(
        """
        INSERT INTO kg_build (
            build_id, project_id, built_at, source_checksum,
            source_health_json, stats_json, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            build_id,
            project_id,
            built_at,
            source_checksum,
            _json_dumps(source_health),
            _json_dumps(stats),
            "SUCCEEDED",
        ),
    )
    node_rows = []
    for node in nodes:
        node_rows.append(
            (
                str(node["node_id"]),
                project_id,
                build_id,
                str(node["node_type"]),
                str(node["source_table"]),
                str(node["source_id"]),
                str(node.get("label") or ""),
                _json_dumps(node.get("payload") or {}),
                str(node.get("status") or "ACTIVE"),
                float(node.get("confidence", 1.0) or 1.0),
            )
        )
    if node_rows:
        conn.executemany(
            """
            INSERT INTO kg_node (
                node_id, project_id, build_id, node_type, source_table,
                source_id, label, payload_json, status, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            node_rows,
        )
    edge_rows = []
    for edge in edges:
        edge_rows.append(
            (
                str(edge["edge_id"]),
                project_id,
                build_id,
                str(edge["src_node_id"]),
                str(edge["dst_node_id"]),
                str(edge["edge_type"]),
                str(edge["source_table"]),
                str(edge["source_id"]),
                _json_dumps(edge.get("payload") or {}),
                str(edge.get("status") or "ACTIVE"),
                float(edge.get("confidence", 1.0) or 1.0),
            )
        )
    if edge_rows:
        conn.executemany(
            """
            INSERT INTO kg_edge (
                edge_id, project_id, build_id, src_node_id, dst_node_id,
                edge_type, source_table, source_id, payload_json, status, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            edge_rows,
        )
    if commit:
        conn.commit()
    return {
        "build_id": build_id,
        "project_id": project_id,
        "built_at": built_at,
        "source_checksum": source_checksum,
        "source_health": dict(source_health),
        "stats": dict(stats),
        "status": "SUCCEEDED",
    }


def get_latest_project_kg_build(conn, project_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM kg_build
        WHERE project_id = ? AND status = 'SUCCEEDED'
        ORDER BY built_at DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "build_id": row["build_id"],
        "project_id": row["project_id"],
        "built_at": row["built_at"],
        "source_checksum": row["source_checksum"],
        "source_health": json.loads(row["source_health_json"] or "{}"),
        "stats": json.loads(row["stats_json"] or "{}"),
        "status": row["status"],
    }


def list_kg_nodes(conn, *, project_id: str, build_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM kg_node
        WHERE project_id = ? AND build_id = ?
        ORDER BY node_type ASC, source_table ASC, source_id ASC
        """,
        (project_id, build_id),
    ).fetchall()
    return [
        {
            "node_id": row["node_id"],
            "project_id": row["project_id"],
            "build_id": row["build_id"],
            "node_type": row["node_type"],
            "source_table": row["source_table"],
            "source_id": row["source_id"],
            "label": row["label"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "status": row["status"],
            "confidence": float(row["confidence"]),
        }
        for row in rows
    ]


def list_kg_edges(conn, *, project_id: str, build_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM kg_edge
        WHERE project_id = ? AND build_id = ?
        ORDER BY edge_type ASC, source_table ASC, source_id ASC, src_node_id ASC, dst_node_id ASC
        """,
        (project_id, build_id),
    ).fetchall()
    return [
        {
            "edge_id": row["edge_id"],
            "project_id": row["project_id"],
            "build_id": row["build_id"],
            "src_node_id": row["src_node_id"],
            "dst_node_id": row["dst_node_id"],
            "edge_type": row["edge_type"],
            "source_table": row["source_table"],
            "source_id": row["source_id"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "status": row["status"],
            "confidence": float(row["confidence"]),
        }
        for row in rows
    ]


def load_latest_project_kg(conn, project_id: str) -> dict[str, Any] | None:
    build = get_latest_project_kg_build(conn, project_id)
    if build is None:
        return None
    build_id = str(build["build_id"])
    return {
        "build": build,
        "nodes": list_kg_nodes(conn, project_id=project_id, build_id=build_id),
        "edges": list_kg_edges(conn, project_id=project_id, build_id=build_id),
    }
