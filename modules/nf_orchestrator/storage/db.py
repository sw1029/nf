from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

DEFAULT_DB_PATH = Path(os.environ.get("NF_ORCH_DB_PATH", "nf_orchestrator.sqlite3"))
_SCHEMA_USER_VERSION = 1
_SQLITE_CONNECT_TIMEOUT_SEC = 30.0
_SQLITE_BUSY_TIMEOUT_MS = 30000
_INITIALIZED_DB_KEYS: set[str] = set()
_INITIALIZE_LOCK = threading.Lock()


def get_db_path() -> Path:
    return DEFAULT_DB_PATH


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = (db_path or get_db_path()).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=_SQLITE_CONNECT_TIMEOUT_SEC)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError:
        pass
    _initialize_if_needed(conn, path)
    return conn


def _db_key(path: Path) -> str:
    return str(path.resolve())


def _get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError, IndexError):
        return 0


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _initialize_if_needed(conn: sqlite3.Connection, path: Path) -> None:
    key = _db_key(path)
    if key in _INITIALIZED_DB_KEYS and _get_user_version(conn) >= _SCHEMA_USER_VERSION:
        return

    with _INITIALIZE_LOCK:
        if key in _INITIALIZED_DB_KEYS and _get_user_version(conn) >= _SCHEMA_USER_VERSION:
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _get_user_version(conn) < _SCHEMA_USER_VERSION:
                _apply_schema(conn)
                _set_user_version(conn, _SCHEMA_USER_VERSION)
            conn.commit()
            _INITIALIZED_DB_KEYS.add(key)
        except Exception:
            conn.rollback()
            raise


def _apply_schema(conn: sqlite3.Connection) -> None:
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
        CREATE TABLE IF NOT EXISTS entity_mention_span (
            mention_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS time_anchor (
            anchor_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            time_key TEXT NOT NULL,
            timeline_idx INTEGER,
            status TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS timeline_event (
            timeline_event_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            timeline_idx INTEGER NOT NULL,
            label TEXT NOT NULL,
            time_key TEXT NOT NULL,
            source_doc_id TEXT NOT NULL,
            source_snapshot_id TEXT NOT NULL,
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            status TEXT NOT NULL,
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
        CREATE TABLE IF NOT EXISTS whitelist_annotation (
            annotation_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            claim_fingerprint TEXT NOT NULL,
            scope TEXT NOT NULL,
            intent_type TEXT NOT NULL,
            reason TEXT,
            meta_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ignore_item (
            iid TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            claim_fingerprint TEXT NOT NULL,
            scope TEXT NOT NULL,
            kind TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS extraction_mappings (
            mapping_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            slot_key TEXT NOT NULL,
            pattern TEXT NOT NULL,
            flags TEXT NOT NULL DEFAULT '',
            transform TEXT NOT NULL DEFAULT 'identity',
            priority INTEGER NOT NULL DEFAULT 100,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
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
        CREATE TABLE IF NOT EXISTS ingest_meta (
            doc_id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            checksum TEXT NOT NULL,
            last_ingested_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fts_snapshot_meta (
            snapshot_id TEXT PRIMARY KEY,
            row_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
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
    _ensure_columns(conn, "jobs", "result_json", "result_json TEXT")
    _ensure_columns(conn, "documents", "metadata_json", "metadata_json TEXT")
    _ensure_columns(conn, "verdict_log", "claim_fingerprint", "claim_fingerprint TEXT")
    _ensure_columns(conn, "verdict_log", "unknown_reasons_json", "unknown_reasons_json TEXT")
    _ensure_indexes(conn)
    _drop_redundant_indexes(conn)
    _backfill_verdict_log_claim_fingerprints(conn)
    _backfill_verdict_log_unknown_reasons(conn)
def _ensure_indexes(conn: sqlite3.Connection) -> None:
    index_statements: Iterable[str] = (
        "CREATE INDEX IF NOT EXISTS idx_jobs_status_type_priority_created ON jobs(status, type, priority, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_job_events_job_seq ON job_events(job_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_documents_project_type ON documents(project_id, type)",
        "CREATE INDEX IF NOT EXISTS idx_doc_snapshots_doc_version ON doc_snapshots(doc_id, version)",
        "CREATE INDEX IF NOT EXISTS idx_chunks_snapshot ON chunks(snapshot_id)",
        "CREATE INDEX IF NOT EXISTS idx_chunks_doc_snapshot ON chunks(doc_id, snapshot_id)",
        "CREATE INDEX IF NOT EXISTS idx_chunks_project_chunk ON chunks(project_id, chunk_id)",
        "CREATE INDEX IF NOT EXISTS idx_tag_assignment_snapshot_span ON tag_assignment(snapshot_id, span_start, span_end)",
        "CREATE INDEX IF NOT EXISTS idx_schema_facts_project_schema_status ON schema_facts(project_id, schema_ver, status)",
        "CREATE INDEX IF NOT EXISTS idx_schema_facts_project_schema_layer_status ON schema_facts(project_id, schema_ver, layer, status)",
        "CREATE INDEX IF NOT EXISTS idx_evidence_project_doc_snapshot ON evidence(project_id, doc_id, snapshot_id)",
        "CREATE INDEX IF NOT EXISTS idx_verdict_log_project_doc_created ON verdict_log(project_id, input_doc_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_entity_mention_lookup ON entity_mention_span(project_id, doc_id, entity_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_time_anchor_lookup ON time_anchor(project_id, doc_id, time_key, timeline_idx, status)",
        "CREATE INDEX IF NOT EXISTS idx_whitelist_lookup ON whitelist_item(project_id, claim_fingerprint, scope)",
        "CREATE INDEX IF NOT EXISTS idx_whitelist_annotation_lookup ON whitelist_annotation(project_id, claim_fingerprint, scope, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_ignore_lookup ON ignore_item(project_id, claim_fingerprint, scope, kind)",
        "CREATE INDEX IF NOT EXISTS idx_extraction_mapping_lookup ON extraction_mappings(project_id, enabled, priority, slot_key)",
    )
    for stmt in index_statements:
        conn.execute(stmt)


def _drop_redundant_indexes(conn: sqlite3.Connection) -> None:
    # PK(vid, eid, role) already provides a left-prefix index on vid.
    try:
        conn.execute("DROP INDEX IF EXISTS idx_verdict_evidence_vid")
    except sqlite3.OperationalError:
        return


def _ensure_columns(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
        except sqlite3.OperationalError as exc:
            refreshed = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column in refreshed and "duplicate column name" in str(exc).lower():
                return
            raise


def _fingerprint(text: str) -> str:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _backfill_verdict_log_claim_fingerprints(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT vid, claim_text
        FROM verdict_log
        WHERE claim_fingerprint IS NULL OR claim_fingerprint = ''
        """,
    ).fetchall()
    if not rows:
        return
    for row in rows:
        conn.execute(
            "UPDATE verdict_log SET claim_fingerprint = ? WHERE vid = ?",
            (_fingerprint(row["claim_text"] or ""), row["vid"]),
        )


def _backfill_verdict_log_unknown_reasons(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT vid
        FROM verdict_log
        WHERE unknown_reasons_json IS NULL OR unknown_reasons_json = ''
        """,
    ).fetchall()
    if not rows:
        return
    for row in rows:
        conn.execute(
            "UPDATE verdict_log SET unknown_reasons_json = '[]' WHERE vid = ?",
            (row["vid"],),
        )
