from __future__ import annotations

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
)


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_tag_def(row: Any) -> TagDef:
    return TagDef(
        tag_id=row["tag_id"],
        project_id=row["project_id"],
        tag_path=row["tag_path"],
        kind=TagKind(row["kind"]),
        schema_type=SchemaType(row["schema_type"]),
        constraints=json.loads(row["constraints_json"]),
    )


def _row_to_tag_assignment(row: Any) -> TagAssignment:
    return TagAssignment(
        assign_id=row["assign_id"],
        project_id=row["project_id"],
        doc_id=row["doc_id"],
        snapshot_id=row["snapshot_id"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        tag_path=row["tag_path"],
        user_value=json.loads(row["user_value_json"]) if row["user_value_json"] else None,
        created_by=FactSource(row["created_by"]),
        created_at=row["created_at"],
    )


def _row_to_entity(row: Any) -> Entity:
    return Entity(
        entity_id=row["entity_id"],
        project_id=row["project_id"],
        kind=EntityKind(row["kind"]),
        canonical_name=row["canonical_name"],
        created_at=row["created_at"],
    )


def _row_to_alias(row: Any) -> EntityAlias:
    return EntityAlias(
        alias_id=row["alias_id"],
        project_id=row["project_id"],
        entity_id=row["entity_id"],
        alias_text=row["alias_text"],
        created_by=FactSource(row["created_by"]),
        created_at=row["created_at"],
    )


def _row_to_schema_version(row: Any) -> SchemaVersion:
    return SchemaVersion(
        schema_ver=row["schema_ver"],
        project_id=row["project_id"],
        created_at=row["created_at"],
        source_snapshot_id=row["source_snapshot_id"],
        notes=row["notes"],
    )


def _row_to_schema_fact(row: Any) -> SchemaFact:
    return SchemaFact(
        fact_id=row["fact_id"],
        project_id=row["project_id"],
        schema_ver=row["schema_ver"],
        layer=SchemaLayer(row["layer"]),
        entity_id=row["entity_id"],
        tag_path=row["tag_path"],
        value=json.loads(row["value_json"]),
        evidence_eid=row["evidence_eid"],
        confidence=row["confidence"],
        source=FactSource(row["source"]),
        status=FactStatus(row["status"]),
    )


def _row_to_entity_mention(row: Any) -> EntityMentionSpan:
    return EntityMentionSpan(
        mention_id=row["mention_id"],
        project_id=row["project_id"],
        doc_id=row["doc_id"],
        snapshot_id=row["snapshot_id"],
        entity_id=row["entity_id"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        status=FactStatus(row["status"]),
        created_by=FactSource(row["created_by"]),
        created_at=row["created_at"],
    )


def _row_to_time_anchor(row: Any) -> TimeAnchor:
    return TimeAnchor(
        anchor_id=row["anchor_id"],
        project_id=row["project_id"],
        doc_id=row["doc_id"],
        snapshot_id=row["snapshot_id"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        time_key=row["time_key"],
        timeline_idx=row["timeline_idx"],
        status=FactStatus(row["status"]),
        created_by=FactSource(row["created_by"]),
        created_at=row["created_at"],
    )


def _row_to_timeline_event(row: Any) -> TimelineEvent:
    return TimelineEvent(
        timeline_event_id=row["timeline_event_id"],
        project_id=row["project_id"],
        timeline_idx=row["timeline_idx"],
        label=row["label"],
        time_key=row["time_key"],
        source_doc_id=row["source_doc_id"],
        source_snapshot_id=row["source_snapshot_id"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        status=FactStatus(row["status"]),
        created_by=FactSource(row["created_by"]),
        created_at=row["created_at"],
    )


def create_tag_def(
    conn,
    *,
    project_id: str,
    tag_path: str,
    kind: TagKind,
    schema_type: SchemaType,
    constraints: dict[str, Any] | None = None,
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


def create_schema_version(
    conn,
    *,
    project_id: str,
    source_snapshot_id: str,
    notes: str | None = None,
    schema_ver: str | None = None,
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


def create_schema_fact(conn, fact: SchemaFact) -> SchemaFact:
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
) -> int:
    query = "DELETE FROM timeline_event WHERE project_id = ?"
    params: list[Any] = [project_id]
    if source_doc_id is not None:
        query += " AND source_doc_id = ?"
        params.append(source_doc_id)
    cur = conn.execute(query, params)
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
