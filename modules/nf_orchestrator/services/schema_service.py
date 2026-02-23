from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import schema_repo
from modules.nf_shared.protocol.dtos import FactID, FactSource, FactStatus, SchemaFact, SchemaLayer, SchemaView


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SchemaServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def get_schema_view(self, project_id: str) -> SchemaView:
        with db.connect(self._db_path) as conn:
            latest = schema_repo.get_latest_schema_version(conn, project_id)
            if latest is None:
                return SchemaView(project_id=project_id, schema_ver="", facts=tuple(), created_at=_now_ts())
            facts = schema_repo.list_approved_facts(conn, project_id, latest.schema_ver)
            return SchemaView(
                project_id=project_id,
                schema_ver=latest.schema_ver,
                facts=tuple(facts),
                created_at=latest.created_at,
            )

    def list_facts(
        self,
        project_id: str,
        *,
        status: FactStatus | None = None,
        layer: str | None = None,
        source: str | None = None,
    ) -> list[SchemaFact]:
        with db.connect(self._db_path) as conn:
            layer_enum = SchemaLayer(layer) if layer else None
            source_enum = FactSource(source) if source else None
            return schema_repo.list_schema_facts(
                conn,
                project_id,
                status=status,
                layer=layer_enum,
                source=source_enum,
            )

    def set_fact_status(self, project_id: str, fact_id: FactID, status: FactStatus) -> SchemaFact:
        with db.connect(self._db_path) as conn:
            fact = schema_repo.get_schema_fact(conn, fact_id)
            if fact is None or fact.project_id != project_id:
                raise ValueError("fact not found")
            updated = schema_repo.update_fact_status(conn, fact_id, status)
            if updated is None:
                raise ValueError("fact not found")
            return updated

    def get_fact(self, fact_id: FactID) -> SchemaFact | None:
        with db.connect(self._db_path) as conn:
            return schema_repo.get_schema_fact(conn, fact_id)

    def create_schema_version(self, project_id: str, source_snapshot_id: str, notes: str | None = None) -> str:
        with db.connect(self._db_path) as conn:
            version = schema_repo.create_schema_version(
                conn,
                project_id=project_id,
                source_snapshot_id=source_snapshot_id,
                notes=notes,
            )
            return version.schema_ver

    def add_fact(self, fact: SchemaFact) -> SchemaFact:
        with db.connect(self._db_path) as conn:
            return schema_repo.create_schema_fact(conn, fact)
