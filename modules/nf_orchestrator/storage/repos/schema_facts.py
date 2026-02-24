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

def create_schema_version(
    conn,
    *,
    project_id: str,
    source_snapshot_id: str,
    notes: str | None = None,
    schema_ver: str | None = None,
    commit: bool = True,
) -> SchemaVersion:
    schema_ver = schema_ver or str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO schema_version (schema_ver, project_id, created_at, source_snapshot_id, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (schema_ver, project_id, ts, source_snapshot_id, notes),
    )
    if commit:
        conn.commit()
    return SchemaVersion(
        schema_ver=schema_ver,
        project_id=project_id,
        created_at=ts,
        source_snapshot_id=source_snapshot_id,
        notes=notes,
    )

def list_schema_versions(conn, project_id: str) -> list[SchemaVersion]:
    rows = conn.execute(
        "SELECT * FROM schema_version WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()
    return [_row_to_schema_version(row) for row in rows]

def get_latest_schema_version(conn, project_id: str) -> SchemaVersion | None:
    row = conn.execute(
        "SELECT * FROM schema_version WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_schema_version(row)

def create_schema_fact(conn, fact: SchemaFact, *, commit: bool = True) -> SchemaFact:
    conn.execute(
        """
        INSERT INTO schema_facts (
            fact_id, project_id, schema_ver, layer, entity_id, tag_path,
            value_json, evidence_eid, confidence, source, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fact.fact_id,
            fact.project_id,
            fact.schema_ver,
            fact.layer.value,
            fact.entity_id,
            fact.tag_path,
            json.dumps(fact.value),
            fact.evidence_eid,
            fact.confidence,
            fact.source.value,
            fact.status.value,
        ),
    )
    if commit:
        conn.commit()
    return fact

def list_schema_facts(
    conn,
    project_id: str,
    *,
    schema_ver: str | None = None,
    status: FactStatus | None = None,
    layer: SchemaLayer | None = None,
    source: FactSource | None = None,
) -> list[SchemaFact]:
    query = "SELECT * FROM schema_facts WHERE project_id = ?"
    params: list[Any] = [project_id]
    if schema_ver is not None:
        query += " AND schema_ver = ?"
        params.append(schema_ver)
    if status is not None:
        query += " AND status = ?"
        params.append(status.value)
    if layer is not None:
        query += " AND layer = ?"
        params.append(layer.value)
    if source is not None:
        query += " AND source = ?"
        params.append(source.value)
    rows = conn.execute(query, params).fetchall()
    return [_row_to_schema_fact(row) for row in rows]

def list_schema_facts_by_evidence_ids(
    conn,
    project_id: str,
    evidence_ids: list[str],
    *,
    status: FactStatus | None = None,
) -> list[SchemaFact]:
    cleaned_ids = sorted({eid.strip() for eid in evidence_ids if isinstance(eid, str) and eid.strip()})
    if not cleaned_ids:
        return []
    rows: list[Any] = []
    chunk_size = 200
    for start in range(0, len(cleaned_ids), chunk_size):
        chunk = cleaned_ids[start : start + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        query = f"SELECT * FROM schema_facts WHERE project_id = ? AND evidence_eid IN ({placeholders})"
        params: list[Any] = [project_id, *chunk]
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        rows.extend(conn.execute(query, params).fetchall())
    return [_row_to_schema_fact(row) for row in rows]

def get_schema_fact(conn, fact_id: str) -> SchemaFact | None:
    row = conn.execute("SELECT * FROM schema_facts WHERE fact_id = ?", (fact_id,)).fetchone()
    if row is None:
        return None
    return _row_to_schema_fact(row)

def update_fact_status(conn, fact_id: str, status: FactStatus) -> SchemaFact | None:
    conn.execute(
        "UPDATE schema_facts SET status = ? WHERE fact_id = ?",
        (status.value, fact_id),
    )
    conn.commit()
    return get_schema_fact(conn, fact_id)

def list_approved_facts(conn, project_id: str, schema_ver: str) -> list[SchemaFact]:
    return list_schema_facts(conn, project_id, schema_ver=schema_ver, status=FactStatus.APPROVED)
