from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import project_repo
from modules.nf_shared.protocol.dtos import Project


class ProjectServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def list_projects(self) -> list[Project]:
        return db.run_with_retry(self._db_path, lambda conn: project_repo.list_projects(conn))

    def create_project(self, name: str, settings: dict[str, Any]) -> Project:
        return db.run_with_retry(self._db_path, lambda conn: project_repo.create_project(conn, name, settings))

    def get_project(self, project_id: str) -> Project | None:
        return db.run_with_retry(self._db_path, lambda conn: project_repo.get_project(conn, project_id))

    def update_project(
        self, project_id: str, name: str | None, settings: dict[str, Any] | None
    ) -> Project | None:
        return db.run_with_retry(
            self._db_path,
            lambda conn: project_repo.update_project(conn, project_id, name, settings),
        )

    def delete_project(self, project_id: str) -> bool:
        return db.run_with_retry(self._db_path, lambda conn: project_repo.delete_project(conn, project_id))
