from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from modules.nf_shared.protocol.dtos import Project


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_project(row: Any) -> Project:
    return Project(
        project_id=row["project_id"],
        name=row["name"],
        created_at=row["created_at"],
        settings=json.loads(row["settings_json"]),
    )


def create_project(conn, name: str, settings: dict[str, Any]) -> Project:
    project_id = str(uuid.uuid4())
    ts = _now_ts()
    payload = json.dumps(settings or {})
    conn.execute(
        """
        INSERT INTO projects (project_id, name, settings_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, name, payload, ts, ts),
    )
    conn.commit()
    return Project(project_id=project_id, name=name, created_at=ts, settings=settings or {})


def list_projects(conn) -> list[Project]:
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at ASC").fetchall()
    return [_row_to_project(row) for row in rows]


def get_project(conn, project_id: str) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        return None
    return _row_to_project(row)


def update_project(conn, project_id: str, name: str | None, settings: dict[str, Any] | None) -> Project | None:
    existing = conn.execute(
        "SELECT * FROM projects WHERE project_id = ?", (project_id,)
    ).fetchone()
    if existing is None:
        return None

    next_name = name if name is not None else existing["name"]
    next_settings = settings if settings is not None else json.loads(existing["settings_json"])
    ts = _now_ts()
    conn.execute(
        """
        UPDATE projects
        SET name = ?, settings_json = ?, updated_at = ?
        WHERE project_id = ?
        """,
        (next_name, json.dumps(next_settings), ts, project_id),
    )
    conn.commit()
    return Project(project_id=project_id, name=next_name, created_at=existing["created_at"], settings=next_settings)


def delete_project(conn, project_id: str) -> bool:
    cur = conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
    conn.commit()
    return cur.rowcount > 0
