from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import schema_repo
from modules.nf_schema.registry import default_tag_defs
from modules.nf_schema.validators import validate_constraints, validate_tag_path
from modules.nf_shared.protocol.dtos import FactSource, TagAssignment, TagDef, TagKind, SchemaType


class TagServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def list_tag_defs(self, project_id: str) -> list[TagDef]:
        with db.connect(self._db_path) as conn:
            tags = schema_repo.list_tag_defs(conn, project_id)
            if tags:
                return tags
            for item in default_tag_defs():
                schema_repo.create_tag_def(
                    conn,
                    project_id=project_id,
                    tag_path=item["tag_path"],
                    kind=item["kind"],
                    schema_type=item["schema_type"],
                    constraints=item.get("constraints") or {},
                )
            return schema_repo.list_tag_defs(conn, project_id)

    def create_tag_def(
        self,
        project_id: str,
        tag_path: str,
        kind: TagKind,
        schema_type: SchemaType,
        constraints: dict[str, Any] | None = None,
    ) -> TagDef:
        with db.connect(self._db_path) as conn:
            validate_tag_path(tag_path)
            validate_constraints(schema_type, constraints or {})
            return schema_repo.create_tag_def(
                conn,
                project_id=project_id,
                tag_path=tag_path,
                kind=kind,
                schema_type=schema_type,
                constraints=constraints,
            )

    def delete_tag_def(self, tag_id: str) -> bool:
        with db.connect(self._db_path) as conn:
            return schema_repo.delete_tag_def(conn, tag_id)

    def list_tag_assignments(
        self,
        project_id: str,
        *,
        doc_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> list[TagAssignment]:
        with db.connect(self._db_path) as conn:
            return schema_repo.list_tag_assignments(
                conn,
                project_id,
                doc_id=doc_id,
                snapshot_id=snapshot_id,
            )

    def create_tag_assignment(
        self,
        project_id: str,
        doc_id: str,
        snapshot_id: str,
        span_start: int,
        span_end: int,
        tag_path: str,
        user_value: Any,
        created_by: FactSource,
    ) -> TagAssignment:
        with db.connect(self._db_path) as conn:
            validate_tag_path(tag_path)
            return schema_repo.create_tag_assignment(
                conn,
                project_id=project_id,
                doc_id=doc_id,
                snapshot_id=snapshot_id,
                span_start=span_start,
                span_end=span_end,
                tag_path=tag_path,
                user_value=user_value,
                created_by=created_by,
            )

    def delete_tag_assignment(self, assign_id: str) -> bool:
        with db.connect(self._db_path) as conn:
            return schema_repo.delete_tag_assignment(conn, assign_id)
