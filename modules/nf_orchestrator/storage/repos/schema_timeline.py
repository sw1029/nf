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

def create_entity_mention_span(
    conn,
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    entity_id: str,
    span_start: int,
    span_end: int,
    status: FactStatus,
    created_by: FactSource,
    commit: bool = True,
) -> EntityMentionSpan:
    mention_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO entity_mention_span (
            mention_id, project_id, doc_id, snapshot_id, entity_id,
            span_start, span_end, status, created_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mention_id,
            project_id,
            doc_id,
            snapshot_id,
            entity_id,
            span_start,
            span_end,
            status.value,
            created_by.value,
            ts,
        ),
    )
    if commit:
        conn.commit()
    return EntityMentionSpan(
        mention_id=mention_id,
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        entity_id=entity_id,
        span_start=span_start,
        span_end=span_end,
        status=status,
        created_by=created_by,
        created_at=ts,
    )

def list_entity_mention_spans(
    conn,
    project_id: str,
    *,
    doc_id: str | None = None,
    entity_id: str | None = None,
    status: FactStatus | None = None,
) -> list[EntityMentionSpan]:
    query = "SELECT * FROM entity_mention_span WHERE project_id = ?"
    params: list[Any] = [project_id]
    if doc_id is not None:
        query += " AND doc_id = ?"
        params.append(doc_id)
    if entity_id is not None:
        query += " AND entity_id = ?"
        params.append(entity_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status.value)
    query += " ORDER BY span_start ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_entity_mention(row) for row in rows]

def delete_entity_mention_spans(
    conn,
    *,
    project_id: str,
    doc_id: str | None = None,
    snapshot_id: str | None = None,
    commit: bool = True,
) -> int:
    query = "DELETE FROM entity_mention_span WHERE project_id = ?"
    params: list[Any] = [project_id]
    if doc_id is not None:
        query += " AND doc_id = ?"
        params.append(doc_id)
    if snapshot_id is not None:
        query += " AND snapshot_id = ?"
        params.append(snapshot_id)
    cur = conn.execute(query, params)
    if commit:
        conn.commit()
    return cur.rowcount

def update_entity_mention_status(conn, mention_id: str, status: FactStatus) -> EntityMentionSpan | None:
    conn.execute(
        "UPDATE entity_mention_span SET status = ? WHERE mention_id = ?",
        (status.value, mention_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM entity_mention_span WHERE mention_id = ?",
        (mention_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_entity_mention(row)

def create_time_anchor(
    conn,
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    span_start: int,
    span_end: int,
    time_key: str,
    timeline_idx: int | None,
    status: FactStatus,
    created_by: FactSource,
    commit: bool = True,
) -> TimeAnchor:
    anchor_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO time_anchor (
            anchor_id, project_id, doc_id, snapshot_id,
            span_start, span_end, time_key, timeline_idx,
            status, created_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            anchor_id,
            project_id,
            doc_id,
            snapshot_id,
            span_start,
            span_end,
            time_key,
            timeline_idx,
            status.value,
            created_by.value,
            ts,
        ),
    )
    if commit:
        conn.commit()
    return TimeAnchor(
        anchor_id=anchor_id,
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        span_start=span_start,
        span_end=span_end,
        time_key=time_key,
        timeline_idx=timeline_idx,
        status=status,
        created_by=created_by,
        created_at=ts,
    )

def list_time_anchors(
    conn,
    project_id: str,
    *,
    doc_id: str | None = None,
    time_key: str | None = None,
    timeline_idx: int | None = None,
    status: FactStatus | None = None,
) -> list[TimeAnchor]:
    query = "SELECT * FROM time_anchor WHERE project_id = ?"
    params: list[Any] = [project_id]
    if doc_id is not None:
        query += " AND doc_id = ?"
        params.append(doc_id)
    if time_key is not None:
        query += " AND time_key = ?"
        params.append(time_key)
    if timeline_idx is not None:
        query += " AND timeline_idx = ?"
        params.append(timeline_idx)
    if status is not None:
        query += " AND status = ?"
        params.append(status.value)
    query += " ORDER BY span_start ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_time_anchor(row) for row in rows]

def delete_time_anchors(
    conn,
    *,
    project_id: str,
    doc_id: str | None = None,
    snapshot_id: str | None = None,
    commit: bool = True,
) -> int:
    query = "DELETE FROM time_anchor WHERE project_id = ?"
    params: list[Any] = [project_id]
    if doc_id is not None:
        query += " AND doc_id = ?"
        params.append(doc_id)
    if snapshot_id is not None:
        query += " AND snapshot_id = ?"
        params.append(snapshot_id)
    cur = conn.execute(query, params)
    if commit:
        conn.commit()
    return cur.rowcount

def update_time_anchor_status(conn, anchor_id: str, status: FactStatus) -> TimeAnchor | None:
    conn.execute(
        "UPDATE time_anchor SET status = ? WHERE anchor_id = ?",
        (status.value, anchor_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM time_anchor WHERE anchor_id = ?",
        (anchor_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_time_anchor(row)

def create_timeline_event(
    conn,
    *,
    project_id: str,
    timeline_idx: int,
    label: str,
    time_key: str,
    source_doc_id: str,
    source_snapshot_id: str,
    span_start: int,
    span_end: int,
    status: FactStatus,
    created_by: FactSource,
    commit: bool = True,
) -> TimelineEvent:
    timeline_event_id = str(uuid.uuid4())
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO timeline_event (
            timeline_event_id, project_id, timeline_idx, label, time_key,
            source_doc_id, source_snapshot_id, span_start, span_end,
            status, created_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timeline_event_id,
            project_id,
            timeline_idx,
            label,
            time_key,
            source_doc_id,
            source_snapshot_id,
            span_start,
            span_end,
            status.value,
            created_by.value,
            ts,
        ),
    )
    if commit:
        conn.commit()
    return TimelineEvent(
        timeline_event_id=timeline_event_id,
        project_id=project_id,
        timeline_idx=timeline_idx,
        label=label,
        time_key=time_key,
        source_doc_id=source_doc_id,
        source_snapshot_id=source_snapshot_id,
        span_start=span_start,
        span_end=span_end,
        status=status,
        created_by=created_by,
        created_at=ts,
    )

def list_timeline_events(
    conn,
    project_id: str,
    *,
    source_doc_id: str | None = None,
    status: FactStatus | None = None,
) -> list[TimelineEvent]:
    query = "SELECT * FROM timeline_event WHERE project_id = ?"
    params: list[Any] = [project_id]
    if source_doc_id is not None:
        query += " AND source_doc_id = ?"
        params.append(source_doc_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status.value)
    query += " ORDER BY timeline_idx ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_timeline_event(row) for row in rows]

def delete_timeline_events(
    conn,
    *,
    project_id: str,
    source_doc_id: str | None = None,
    commit: bool = True,
) -> int:
    query = "DELETE FROM timeline_event WHERE project_id = ?"
    params: list[Any] = [project_id]
    if source_doc_id is not None:
        query += " AND source_doc_id = ?"
        params.append(source_doc_id)
    cur = conn.execute(query, params)
    if commit:
        conn.commit()
    return cur.rowcount

def update_timeline_event_status(conn, event_id: str, status: FactStatus) -> TimelineEvent | None:
    conn.execute(
        "UPDATE timeline_event SET status = ? WHERE timeline_event_id = ?",
        (status.value, event_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM timeline_event WHERE timeline_event_id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_timeline_event(row)
