from __future__ import annotations

from pathlib import Path

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import schema_repo
from modules.nf_shared.protocol.dtos import ExtractionMapping


class ExtractionServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def list_mappings(self, project_id: str, *, enabled_only: bool = False) -> list[ExtractionMapping]:
        with db.connect(self._db_path) as conn:
            return schema_repo.list_extraction_mappings(conn, project_id, enabled_only=enabled_only)

    def create_mapping(
        self,
        project_id: str,
        *,
        slot_key: str,
        pattern: str,
        flags: str,
        transform: str,
        priority: int,
        enabled: bool,
        created_by: str,
    ) -> ExtractionMapping:
        with db.connect(self._db_path) as conn:
            return schema_repo.create_extraction_mapping(
                conn,
                project_id=project_id,
                slot_key=slot_key,
                pattern=pattern,
                flags=flags,
                transform=transform,
                priority=priority,
                enabled=enabled,
                created_by=created_by,
            )

    def update_mapping(
        self,
        mapping_id: str,
        *,
        slot_key: str | None = None,
        pattern: str | None = None,
        flags: str | None = None,
        transform: str | None = None,
        priority: int | None = None,
        enabled: bool | None = None,
    ) -> ExtractionMapping | None:
        with db.connect(self._db_path) as conn:
            return schema_repo.update_extraction_mapping(
                conn,
                mapping_id,
                slot_key=slot_key,
                pattern=pattern,
                flags=flags,
                transform=transform,
                priority=priority,
                enabled=enabled,
            )

    def get_mapping(self, mapping_id: str) -> ExtractionMapping | None:
        with db.connect(self._db_path) as conn:
            return schema_repo.get_extraction_mapping(conn, mapping_id)

    def delete_mapping(self, mapping_id: str) -> bool:
        with db.connect(self._db_path) as conn:
            return schema_repo.delete_extraction_mapping(conn, mapping_id)

    def mapping_checksum(self, project_id: str) -> str:
        with db.connect(self._db_path) as conn:
            return schema_repo.extraction_mapping_checksum(conn, project_id)
