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

def create_extraction_mapping(
    conn,
    *,
    project_id: str,
    slot_key: str,
    pattern: str,
    flags: str = "",
    transform: str = "identity",
    priority: int = 100,
    enabled: bool = True,
    created_by: str = "USER",
    commit: bool = True,
) -> ExtractionMapping:
    mapping_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO extraction_mappings (
            mapping_id, project_id, slot_key, pattern, flags, transform,
            priority, enabled, created_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mapping_id,
            project_id,
            slot_key,
            pattern,
            flags,
            transform,
            int(priority),
            1 if enabled else 0,
            created_by,
            ts,
        ),
    )
    if commit:
        conn.commit()
    return ExtractionMapping(
        mapping_id=mapping_id,
        project_id=project_id,
        slot_key=slot_key,
        pattern=pattern,
        flags=flags,
        transform=transform,
        priority=int(priority),
        enabled=enabled,
        created_by=created_by,
        created_at=ts,
    )

def list_extraction_mappings(conn, project_id: str, *, enabled_only: bool = False) -> list[ExtractionMapping]:
    query = "SELECT * FROM extraction_mappings WHERE project_id = ?"
    params: list[Any] = [project_id]
    if enabled_only:
        query += " AND enabled = 1"
    query += " ORDER BY priority DESC, created_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_extraction_mapping(row) for row in rows]

def get_extraction_mapping(conn, mapping_id: str) -> ExtractionMapping | None:
    row = conn.execute("SELECT * FROM extraction_mappings WHERE mapping_id = ?", (mapping_id,)).fetchone()
    if row is None:
        return None
    return _row_to_extraction_mapping(row)

def update_extraction_mapping(
    conn,
    mapping_id: str,
    *,
    pattern: str | None = None,
    flags: str | None = None,
    transform: str | None = None,
    priority: int | None = None,
    enabled: bool | None = None,
    slot_key: str | None = None,
) -> ExtractionMapping | None:
    current = get_extraction_mapping(conn, mapping_id)
    if current is None:
        return None
    next_slot_key = slot_key if isinstance(slot_key, str) else current.slot_key
    next_pattern = pattern if isinstance(pattern, str) else current.pattern
    next_flags = flags if isinstance(flags, str) else current.flags
    next_transform = transform if isinstance(transform, str) else current.transform
    next_priority = int(priority) if isinstance(priority, int) else current.priority
    next_enabled = enabled if isinstance(enabled, bool) else current.enabled
    conn.execute(
        """
        UPDATE extraction_mappings
        SET slot_key = ?, pattern = ?, flags = ?, transform = ?, priority = ?, enabled = ?
        WHERE mapping_id = ?
        """,
        (
            next_slot_key,
            next_pattern,
            next_flags,
            next_transform,
            next_priority,
            1 if next_enabled else 0,
            mapping_id,
        ),
    )
    conn.commit()
    return get_extraction_mapping(conn, mapping_id)

def delete_extraction_mapping(conn, mapping_id: str) -> bool:
    cur = conn.execute("DELETE FROM extraction_mappings WHERE mapping_id = ?", (mapping_id,))
    conn.commit()
    return cur.rowcount > 0

def extraction_mapping_checksum(conn, project_id: str) -> str:
    rows = conn.execute(
        """
        SELECT mapping_id, slot_key, pattern, flags, transform, priority, enabled
        FROM extraction_mappings
        WHERE project_id = ?
        ORDER BY priority DESC, mapping_id ASC
        """,
        (project_id,),
    ).fetchall()
    payload = [
        {
            "mapping_id": row["mapping_id"],
            "slot_key": row["slot_key"],
            "pattern": row["pattern"],
            "flags": row["flags"] or "",
            "transform": row["transform"] or "identity",
            "priority": int(row["priority"]),
            "enabled": bool(int(row["enabled"])),
        }
        for row in rows
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
