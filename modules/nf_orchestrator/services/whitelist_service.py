from __future__ import annotations

import hashlib
from pathlib import Path

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import whitelist_repo


class WhitelistServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def add_item(self, project_id: str, claim_text: str, scope: str, note: str | None = None) -> dict:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            return whitelist_repo.create_whitelist_item(
                conn,
                project_id=project_id,
                claim_fingerprint=fingerprint,
                scope=scope,
                note=note,
            )

    def delete_item(self, project_id: str, claim_text: str) -> bool:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            return whitelist_repo.delete_whitelist_item(conn, project_id, fingerprint)

    def is_whitelisted(self, project_id: str, claim_text: str) -> bool:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            return whitelist_repo.is_whitelisted(conn, project_id, fingerprint)

    @staticmethod
    def _fingerprint(text: str) -> str:
        digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
