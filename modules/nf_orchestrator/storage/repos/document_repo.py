from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone
from typing import Any

from modules.nf_shared.protocol.dtos import DocSnapshot, Document, DocumentType, Episode


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_document(row: Any) -> Document:
    meta_json = row["metadata_json"]
    meta = json.loads(meta_json) if meta_json else {}
    return Document(
        doc_id=row["doc_id"],
        project_id=row["project_id"],
        title=row["title"],
        type=DocumentType(row["type"]),
        path=row["path"],
        head_snapshot_id=row["head_snapshot_id"],
        checksum=row["checksum"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=meta,
    )


def _row_to_snapshot(row: Any) -> DocSnapshot:
    return DocSnapshot(
        snapshot_id=row["snapshot_id"],
        project_id=row["project_id"],
        doc_id=row["doc_id"],
        version=row["version"],
        path=row["path"],
        checksum=row["checksum"],
        created_at=row["created_at"],
    )


def _row_to_episode(row: Any) -> Episode:
    return Episode(
        episode_id=row["episode_id"],
        project_id=row["project_id"],
        start_n=row["start_n"],
        end_m=row["end_m"],
        label=row["label"],
        created_at=row["created_at"],
    )


def create_document(
    conn,
    *,
    doc_id: str,
    project_id: str,
    title: str,
    doc_type: DocumentType,
    path: str,
    head_snapshot_id: str,
    checksum: str,
    version: int,
    metadata: dict[str, Any] | None = None,
) -> Document:
    ts = _now_ts()
    meta_json = json.dumps(metadata) if metadata else "{}"
    conn.execute(
        """
        INSERT INTO documents (
            doc_id, project_id, title, type, path, head_snapshot_id,
            checksum, version, created_at, updated_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            project_id,
            title,
            doc_type.value,
            path,
            head_snapshot_id,
            checksum,
            version,
            ts,
            ts,
            meta_json,
        ),
    )
    conn.commit()
    return Document(
        doc_id=doc_id,
        project_id=project_id,
        title=title,
        type=doc_type,
        path=path,
        head_snapshot_id=head_snapshot_id,
        checksum=checksum,
        version=version,
        created_at=ts,
        updated_at=ts,
        metadata=metadata or {},
    )


def list_documents(conn, project_id: str) -> list[Document]:
    # TODO: Might need custom sorting here or in service layer based on metadata
    rows = conn.execute(
        "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()
    return [_row_to_document(row) for row in rows]


def get_document(conn, doc_id: str) -> Document | None:
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if row is None:
        return None
    return _row_to_document(row)


def update_document(
    conn,
    *,
    doc_id: str,
    title: str | None = None,
    doc_type: DocumentType | None = None,
    path: str | None = None,
    head_snapshot_id: str | None = None,
    checksum: str | None = None,
    version: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Document | None:
    existing = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if existing is None:
        return None
    ts = _now_ts()
    next_title = title if title is not None else existing["title"]
    next_type = doc_type.value if doc_type is not None else existing["type"]
    next_path = path if path is not None else existing["path"]
    next_snapshot = head_snapshot_id if head_snapshot_id is not None else existing["head_snapshot_id"]
    next_checksum = checksum if checksum is not None else existing["checksum"]
    next_version = version if version is not None else existing["version"]
    
    next_meta_json = existing["metadata_json"]
    if metadata is not None:
        # Merge or replace? For now, we assume FULL replacement of metadata or merge logic in service
        # But usually update_document might receive partial updates. Let's start with replacement for simplicity 
        # or merge if we want to be safe. Since `metadata` arg is passed, we likely want to set it.
        # But if the user passed specific keys, they should have constructed the dict in service.
        # So we just dump what we got.
        next_meta_json = json.dumps(metadata)

    conn.execute(
        """
        UPDATE documents
        SET title = ?, type = ?, path = ?, head_snapshot_id = ?, checksum = ?, version = ?, updated_at = ?, metadata_json = ?
        WHERE doc_id = ?
        """,
        (
            next_title,
            next_type,
            next_path,
            next_snapshot,
            next_checksum,
            next_version,
            ts,
            next_meta_json,
            doc_id,
        ),
    )
    conn.commit()
    
    next_meta = json.loads(next_meta_json) if next_meta_json else {}

    return Document(
        doc_id=existing["doc_id"],
        project_id=existing["project_id"],
        title=next_title,
        type=DocumentType(next_type),
        path=next_path,
        head_snapshot_id=next_snapshot,
        checksum=next_checksum,
        version=next_version,
        created_at=existing["created_at"],
        updated_at=ts,
        metadata=next_meta,
    )


def delete_document(conn, doc_id: str) -> bool:
    cur = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.commit()
    return cur.rowcount > 0


def create_snapshot(
    conn,
    *,
    snapshot_id: str,
    project_id: str,
    doc_id: str,
    version: int,
    path: str,
    checksum: str,
) -> DocSnapshot:
    ts = _now_ts()
    conn.execute(
        """
        INSERT INTO doc_snapshots (
            snapshot_id, project_id, doc_id, version, path, checksum, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, project_id, doc_id, version, path, checksum, ts),
    )
    conn.commit()
    return DocSnapshot(
        snapshot_id=snapshot_id,
        project_id=project_id,
        doc_id=doc_id,
        version=version,
        path=path,
        checksum=checksum,
        created_at=ts,
    )


def get_snapshot(conn, snapshot_id: str) -> DocSnapshot | None:
    row = conn.execute("SELECT * FROM doc_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
    if row is None:
        return None
    return _row_to_snapshot(row)


def list_snapshots(conn, doc_id: str) -> list[DocSnapshot]:
    rows = conn.execute(
        "SELECT * FROM doc_snapshots WHERE doc_id = ? ORDER BY version ASC",
        (doc_id,),
    ).fetchall()
    return [_row_to_snapshot(row) for row in rows]


def get_head_snapshot(conn, doc_id: str) -> DocSnapshot | None:
    row = conn.execute(
        "SELECT * FROM doc_snapshots WHERE doc_id = ? ORDER BY version DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_snapshot(row)


def create_episode(
    conn,
    *,
    project_id: str,
    start_n: int,
    end_m: int,
    label: str,
    episode_id: str | None = None,
) -> Episode:
    ts = _now_ts()
    episode_id = episode_id or str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO episodes (episode_id, project_id, start_n, end_m, label, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (episode_id, project_id, start_n, end_m, label, ts),
    )
    conn.commit()
    return Episode(
        episode_id=episode_id,
        project_id=project_id,
        start_n=start_n,
        end_m=end_m,
        label=label,
        created_at=ts,
    )


def list_episodes(conn, project_id: str) -> list[Episode]:
    rows = conn.execute(
        "SELECT * FROM episodes WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()
    return [_row_to_episode(row) for row in rows]
