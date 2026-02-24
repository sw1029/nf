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

def create_entity(conn, *, project_id: str, kind: EntityKind, canonical_name: str) -> Entity:
    entity_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO entity (entity_id, project_id, kind, canonical_name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (entity_id, project_id, kind.value, canonical_name, ts),
    )
    conn.commit()
    return Entity(
        entity_id=entity_id,
        project_id=project_id,
        kind=kind,
        canonical_name=canonical_name,
        created_at=ts,
    )

def list_entities(conn, project_id: str) -> list[Entity]:
    rows = conn.execute(
        "SELECT * FROM entity WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()
    return [_row_to_entity(row) for row in rows]

def delete_entity(conn, entity_id: str) -> bool:
    cur = conn.execute("DELETE FROM entity WHERE entity_id = ?", (entity_id,))
    conn.commit()
    return cur.rowcount > 0

def create_entity_alias(
    conn,
    *,
    project_id: str,
    entity_id: str,
    alias_text: str,
    created_by: FactSource,
) -> EntityAlias:
    alias_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO entity_alias (alias_id, project_id, entity_id, alias_text, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (alias_id, project_id, entity_id, alias_text, created_by.value, ts),
    )
    conn.commit()
    return EntityAlias(
        alias_id=alias_id,
        project_id=project_id,
        entity_id=entity_id,
        alias_text=alias_text,
        created_by=created_by,
        created_at=ts,
    )

def list_entity_aliases(conn, project_id: str, entity_id: str) -> list[EntityAlias]:
    rows = conn.execute(
        """
        SELECT * FROM entity_alias
        WHERE project_id = ? AND entity_id = ?
        ORDER BY created_at ASC
        """,
        (project_id, entity_id),
    ).fetchall()
    return [_row_to_alias(row) for row in rows]

def delete_entity_alias(conn, alias_id: str) -> bool:
    cur = conn.execute("DELETE FROM entity_alias WHERE alias_id = ?", (alias_id,))
    conn.commit()
    return cur.rowcount > 0
