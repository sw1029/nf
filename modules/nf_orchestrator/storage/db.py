from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

DEFAULT_DB_PATH = Path(os.environ.get("NF_ORCH_DB_PATH", "nf_orchestrator.sqlite3"))


def get_db_path() -> Path:
    return DEFAULT_DB_PATH


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize(conn)
    return conn


def _initialize(conn: sqlite3.Connection) -> None:
    statements: Iterable[str] = (
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            queued_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            inputs_json TEXT,
            params_json TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            job_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            progress REAL,
            metrics_json TEXT,
            payload_json TEXT
        )
        """,
    )
    for stmt in statements:
        conn.execute(stmt)
    conn.commit()
