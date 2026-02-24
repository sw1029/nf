from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from modules.nf_shared.protocol.dtos import (
    Entity,
    EntityAlias,
    EntityKind,
    EntityMentionSpan,
    FactSource,
    FactStatus,
    SchemaFact,
    SchemaLayer,
    SchemaType,
    SchemaVersion,
    TagAssignment,
    TagDef,
    TagKind,
    TimeAnchor,
    TimelineEvent,
    ExtractionMapping,
)

from .schema_rows import (
    _now_ts,
    _row_to_alias,
    _row_to_entity,
    _row_to_entity_mention,
    _row_to_extraction_mapping,
    _row_to_schema_fact,
    _row_to_schema_version,
    _row_to_tag_assignment,
    _row_to_tag_def,
    _row_to_time_anchor,
    _row_to_timeline_event,
)

def create_tag_def(
    conn,
    *,
    project_id: str,
    tag_path: str,
    kind: TagKind,
    schema_type: SchemaType,
    constraints: dict[str, Any] | None = None,
    commit: bool = True,
) -> TagDef:
    tag_id = str(uuid.uuid4())
    constraints = constraints or {}
    conn.execute(
        """
        INSERT INTO tag_def (tag_id, project_id, tag_path, kind, schema_type, constraints_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tag_id, project_id, tag_path, kind.value, schema_type.value, json.dumps(constraints)),
    )
    if commit:
        conn.commit()
    return TagDef(
        tag_id=tag_id,
        project_id=project_id,
        tag_path=tag_path,
        kind=kind,
        schema_type=schema_type,
        constraints=constraints,
    )

def list_tag_defs(conn, project_id: str) -> list[TagDef]:
    rows = conn.execute(
        "SELECT * FROM tag_def WHERE project_id = ? ORDER BY tag_path ASC",
        (project_id,),
    ).fetchall()
    return [_row_to_tag_def(row) for row in rows]

def delete_tag_def(conn, tag_id: str) -> bool:
    cur = conn.execute("DELETE FROM tag_def WHERE tag_id = ?", (tag_id,))
    conn.commit()
    return cur.rowcount > 0

def create_tag_assignment(
    conn,
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    span_start: int,
    span_end: int,
    tag_path: str,
    user_value: Any,
    created_by: FactSource,
) -> TagAssignment:
    assign_id = str(uuid.uuid4())
    ts = _now_ts()
    payload = json.dumps(user_value) if user_value is not None else None
    conn.execute(
        """
        INSERT INTO tag_assignment (
            assign_id, project_id, doc_id, snapshot_id, span_start, span_end,
            tag_path, user_value_json, created_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assign_id,
            project_id,
            doc_id,
            snapshot_id,
            span_start,
            span_end,
            tag_path,
            payload,
            created_by.value,
            ts,
        ),
    )
    conn.commit()
    return TagAssignment(
        assign_id=assign_id,
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        span_start=span_start,
        span_end=span_end,
        tag_path=tag_path,
        user_value=user_value,
        created_by=created_by,
        created_at=ts,
    )

def list_tag_assignments(
    conn,
    project_id: str,
    *,
    doc_id: str | None = None,
    snapshot_id: str | None = None,
) -> list[TagAssignment]:
    query = "SELECT * FROM tag_assignment WHERE project_id = ?"
    params: list[Any] = [project_id]
    if doc_id is not None:
        query += " AND doc_id = ?"
        params.append(doc_id)
    if snapshot_id is not None:
        query += " AND snapshot_id = ?"
        params.append(snapshot_id)
    query += " ORDER BY created_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_tag_assignment(row) for row in rows]

def delete_tag_assignment(conn, assign_id: str) -> bool:
    cur = conn.execute("DELETE FROM tag_assignment WHERE assign_id = ?", (assign_id,))
    conn.commit()
    return cur.rowcount > 0
