from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import whitelist_repo
from modules.nf_shared.protocol.dtos import WhitelistIntentType


class WhitelistServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def add_item(
        self,
        project_id: str,
        claim_text: str,
        scope: str,
        note: str | None = None,
        *,
        intent_type: str | None = None,
        reason: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict:
        fingerprint = self._fingerprint(claim_text)
        normalized_intent = self._normalize_intent_type(intent_type)
        with db.connect(self._db_path) as conn:
            item = whitelist_repo.create_whitelist_item(
                conn,
                project_id=project_id,
                claim_fingerprint=fingerprint,
                scope=scope,
                note=note,
            )
            annotation = whitelist_repo.set_whitelist_annotation(
                conn,
                project_id=project_id,
                claim_fingerprint=fingerprint,
                scope=scope,
                intent_type=normalized_intent.value,
                reason=reason,
                meta=meta,
            )
            whitelist_repo.recompute_verdict_whitelist_flags(conn, project_id, claim_fingerprint=fingerprint)
            return {
                **item,
                "annotation": annotation,
            }

    def delete_item(self, project_id: str, claim_text: str) -> bool:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            deleted = whitelist_repo.delete_whitelist_item(conn, project_id, fingerprint)
            whitelist_repo.delete_whitelist_annotations(conn, project_id, fingerprint)
            whitelist_repo.recompute_verdict_whitelist_flags(conn, project_id, claim_fingerprint=fingerprint)
            return deleted

    def is_whitelisted(self, project_id: str, claim_text: str) -> bool:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            return whitelist_repo.is_whitelisted(conn, project_id, fingerprint)

    def get_annotation(self, project_id: str, claim_text: str, *, scope: str | None = None) -> dict | None:
        fingerprint = self._fingerprint(claim_text)
        with db.connect(self._db_path) as conn:
            return whitelist_repo.get_whitelist_annotation(conn, project_id, fingerprint, scope=scope)

    @staticmethod
    def _normalize_intent_type(raw: str | None) -> WhitelistIntentType:
        if isinstance(raw, str):
            value = raw.strip().upper()
            if value:
                try:
                    return WhitelistIntentType(value)
                except ValueError:
                    pass
        return WhitelistIntentType.INTENDED_CONFLICT

    @staticmethod
    def _fingerprint(text: str) -> str:
        digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
