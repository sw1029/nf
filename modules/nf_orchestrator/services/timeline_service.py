from __future__ import annotations

from pathlib import Path

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import schema_repo
from modules.nf_shared.protocol.dtos import EntityMentionSpan, FactStatus, TimeAnchor, TimelineEvent


class TimelineServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def list_entity_mentions(
        self,
        project_id: str,
        *,
        doc_id: str | None = None,
        entity_id: str | None = None,
        status: FactStatus | None = None,
    ) -> list[EntityMentionSpan]:
        with db.connect(self._db_path) as conn:
            return schema_repo.list_entity_mention_spans(
                conn,
                project_id,
                doc_id=doc_id,
                entity_id=entity_id,
                status=status,
            )

    def set_entity_mention_status(self, mention_id: str, status: FactStatus) -> EntityMentionSpan | None:
        with db.connect(self._db_path) as conn:
            return schema_repo.update_entity_mention_status(conn, mention_id, status)

    def list_time_anchors(
        self,
        project_id: str,
        *,
        doc_id: str | None = None,
        time_key: str | None = None,
        timeline_idx: int | None = None,
        status: FactStatus | None = None,
    ) -> list[TimeAnchor]:
        with db.connect(self._db_path) as conn:
            return schema_repo.list_time_anchors(
                conn,
                project_id,
                doc_id=doc_id,
                time_key=time_key,
                timeline_idx=timeline_idx,
                status=status,
            )

    def set_time_anchor_status(self, anchor_id: str, status: FactStatus) -> TimeAnchor | None:
        with db.connect(self._db_path) as conn:
            return schema_repo.update_time_anchor_status(conn, anchor_id, status)

    def list_timeline_events(
        self,
        project_id: str,
        *,
        source_doc_id: str | None = None,
        status: FactStatus | None = None,
    ) -> list[TimelineEvent]:
        with db.connect(self._db_path) as conn:
            return schema_repo.list_timeline_events(
                conn,
                project_id,
                source_doc_id=source_doc_id,
                status=status,
            )

    def set_timeline_event_status(self, event_id: str, status: FactStatus) -> TimelineEvent | None:
        with db.connect(self._db_path) as conn:
            return schema_repo.update_timeline_event_status(conn, event_id, status)
