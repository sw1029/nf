from __future__ import annotations

from pathlib import Path

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import schema_repo
from modules.nf_shared.protocol.dtos import Entity, EntityAlias, EntityKind, FactSource


class EntityServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def list_entities(self, project_id: str) -> list[Entity]:
        with db.connect(self._db_path) as conn:
            return schema_repo.list_entities(conn, project_id)

    def create_entity(self, project_id: str, kind: EntityKind, canonical_name: str) -> Entity:
        with db.connect(self._db_path) as conn:
            return schema_repo.create_entity(conn, project_id=project_id, kind=kind, canonical_name=canonical_name)

    def delete_entity(self, entity_id: str) -> bool:
        with db.connect(self._db_path) as conn:
            return schema_repo.delete_entity(conn, entity_id)

    def list_aliases(self, project_id: str, entity_id: str) -> list[EntityAlias]:
        with db.connect(self._db_path) as conn:
            return schema_repo.list_entity_aliases(conn, project_id, entity_id)

    def create_alias(self, project_id: str, entity_id: str, alias_text: str, created_by: FactSource) -> EntityAlias:
        with db.connect(self._db_path) as conn:
            return schema_repo.create_entity_alias(
                conn,
                project_id=project_id,
                entity_id=entity_id,
                alias_text=alias_text,
                created_by=created_by,
            )

    def delete_alias(self, alias_id: str) -> bool:
        with db.connect(self._db_path) as conn:
            return schema_repo.delete_entity_alias(conn, alias_id)
