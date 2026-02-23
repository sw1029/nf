from __future__ import annotations

from pathlib import Path

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import document_repo
from modules.nf_shared.protocol.dtos import Episode


class EpisodeServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def list_episodes(self, project_id: str) -> list[Episode]:
        with db.connect(self._db_path) as conn:
            return document_repo.list_episodes(conn, project_id)

    def create_episode(self, project_id: str, start_n: int, end_m: int, label: str) -> Episode:
        with db.connect(self._db_path) as conn:
            return document_repo.create_episode(
                conn,
                project_id=project_id,
                start_n=start_n,
                end_m=end_m,
                label=label,
            )
