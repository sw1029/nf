from __future__ import annotations

import hashlib
from pathlib import Path

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import ignore_repo


class IgnoreServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def add_item(
        self,
        project_id: str,
        claim_text: str,
        scope: str,
        kind: str,
        note: str | None = None,
    ) -> dict:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            item = ignore_repo.create_ignore_item(
                conn,
                project_id=project_id,
                claim_fingerprint=fingerprint,
                scope=scope,
                kind=kind,
                note=note,
            )
            return item

    def delete_item(
        self,
        project_id: str,
        claim_text: str,
        *,
        scope: str | None = None,
        kind: str | None = None,
    ) -> bool:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            return ignore_repo.delete_ignore_item(conn, project_id, fingerprint, scope=scope, kind=kind)

    def is_ignored(
        self,
        project_id: str,
        claim_text: str,
        *,
        scope: str | None = None,
        kind: str | None = None,
    ) -> bool:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            return ignore_repo.is_ignored(conn, project_id, fingerprint, scope=scope, kind=kind)

    @staticmethod
    def _fingerprint(text: str) -> str:
        digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

