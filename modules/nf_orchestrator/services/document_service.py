from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage import docstore
from modules.nf_orchestrator.storage.repos import document_repo
from modules.nf_shared.protocol.dtos import DocSnapshot, Document, DocumentType


class DocumentServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def list_documents(self, project_id: str) -> list[Document]:
        with db.connect(self._db_path) as conn:
            return document_repo.list_documents(conn, project_id)

    def get_document(self, doc_id: str) -> Document | None:
        with db.connect(self._db_path) as conn:
            return document_repo.get_document(conn, doc_id)

    def get_snapshot(self, snapshot_id: str) -> DocSnapshot | None:
        with db.connect(self._db_path) as conn:
            return document_repo.get_snapshot(conn, snapshot_id)

    def create_document(
        self,
        project_id: str,
        title: str,
        doc_type: DocumentType,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        doc_id = str(uuid.uuid4())
        snapshot_id = str(uuid.uuid4())
        checksum = docstore.checksum_text(content)
        version = 1
        raw_path = docstore.write_raw_text(project_id, doc_id, version=version, text=content)
        snapshot_path = docstore.write_snapshot_text(
            project_id,
            doc_id,
            snapshot_id=snapshot_id,
            version=version,
            text=content,
        )
        with db.connect(self._db_path) as conn:
            document_repo.create_snapshot(
                conn,
                snapshot_id=snapshot_id,
                project_id=project_id,
                doc_id=doc_id,
                version=version,
                path=str(snapshot_path),
                checksum=checksum,
            )
            return document_repo.create_document(
                conn,
                doc_id=doc_id,
                project_id=project_id,
                title=title,
                doc_type=doc_type,
                path=str(raw_path),
                head_snapshot_id=snapshot_id,
                checksum=checksum,
                version=version,
                metadata=metadata,
            )

    def update_document(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        doc_type: DocumentType | None = None,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Document | None:
        with db.connect(self._db_path) as conn:
            existing = document_repo.get_document(conn, doc_id)
            if existing is None:
                return None
            next_snapshot_id = None
            next_path = None
            next_checksum = None
            next_version = None
            if content is not None:
                next_version = existing.version + 1
                next_checksum = docstore.checksum_text(content)
                raw_path = docstore.write_raw_text(
                    existing.project_id,
                    doc_id,
                    version=next_version,
                    text=content,
                )
                snapshot_id = str(uuid.uuid4())
                snapshot_path = docstore.write_snapshot_text(
                    existing.project_id,
                    doc_id,
                    snapshot_id=snapshot_id,
                    version=next_version,
                    text=content,
                )
                document_repo.create_snapshot(
                    conn,
                    snapshot_id=snapshot_id,
                    project_id=existing.project_id,
                    doc_id=doc_id,
                    version=next_version,
                    path=str(snapshot_path),
                    checksum=next_checksum,
                )
                next_snapshot_id = snapshot_id
                next_path = str(raw_path)
            return document_repo.update_document(
                conn,
                doc_id=doc_id,
                title=title,
                doc_type=doc_type,
                path=next_path,
                head_snapshot_id=next_snapshot_id,
                checksum=next_checksum,
                version=next_version,
                metadata=metadata,
            )

    def delete_document(self, doc_id: str) -> bool:
        with db.connect(self._db_path) as conn:
            return document_repo.delete_document(conn, doc_id)
