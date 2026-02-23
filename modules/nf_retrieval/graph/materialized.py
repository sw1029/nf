from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.nf_retrieval.vector.shard_store import DEFAULT_VECTOR_PATH


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def graph_index_path(project_id: str) -> Path:
    safe = project_id.replace("/", "_").replace("\\", "_")
    return DEFAULT_VECTOR_PATH / "graph" / f"{safe}.json"


def _append_set(mapping: dict[str, set[str]], key: str, value: str) -> None:
    bucket = mapping.setdefault(key, set())
    bucket.add(value)


def _normalize_term(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _to_sorted_lists(mapping: dict[str, set[str]]) -> dict[str, list[str]]:
    return {key: sorted(values) for key, values in mapping.items()}


def build_project_graph(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    entity_doc_ids: dict[str, set[str]] = {}
    time_doc_ids: dict[str, set[str]] = {}
    timeline_doc_ids: dict[str, set[str]] = {}
    doc_entities: dict[str, set[str]] = {}
    doc_times: dict[str, set[str]] = {}
    doc_timelines: dict[str, set[str]] = {}
    entity_aliases: dict[str, set[str]] = {}
    entity_terms: dict[str, set[str]] = {}

    mention_rows = conn.execute(
        """
        SELECT entity_id, doc_id
        FROM entity_mention_span
        WHERE project_id = ? AND status != 'REJECTED'
        """,
        (project_id,),
    ).fetchall()
    for row in mention_rows:
        entity_id = str(row["entity_id"] or "")
        doc_id = str(row["doc_id"] or "")
        if not entity_id or not doc_id:
            continue
        _append_set(entity_doc_ids, entity_id, doc_id)
        _append_set(doc_entities, doc_id, entity_id)

    anchor_rows = conn.execute(
        """
        SELECT doc_id, time_key, timeline_idx
        FROM time_anchor
        WHERE project_id = ? AND status != 'REJECTED'
        """,
        (project_id,),
    ).fetchall()
    for row in anchor_rows:
        doc_id = str(row["doc_id"] or "")
        if not doc_id:
            continue
        time_key = str(row["time_key"] or "")
        if time_key:
            _append_set(time_doc_ids, time_key, doc_id)
            _append_set(doc_times, doc_id, time_key)
        timeline_idx = row["timeline_idx"]
        if timeline_idx is not None:
            timeline_key = str(int(timeline_idx))
            _append_set(timeline_doc_ids, timeline_key, doc_id)
            _append_set(doc_timelines, doc_id, timeline_key)

    timeline_rows = conn.execute(
        """
        SELECT source_doc_id, time_key, timeline_idx
        FROM timeline_event
        WHERE project_id = ? AND status != 'REJECTED'
        """,
        (project_id,),
    ).fetchall()
    for row in timeline_rows:
        doc_id = str(row["source_doc_id"] or "")
        if not doc_id:
            continue
        time_key = str(row["time_key"] or "")
        if time_key:
            _append_set(time_doc_ids, time_key, doc_id)
            _append_set(doc_times, doc_id, time_key)
        timeline_idx = row["timeline_idx"]
        if timeline_idx is not None:
            timeline_key = str(int(timeline_idx))
            _append_set(timeline_doc_ids, timeline_key, doc_id)
            _append_set(doc_timelines, doc_id, timeline_key)

    entity_rows = conn.execute(
        """
        SELECT entity_id, canonical_name
        FROM entity
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchall()
    for row in entity_rows:
        entity_id = str(row["entity_id"] or "")
        canonical = _normalize_term(str(row["canonical_name"] or ""))
        if entity_id and canonical:
            _append_set(entity_aliases, entity_id, canonical)

    alias_rows = conn.execute(
        """
        SELECT entity_id, alias_text
        FROM entity_alias
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchall()
    for row in alias_rows:
        entity_id = str(row["entity_id"] or "")
        alias_text = _normalize_term(str(row["alias_text"] or ""))
        if entity_id and alias_text:
            _append_set(entity_aliases, entity_id, alias_text)

    fact_rows = conn.execute(
        """
        SELECT entity_id, tag_path, value_json
        FROM schema_facts
        WHERE project_id = ? AND status = 'APPROVED'
        """,
        (project_id,),
    ).fetchall()
    for row in fact_rows:
        entity_id = row["entity_id"]
        if not isinstance(entity_id, str) or not entity_id:
            continue
        tag_path = _normalize_term(str(row["tag_path"] or ""))
        value_raw = str(row["value_json"] or "")
        try:
            value_obj = json.loads(value_raw)
            if isinstance(value_obj, str):
                value = _normalize_term(value_obj)
            else:
                value = _normalize_term(str(value_obj))
        except json.JSONDecodeError:
            value = _normalize_term(value_raw)
        if tag_path:
            _append_set(entity_terms, entity_id, tag_path)
        if value:
            _append_set(entity_terms, entity_id, value)

    return {
        "project_id": project_id,
        "built_at": _now_ts(),
        "entity_doc_ids": _to_sorted_lists(entity_doc_ids),
        "time_doc_ids": _to_sorted_lists(time_doc_ids),
        "timeline_doc_ids": _to_sorted_lists(timeline_doc_ids),
        "doc_entities": _to_sorted_lists(doc_entities),
        "doc_times": _to_sorted_lists(doc_times),
        "doc_timelines": _to_sorted_lists(doc_timelines),
        "entity_aliases": _to_sorted_lists(entity_aliases),
        "entity_terms": _to_sorted_lists(entity_terms),
    }


def materialize_project_graph(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    graph = build_project_graph(conn, project_id)
    path = graph_index_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return graph


def load_project_graph(project_id: str) -> dict[str, Any] | None:
    path = graph_index_path(project_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
