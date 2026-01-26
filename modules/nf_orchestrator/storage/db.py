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
        """
        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            path TEXT NOT NULL,
            head_snapshot_id TEXT NOT NULL,
            checksum TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS doc_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            path TEXT NOT NULL,
            checksum TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS episodes (
            episode_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            start_n INTEGER NOT NULL,
            end_m INTEGER NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sections (
            section_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            section_path TEXT NOT NULL,
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            section_path TEXT NOT NULL,
            episode_id TEXT,
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            token_count_est INTEGER,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tag_def (
            tag_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            tag_path TEXT NOT NULL,
            kind TEXT NOT NULL,
            schema_type TEXT NOT NULL,
            constraints_json TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tag_assignment (
            assign_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            tag_path TEXT NOT NULL,
            user_value_json TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS entity (
            entity_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS entity_alias (
            alias_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            alias_text TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            schema_ver TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_snapshot_id TEXT NOT NULL,
            notes TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_facts (
            fact_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            schema_ver TEXT NOT NULL,
            layer TEXT NOT NULL,
            entity_id TEXT,
            tag_path TEXT NOT NULL,
            value_json TEXT NOT NULL,
            evidence_eid TEXT NOT NULL,
            confidence REAL NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS evidence (
            eid TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            chunk_id TEXT,
            section_path TEXT NOT NULL,
            tag_path TEXT NOT NULL,
            snippet_text TEXT NOT NULL,
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            fts_score REAL NOT NULL,
            match_type TEXT NOT NULL,
            confirmed INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS verdict_log (
            vid TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            input_doc_id TEXT NOT NULL,
            input_snapshot_id TEXT NOT NULL,
            schema_ver TEXT NOT NULL,
            segment_start INTEGER NOT NULL,
            segment_end INTEGER NOT NULL,
            claim_text TEXT NOT NULL,
            verdict TEXT NOT NULL,
            reliability_overall REAL NOT NULL,
            breakdown_json TEXT NOT NULL,
            whitelist_applied INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS verdict_evidence_link (
            vid TEXT NOT NULL,
            eid TEXT NOT NULL,
            role TEXT NOT NULL,
            PRIMARY KEY (vid, eid, role)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS whitelist_item (
            wid TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            claim_fingerprint TEXT NOT NULL,
            scope TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fts_meta (
            doc_id TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            last_indexed_at TEXT NOT NULL
        )
        """,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_docs USING fts5(
            content,
            chunk_id UNINDEXED,
            doc_id UNINDEXED,
            snapshot_id UNINDEXED,
            section_path UNINDEXED,
            tag_path UNINDEXED,
            episode_id UNINDEXED,
            span_start UNINDEXED,
            span_end UNINDEXED
        )
        """,
    )
    for stmt in statements:
        conn.execute(stmt)
    _ensure_columns(conn, "jobs", "priority", "priority INTEGER NOT NULL DEFAULT 100")
    _ensure_columns(conn, "jobs", "lease_owner", "lease_owner TEXT")
    _ensure_columns(conn, "jobs", "lease_expires_at", "lease_expires_at TEXT")
    _ensure_columns(conn, "jobs", "attempts", "attempts INTEGER NOT NULL DEFAULT 0")
    _ensure_columns(conn, "jobs", "max_attempts", "max_attempts INTEGER NOT NULL DEFAULT 1")
    _ensure_columns(conn, "jobs", "error_code", "error_code TEXT")
    _ensure_columns(conn, "jobs", "error_message", "error_message TEXT")
    conn.commit()


def _ensure_columns(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
