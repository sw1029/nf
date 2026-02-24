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

def _row_to_extraction_mapping(row: Any) -> ExtractionMapping:
    return ExtractionMapping(
        mapping_id=row["mapping_id"],
        project_id=row["project_id"],
        slot_key=row["slot_key"],
        pattern=row["pattern"],
        flags=row["flags"] or "",
        transform=row["transform"] or "identity",
        priority=int(row["priority"]),
        enabled=bool(int(row["enabled"])),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )
