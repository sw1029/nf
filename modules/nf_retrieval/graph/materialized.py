from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.nf_orchestrator.storage.repos import external_graph_repo, kg_repo
from modules.nf_retrieval.vector.shard_store import DEFAULT_VECTOR_PATH

_WORD_BOUNDARY_RE = re.compile(r"[0-9A-Za-z\uac00-\ud7a3]+")
_SIGNAL_KINDS = ("alias", "term", "time")
_GRAPH_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


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


def _signal_tokens(signal: str) -> set[str]:
    tokens = {match.group(0) for match in _WORD_BOUNDARY_RE.finditer(signal)}
    if not tokens and signal:
        tokens.add(signal)
    return tokens


def _time_signal_variants(time_key: str) -> list[str]:
    normalized = _normalize_term(time_key)
    if not normalized:
        return []
    variants: list[str] = [normalized]
    marker = "/rel:"
    if marker in normalized:
        rel = normalized.split(marker, 1)[1].strip()
        if rel and rel not in variants:
            variants.append(rel)
    return variants


def _to_sorted_lists(mapping: dict[str, set[str]]) -> dict[str, list[str]]:
    return {key: sorted(values) for key, values in mapping.items()}


def _empty_signal_doc_ids() -> dict[str, dict[str, set[str]]]:
    return {kind: {} for kind in _SIGNAL_KINDS}


def _empty_signal_token_index() -> dict[str, dict[str, set[str]]]:
    return {}


def _append_signal_docs(
    signal_doc_ids: dict[str, dict[str, set[str]]],
    signal_token_index: dict[str, dict[str, set[str]]],
    *,
    kind: str,
    signal: str,
    doc_ids: set[str],
) -> None:
    normalized = _normalize_term(signal)
    if kind not in _SIGNAL_KINDS or not normalized or not doc_ids:
        return
    target = signal_doc_ids.setdefault(kind, {}).setdefault(normalized, set())
    target.update(doc_ids)
    for token in _signal_tokens(normalized):
        token_bucket = signal_token_index.setdefault(token, {key: set() for key in _SIGNAL_KINDS})
        token_bucket.setdefault(kind, set()).add(normalized)


def _build_signal_indexes(
    *,
    entity_doc_ids: dict[str, set[str]],
    time_doc_ids: dict[str, set[str]],
    entity_aliases: dict[str, set[str]],
    entity_terms: dict[str, set[str]],
) -> tuple[dict[str, dict[str, list[str]]], dict[str, dict[str, list[str]]]]:
    signal_doc_ids = _empty_signal_doc_ids()
    signal_token_index = _empty_signal_token_index()
    for entity_id, aliases in entity_aliases.items():
        docs = entity_doc_ids.get(entity_id) or set()
        for alias in aliases:
            _append_signal_docs(signal_doc_ids, signal_token_index, kind="alias", signal=alias, doc_ids=docs)
    for entity_id, terms in entity_terms.items():
        docs = entity_doc_ids.get(entity_id) or set()
        for term in terms:
            _append_signal_docs(signal_doc_ids, signal_token_index, kind="term", signal=term, doc_ids=docs)
    for time_key, docs in time_doc_ids.items():
        for signal in _time_signal_variants(time_key):
            _append_signal_docs(signal_doc_ids, signal_token_index, kind="time", signal=signal, doc_ids=docs)
    return (
        {kind: _to_sorted_lists(signal_doc_ids.get(kind, {})) for kind in _SIGNAL_KINDS},
        {
            token: {kind: sorted(values) for kind, values in kinds.items()}
            for token, kinds in signal_token_index.items()
        },
    )


def _node_id(project_id: str, node_type: str, source_id: str) -> str:
    digest = hashlib.sha1(f"{project_id}|{node_type}|{source_id}".encode("utf-8")).hexdigest()[:24]
    return f"kg-node:{digest}"


def _edge_id(project_id: str, edge_type: str, src_node_id: str, dst_node_id: str, source_id: str) -> str:
    digest = hashlib.sha1(
        f"{project_id}|{edge_type}|{src_node_id}|{dst_node_id}|{source_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"kg-edge:{digest}"


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _project_timeline_doc_id(conn: sqlite3.Connection, project_id: str) -> str | None:
    row = conn.execute("SELECT settings_json FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        return None
    try:
        settings = json.loads(row["settings_json"] or "{}")
    except json.JSONDecodeError:
        return None
    timeline_doc_id = settings.get("timeline_doc_id")
    if isinstance(timeline_doc_id, str) and timeline_doc_id.strip():
        return timeline_doc_id.strip()
    return None


def _count(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> int:
    row = conn.execute(query, params).fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)


def _source_snapshot(conn: sqlite3.Connection, project_id: str) -> tuple[str, dict[str, Any]]:
    timeline_doc_id = _project_timeline_doc_id(conn, project_id)
    counts = {
        "documents": _count(conn, "SELECT COUNT(*) FROM documents WHERE project_id = ?", (project_id,)),
        "snapshots": _count(conn, "SELECT COUNT(*) FROM doc_snapshots WHERE project_id = ?", (project_id,)),
        "entities": _count(conn, "SELECT COUNT(*) FROM entity WHERE project_id = ?", (project_id,)),
        "entity_aliases": _count(conn, "SELECT COUNT(*) FROM entity_alias WHERE project_id = ?", (project_id,)),
        "entity_mentions": _count(
            conn,
            "SELECT COUNT(*) FROM entity_mention_span WHERE project_id = ? AND status != 'REJECTED'",
            (project_id,),
        ),
        "time_anchors": _count(
            conn,
            "SELECT COUNT(*) FROM time_anchor WHERE project_id = ? AND status != 'REJECTED'",
            (project_id,),
        ),
        "timeline_events": _count(
            conn,
            "SELECT COUNT(*) FROM timeline_event WHERE project_id = ? AND status != 'REJECTED'",
            (project_id,),
        ),
        "approved_facts": _count(
            conn,
            "SELECT COUNT(*) FROM schema_facts WHERE project_id = ? AND status = 'APPROVED'",
            (project_id,),
        ),
        "evidence": _count(conn, "SELECT COUNT(*) FROM evidence WHERE project_id = ?", (project_id,)),
        "tag_assignments": _count(conn, "SELECT COUNT(*) FROM tag_assignment WHERE project_id = ?", (project_id,)),
        "evidence_linkable": _count(
            conn,
            """
            SELECT COUNT(*)
            FROM schema_facts sf
            JOIN evidence e ON e.eid = sf.evidence_eid
            WHERE sf.project_id = ? AND sf.status = 'APPROVED'
            """,
            (project_id,),
        ),
    }
    max_rows: dict[str, Any] = {}
    for table, id_col in (
        ("documents", "doc_id"),
        ("doc_snapshots", "snapshot_id"),
        ("entity", "entity_id"),
        ("entity_alias", "alias_id"),
        ("entity_mention_span", "mention_id"),
        ("time_anchor", "anchor_id"),
        ("timeline_event", "timeline_event_id"),
        ("schema_facts", "fact_id"),
        ("evidence", "eid"),
        ("tag_assignment", "assign_id"),
    ):
        row = conn.execute(f"SELECT MAX({id_col}) AS max_id FROM {table} WHERE project_id = ?", (project_id,)).fetchone()
        max_rows[table] = row["max_id"] if row is not None else None
    sparse_reason_counts: dict[str, int] = {}
    if counts["entities"] <= 0:
        sparse_reason_counts["entity_missing"] = 1
    if counts["entity_mentions"] <= 0:
        sparse_reason_counts["entity_mentions_missing"] = 1
    if counts["time_anchors"] <= 0:
        sparse_reason_counts["time_anchors_missing"] = 1
    if not timeline_doc_id:
        sparse_reason_counts["timeline_doc_id_missing"] = 1
    if counts["timeline_events"] <= 0:
        sparse_reason_counts["timeline_events_missing"] = 1
    if counts["approved_facts"] <= 0:
        sparse_reason_counts["approved_facts_missing"] = 1
    source_health = {
        "entity_registry_ready": counts["entities"] > 0,
        "entity_mentions_usable": counts["entity_mentions"] > 0,
        "time_anchors_usable": counts["time_anchors"] > 0,
        "timeline_available": bool(timeline_doc_id and counts["timeline_events"] > 0),
        "timeline_doc_id": timeline_doc_id,
        "approved_fact_count": counts["approved_facts"],
        "evidence_linkable_count": counts["evidence_linkable"],
        "tag_assignment_count": counts["tag_assignments"],
        "sparse_reason_counts": sparse_reason_counts,
    }
    source_checksum = _json_hash({"project_id": project_id, "counts": counts, "max_rows": max_rows, "timeline_doc_id": timeline_doc_id})
    return source_checksum, {"counts": counts, "max_rows": max_rows, "source_health": source_health}


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in items:
        value = item.get(key)
        if isinstance(value, str) and value:
            counter[value] += 1
    return dict(sorted(counter.items()))


def get_project_kg_source_state(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    source_checksum, source_meta = _source_snapshot(conn, project_id)
    return {
        "source_checksum": source_checksum,
        "source_counts": dict(source_meta.get("counts") or {}),
        "source_health": dict(source_meta.get("source_health") or {}),
    }


def materialize_project_kg(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    build_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_checksum, source_meta = _source_snapshot(conn, project_id)
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add_node(
        *,
        node_type: str,
        source_table: str,
        source_id: str,
        label: str,
        payload: dict[str, Any],
        status: str = "ACTIVE",
        confidence: float = 1.0,
    ) -> str:
        node_id = _node_id(project_id, node_type, source_id)
        if node_id not in nodes:
            nodes[node_id] = {
                "node_id": node_id,
                "node_type": node_type,
                "source_table": source_table,
                "source_id": source_id,
                "label": label,
                "payload": payload,
                "status": status,
                "confidence": confidence,
            }
        return node_id

    def add_edge(
        *,
        edge_type: str,
        src_node_id: str,
        dst_node_id: str,
        source_table: str,
        source_id: str,
        payload: dict[str, Any] | None = None,
        status: str = "ACTIVE",
        confidence: float = 1.0,
    ) -> None:
        edge_id = _edge_id(project_id, edge_type, src_node_id, dst_node_id, source_id)
        edges.setdefault(
            edge_id,
            {
                "edge_id": edge_id,
                "src_node_id": src_node_id,
                "dst_node_id": dst_node_id,
                "edge_type": edge_type,
                "source_table": source_table,
                "source_id": source_id,
                "payload": payload or {},
                "status": status,
                "confidence": confidence,
            },
        )

    docs = conn.execute("SELECT * FROM documents WHERE project_id = ?", (project_id,)).fetchall()
    for row in docs:
        add_node(
            node_type="document",
            source_table="documents",
            source_id=str(row["doc_id"]),
            label=str(row["title"] or row["doc_id"]),
            payload={
                "doc_id": row["doc_id"],
                "title": row["title"],
                "doc_type": row["type"],
                "head_snapshot_id": row["head_snapshot_id"],
                "checksum": row["checksum"],
            },
        )

    snapshots = conn.execute("SELECT * FROM doc_snapshots WHERE project_id = ?", (project_id,)).fetchall()
    for row in snapshots:
        add_node(
            node_type="snapshot",
            source_table="doc_snapshots",
            source_id=str(row["snapshot_id"]),
            label=str(row["snapshot_id"]),
            payload={
                "snapshot_id": row["snapshot_id"],
                "doc_id": row["doc_id"],
                "version": row["version"],
                "checksum": row["checksum"],
            },
        )

    alias_rows = conn.execute("SELECT * FROM entity_alias WHERE project_id = ?", (project_id,)).fetchall()
    aliases_by_entity: dict[str, list[str]] = {}
    for row in alias_rows:
        aliases_by_entity.setdefault(str(row["entity_id"]), []).append(str(row["alias_text"]))

    entity_rows = conn.execute("SELECT * FROM entity WHERE project_id = ?", (project_id,)).fetchall()
    for row in entity_rows:
        aliases = sorted(set(aliases_by_entity.get(str(row["entity_id"]), [])))
        add_node(
            node_type="entity",
            source_table="entity",
            source_id=str(row["entity_id"]),
            label=str(row["canonical_name"]),
            payload={
                "entity_id": row["entity_id"],
                "kind": row["kind"],
                "canonical_name": row["canonical_name"],
                "aliases": aliases,
            },
        )

    mention_rows = conn.execute(
        "SELECT * FROM entity_mention_span WHERE project_id = ? AND status != 'REJECTED'",
        (project_id,),
    ).fetchall()
    for row in mention_rows:
        entity_id = str(row["entity_id"])
        doc_id = str(row["doc_id"])
        entity_node = add_node(
            node_type="entity",
            source_table="entity",
            source_id=entity_id,
            label=entity_id,
            payload={"entity_id": entity_id, "aliases": []},
            confidence=0.5,
        )
        doc_node = add_node(
            node_type="document",
            source_table="documents",
            source_id=doc_id,
            label=doc_id,
            payload={"doc_id": doc_id},
            confidence=0.5,
        )
        add_edge(
            edge_type="MENTIONED_IN",
            src_node_id=entity_node,
            dst_node_id=doc_node,
            source_table="entity_mention_span",
            source_id=str(row["mention_id"]),
            payload={"span_start": row["span_start"], "span_end": row["span_end"], "snapshot_id": row["snapshot_id"]},
        )

    evidence_rows = conn.execute("SELECT * FROM evidence WHERE project_id = ?", (project_id,)).fetchall()
    evidence_node_by_id: dict[str, str] = {}
    for row in evidence_rows:
        node_id = add_node(
            node_type="evidence",
            source_table="evidence",
            source_id=str(row["eid"]),
            label=str(row["snippet_text"] or row["eid"])[:80],
            payload={
                "eid": row["eid"],
                "doc_id": row["doc_id"],
                "snapshot_id": row["snapshot_id"],
                "chunk_id": row["chunk_id"],
                "tag_path": row["tag_path"],
                "span_start": row["span_start"],
                "span_end": row["span_end"],
                "confirmed": bool(row["confirmed"]),
            },
        )
        evidence_node_by_id[str(row["eid"])] = node_id

    fact_rows = conn.execute(
        "SELECT * FROM schema_facts WHERE project_id = ? AND status = 'APPROVED'",
        (project_id,),
    ).fetchall()
    for row in fact_rows:
        fact_id = str(row["fact_id"])
        try:
            value = json.loads(row["value_json"])
        except json.JSONDecodeError:
            value = row["value_json"]
        fact_node = add_node(
            node_type="schema_fact",
            source_table="schema_facts",
            source_id=fact_id,
            label=str(row["tag_path"]),
            payload={
                "fact_id": fact_id,
                "schema_ver": row["schema_ver"],
                "layer": row["layer"],
                "entity_id": row["entity_id"],
                "tag_path": row["tag_path"],
                "value": value,
                "evidence_eid": row["evidence_eid"],
                "source": row["source"],
            },
            confidence=float(row["confidence"] or 1.0),
        )
        entity_id = row["entity_id"]
        if isinstance(entity_id, str) and entity_id:
            entity_node = add_node(
                node_type="entity",
                source_table="entity",
                source_id=entity_id,
                label=entity_id,
                payload={"entity_id": entity_id, "aliases": []},
                confidence=0.5,
            )
            add_edge(
                edge_type="HAS_FACT",
                src_node_id=entity_node,
                dst_node_id=fact_node,
                source_table="schema_facts",
                source_id=fact_id,
            )
            add_edge(
                edge_type="FACT_ABOUT_ENTITY",
                src_node_id=fact_node,
                dst_node_id=entity_node,
                source_table="schema_facts",
                source_id=fact_id,
            )
        evidence_node = evidence_node_by_id.get(str(row["evidence_eid"]))
        if evidence_node:
            add_edge(
                edge_type="EVIDENCED_BY",
                src_node_id=fact_node,
                dst_node_id=evidence_node,
                source_table="schema_facts",
                source_id=fact_id,
            )

    timeline_rows = conn.execute(
        "SELECT * FROM timeline_event WHERE project_id = ? AND status != 'REJECTED'",
        (project_id,),
    ).fetchall()
    timeline_node_by_idx: dict[int, str] = {}
    for row in timeline_rows:
        node_id = add_node(
            node_type="timeline_event",
            source_table="timeline_event",
            source_id=str(row["timeline_event_id"]),
            label=str(row["label"]),
            payload={
                "timeline_event_id": row["timeline_event_id"],
                "timeline_idx": row["timeline_idx"],
                "label": row["label"],
                "time_key": row["time_key"],
                "source_doc_id": row["source_doc_id"],
                "source_snapshot_id": row["source_snapshot_id"],
                "span_start": row["span_start"],
                "span_end": row["span_end"],
            },
        )
        timeline_node_by_idx[int(row["timeline_idx"])] = node_id
        doc_node = add_node(
            node_type="document",
            source_table="documents",
            source_id=str(row["source_doc_id"]),
            label=str(row["source_doc_id"]),
            payload={"doc_id": row["source_doc_id"]},
            confidence=0.5,
        )
        add_edge(
            edge_type="PART_OF_TIMELINE",
            src_node_id=doc_node,
            dst_node_id=node_id,
            source_table="timeline_event",
            source_id=str(row["timeline_event_id"]),
        )

    anchor_rows = conn.execute(
        "SELECT * FROM time_anchor WHERE project_id = ? AND status != 'REJECTED'",
        (project_id,),
    ).fetchall()
    for row in anchor_rows:
        node_id = add_node(
            node_type="time_anchor",
            source_table="time_anchor",
            source_id=str(row["anchor_id"]),
            label=str(row["time_key"]),
            payload={
                "anchor_id": row["anchor_id"],
                "doc_id": row["doc_id"],
                "snapshot_id": row["snapshot_id"],
                "span_start": row["span_start"],
                "span_end": row["span_end"],
                "time_key": row["time_key"],
                "timeline_idx": row["timeline_idx"],
            },
        )
        doc_node = add_node(
            node_type="document",
            source_table="documents",
            source_id=str(row["doc_id"]),
            label=str(row["doc_id"]),
            payload={"doc_id": row["doc_id"]},
            confidence=0.5,
        )
        add_edge(
            edge_type="ANCHOR_IN_DOC",
            src_node_id=node_id,
            dst_node_id=doc_node,
            source_table="time_anchor",
            source_id=str(row["anchor_id"]),
        )
        timeline_idx = row["timeline_idx"]
        if timeline_idx is not None:
            timeline_node = timeline_node_by_idx.get(int(timeline_idx))
            if timeline_node:
                add_edge(
                    edge_type="ANCHOR_AT_TIME",
                    src_node_id=node_id,
                    dst_node_id=timeline_node,
                    source_table="time_anchor",
                    source_id=str(row["anchor_id"]),
                )
                add_edge(
                    edge_type="PART_OF_TIMELINE",
                    src_node_id=node_id,
                    dst_node_id=timeline_node,
                    source_table="time_anchor",
                    source_id=str(row["anchor_id"]),
                )

    tag_rows = conn.execute("SELECT * FROM tag_assignment WHERE project_id = ?", (project_id,)).fetchall()
    for row in tag_rows:
        node_id = add_node(
            node_type="tag_assignment",
            source_table="tag_assignment",
            source_id=str(row["assign_id"]),
            label=str(row["tag_path"]),
            payload={
                "assign_id": row["assign_id"],
                "doc_id": row["doc_id"],
                "snapshot_id": row["snapshot_id"],
                "tag_path": row["tag_path"],
                "span_start": row["span_start"],
                "span_end": row["span_end"],
                "user_value_json": row["user_value_json"],
            },
        )
        doc_node = add_node(
            node_type="document",
            source_table="documents",
            source_id=str(row["doc_id"]),
            label=str(row["doc_id"]),
            payload={"doc_id": row["doc_id"]},
            confidence=0.5,
        )
        add_edge(
            edge_type="TAGGED_SPAN",
            src_node_id=node_id,
            dst_node_id=doc_node,
            source_table="tag_assignment",
            source_id=str(row["assign_id"]),
        )

    node_list = list(nodes.values())
    edge_list = list(edges.values())
    stats = {
        "node_counts": _count_by(node_list, "node_type"),
        "edge_counts": _count_by(edge_list, "edge_type"),
        "source_counts": source_meta["counts"],
        "built_at": _now_ts(),
    }
    if build_context:
        stats["build_context"] = dict(build_context)
    build = kg_repo.replace_project_kg_build(
        conn,
        project_id=project_id,
        source_checksum=source_checksum,
        source_health=dict(source_meta["source_health"]),
        stats=stats,
        nodes=node_list,
        edges=edge_list,
    )
    return {
        **build,
        "node_counts": stats["node_counts"],
        "edge_counts": stats["edge_counts"],
    }


def _latest_kg_or_build(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    source_checksum, _source_meta = _source_snapshot(conn, project_id)
    latest = kg_repo.get_latest_project_kg_build(conn, project_id)
    if latest is None or latest.get("source_checksum") != source_checksum:
        materialize_project_kg(conn, project_id)
    loaded = kg_repo.load_latest_project_kg(conn, project_id)
    if loaded is None:
        materialize_project_kg(conn, project_id)
        loaded = kg_repo.load_latest_project_kg(conn, project_id)
    if loaded is None:
        return {"build": {}, "nodes": [], "edges": []}
    return loaded


def _project_kg_to_graph(kg: dict[str, Any], project_id: str) -> dict[str, Any]:
    build = kg.get("build") if isinstance(kg.get("build"), dict) else {}
    nodes = kg.get("nodes") if isinstance(kg.get("nodes"), list) else []
    edges = kg.get("edges") if isinstance(kg.get("edges"), list) else []
    node_by_id = {str(node.get("node_id")): node for node in nodes if isinstance(node, dict)}

    entity_doc_ids: dict[str, set[str]] = {}
    time_doc_ids: dict[str, set[str]] = {}
    timeline_doc_ids: dict[str, set[str]] = {}
    doc_entities: dict[str, set[str]] = {}
    doc_times: dict[str, set[str]] = {}
    doc_timelines: dict[str, set[str]] = {}
    entity_aliases: dict[str, set[str]] = {}
    entity_terms: dict[str, set[str]] = {}

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("node_type")
        payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
        if node_type == "entity":
            entity_id = str(payload.get("entity_id") or node.get("source_id") or "")
            if not entity_id:
                continue
            canonical = _normalize_term(str(payload.get("canonical_name") or node.get("label") or ""))
            if canonical:
                _append_set(entity_aliases, entity_id, canonical)
            aliases = payload.get("aliases")
            if isinstance(aliases, list):
                for alias in aliases:
                    normalized = _normalize_term(str(alias))
                    if normalized:
                        _append_set(entity_aliases, entity_id, normalized)
        elif node_type == "schema_fact":
            entity_id = payload.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id:
                continue
            tag_path = _normalize_term(str(payload.get("tag_path") or ""))
            value = payload.get("value")
            value_text = _normalize_term(value if isinstance(value, str) else str(value))
            if tag_path:
                _append_set(entity_terms, entity_id, tag_path)
            if value_text:
                _append_set(entity_terms, entity_id, value_text)
        elif node_type == "timeline_event":
            doc_id = str(payload.get("source_doc_id") or "")
            time_key = str(payload.get("time_key") or "")
            timeline_idx = payload.get("timeline_idx")
            if doc_id and time_key:
                _append_set(time_doc_ids, time_key, doc_id)
                _append_set(doc_times, doc_id, time_key)
            if doc_id and timeline_idx is not None:
                try:
                    timeline_key = str(int(timeline_idx))
                except (TypeError, ValueError):
                    timeline_key = ""
                if timeline_key:
                    _append_set(timeline_doc_ids, timeline_key, doc_id)
                    _append_set(doc_timelines, doc_id, timeline_key)

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_type = edge.get("edge_type")
        src_node = node_by_id.get(str(edge.get("src_node_id")))
        dst_node = node_by_id.get(str(edge.get("dst_node_id")))
        if src_node is None or dst_node is None:
            continue
        src_payload = src_node.get("payload") if isinstance(src_node.get("payload"), dict) else {}
        dst_payload = dst_node.get("payload") if isinstance(dst_node.get("payload"), dict) else {}
        if edge_type == "MENTIONED_IN":
            entity_id = str(src_payload.get("entity_id") or src_node.get("source_id") or "")
            doc_id = str(dst_payload.get("doc_id") or dst_node.get("source_id") or "")
            if entity_id and doc_id:
                _append_set(entity_doc_ids, entity_id, doc_id)
                _append_set(doc_entities, doc_id, entity_id)
        elif edge_type == "EVIDENCED_BY":
            entity_id = str(src_payload.get("entity_id") or "")
            doc_id = str(dst_payload.get("doc_id") or "")
            if entity_id and doc_id:
                _append_set(entity_doc_ids, entity_id, doc_id)
                _append_set(doc_entities, doc_id, entity_id)
        elif edge_type == "ANCHOR_IN_DOC":
            doc_id = str(dst_payload.get("doc_id") or dst_node.get("source_id") or "")
            time_key = str(src_payload.get("time_key") or "")
            if doc_id and time_key:
                _append_set(time_doc_ids, time_key, doc_id)
                _append_set(doc_times, doc_id, time_key)
            timeline_idx = src_payload.get("timeline_idx")
            if doc_id and timeline_idx is not None:
                try:
                    timeline_key = str(int(timeline_idx))
                except (TypeError, ValueError):
                    timeline_key = ""
                if timeline_key:
                    _append_set(timeline_doc_ids, timeline_key, doc_id)
                    _append_set(doc_timelines, doc_id, timeline_key)

    signal_doc_ids, signal_token_index = _build_signal_indexes(
        entity_doc_ids=entity_doc_ids,
        time_doc_ids=time_doc_ids,
        entity_aliases=entity_aliases,
        entity_terms=entity_terms,
    )
    stats = build.get("stats") if isinstance(build.get("stats"), dict) else {}
    return {
        "project_id": project_id,
        "built_at": build.get("built_at") or _now_ts(),
        "kg_build_id": build.get("build_id"),
        "source_checksum": build.get("source_checksum"),
        "source_health": build.get("source_health") if isinstance(build.get("source_health"), dict) else {},
        "kg_node_counts": stats.get("node_counts") if isinstance(stats.get("node_counts"), dict) else _count_by(nodes, "node_type"),
        "kg_edge_counts": stats.get("edge_counts") if isinstance(stats.get("edge_counts"), dict) else _count_by(edges, "edge_type"),
        "entity_doc_ids": _to_sorted_lists(entity_doc_ids),
        "time_doc_ids": _to_sorted_lists(time_doc_ids),
        "timeline_doc_ids": _to_sorted_lists(timeline_doc_ids),
        "doc_entities": _to_sorted_lists(doc_entities),
        "doc_times": _to_sorted_lists(doc_times),
        "doc_timelines": _to_sorted_lists(doc_timelines),
        "entity_aliases": _to_sorted_lists(entity_aliases),
        "entity_terms": _to_sorted_lists(entity_terms),
        "signal_doc_ids": signal_doc_ids,
        "signal_token_index": signal_token_index,
    }


def _signal_list_mapping_to_sets(value: Any) -> dict[str, dict[str, set[str]]]:
    out = _empty_signal_doc_ids()
    if not isinstance(value, dict):
        return out
    for kind in _SIGNAL_KINDS:
        raw_kind = value.get(kind)
        if not isinstance(raw_kind, dict):
            continue
        for signal, doc_ids in raw_kind.items():
            normalized = _normalize_term(str(signal))
            if not normalized:
                continue
            docs = {str(item) for item in doc_ids if isinstance(item, str) and item} if isinstance(doc_ids, list) else set()
            if docs:
                out.setdefault(kind, {}).setdefault(normalized, set()).update(docs)
    return out


def _token_index_list_mapping_to_sets(value: Any) -> dict[str, dict[str, set[str]]]:
    out = _empty_signal_token_index()
    if not isinstance(value, dict):
        return out
    for token, raw_bucket in value.items():
        normalized_token = _normalize_term(str(token))
        if not normalized_token or not isinstance(raw_bucket, dict):
            continue
        bucket = out.setdefault(normalized_token, {kind: set() for kind in _SIGNAL_KINDS})
        for kind in _SIGNAL_KINDS:
            signals = raw_bucket.get(kind)
            if isinstance(signals, list):
                bucket.setdefault(kind, set()).update(_normalize_term(str(signal)) for signal in signals if str(signal).strip())
    return out


def _signal_sets_to_lists(value: dict[str, dict[str, set[str]]]) -> dict[str, dict[str, list[str]]]:
    return {
        kind: {signal: sorted(docs) for signal, docs in signals.items() if docs}
        for kind, signals in value.items()
    }


def _token_index_sets_to_lists(value: dict[str, dict[str, set[str]]]) -> dict[str, dict[str, list[str]]]:
    return {
        token: {kind: sorted(signals) for kind, signals in bucket.items() if signals}
        for token, bucket in value.items()
        if any(bucket.values())
    }


def _doc_ids_for_graph_node_ref(graph: dict[str, Any], node_ref: str) -> set[str]:
    if not node_ref:
        return set()
    if node_ref.startswith("doc:"):
        doc_id = node_ref.split(":", 1)[1]
        return {doc_id} if doc_id else set()
    if node_ref.startswith("entity:"):
        entity_id = node_ref.split(":", 1)[1]
        docs = graph.get("entity_doc_ids", {}).get(entity_id) if isinstance(graph.get("entity_doc_ids"), dict) else []
        return {str(item) for item in docs if isinstance(item, str) and item}
    if node_ref.startswith("time:"):
        time_key = node_ref.split(":", 1)[1]
        docs = graph.get("time_doc_ids", {}).get(time_key) if isinstance(graph.get("time_doc_ids"), dict) else []
        return {str(item) for item in docs if isinstance(item, str) and item}
    return set()


def _external_node_terms(node: dict[str, Any], node_by_ref: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []

    def add(value: Any) -> None:
        normalized = _normalize_term(str(value))
        if normalized and normalized not in terms:
            terms.append(normalized)

    add(node.get("label"))
    aliases = node.get("aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            add(alias)
    payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
    for key in ("canonical_name", "display_name", "name", "title", "summary", "value"):
        add(payload.get(key))
    node_ref = str(node.get("node_ref") or "")
    for edge in edges:
        if edge.get("src_node_ref") == node_ref:
            other = node_by_ref.get(str(edge.get("dst_node_ref")))
        elif edge.get("dst_node_ref") == node_ref:
            other = node_by_ref.get(str(edge.get("src_node_ref")))
        else:
            continue
        add(edge.get("label") or edge.get("edge_type"))
        if other:
            add(other.get("label"))
            for alias in other.get("aliases") or []:
                add(alias)
        if len(terms) >= 30:
            break
    return terms[:30]


def _apply_external_graph_overlay(conn: sqlite3.Connection, project_id: str, graph: dict[str, Any]) -> dict[str, Any]:
    overlay = external_graph_repo.load_external_graph_overlay(conn, project_id, enabled_only=True)
    sources = overlay.get("sources") if isinstance(overlay.get("sources"), list) else []
    nodes = overlay.get("nodes") if isinstance(overlay.get("nodes"), list) else []
    edges = overlay.get("edges") if isinstance(overlay.get("edges"), list) else []
    links = overlay.get("links") if isinstance(overlay.get("links"), list) else []
    if not sources or not nodes or not links:
        graph["external_graph_overlay"] = {
            "source_count": len(sources),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "link_count": len(links),
            "bridge_signal_count": 0,
            "source_ids": [str(source.get("source_id")) for source in sources if source.get("source_id")],
        }
        return graph

    node_by_ref = {str(node.get("node_ref")): node for node in nodes if isinstance(node, dict) and node.get("node_ref")}
    signal_doc_sets = _signal_list_mapping_to_sets(graph.get("signal_doc_ids"))
    token_index_sets = _token_index_list_mapping_to_sets(graph.get("signal_token_index"))
    bridge_signal_count = 0
    source_ids: set[str] = set()
    for link in links:
        if not isinstance(link, dict) or link.get("status") != "ACTIVE":
            continue
        src_ref = str(link.get("src_node_ref") or "")
        dst_ref = str(link.get("dst_node_ref") or "")
        src_external = src_ref.startswith("ext:")
        dst_external = dst_ref.startswith("ext:")
        if src_external == dst_external:
            continue
        external_ref = src_ref if src_external else dst_ref
        current_ref = dst_ref if src_external else src_ref
        external_node = node_by_ref.get(external_ref)
        current_docs = _doc_ids_for_graph_node_ref(graph, current_ref)
        if not external_node or not current_docs:
            continue
        source_id = str(external_node.get("source_id") or "")
        if source_id:
            source_ids.add(source_id)
        for term in _external_node_terms(external_node, node_by_ref, edges):
            _append_signal_docs(signal_doc_sets, token_index_sets, kind="term", signal=term, doc_ids=current_docs)
            bridge_signal_count += 1

    graph["signal_doc_ids"] = _signal_sets_to_lists(signal_doc_sets)
    graph["signal_token_index"] = _token_index_sets_to_lists(token_index_sets)
    edge_counts = graph.get("kg_edge_counts") if isinstance(graph.get("kg_edge_counts"), dict) else {}
    graph["kg_edge_counts"] = {
        **edge_counts,
        "EXTERNAL_MANUAL_LINK": int(edge_counts.get("EXTERNAL_MANUAL_LINK", 0)) + len(links),
    }
    graph["external_graph_overlay"] = {
        "source_count": len(sources),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "link_count": len(links),
        "bridge_signal_count": bridge_signal_count,
        "source_ids": sorted(source_ids or {str(source.get("source_id")) for source in sources if source.get("source_id")}),
    }
    return graph


def build_project_graph(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    kg = _latest_kg_or_build(conn, project_id)
    graph = _project_kg_to_graph(kg, project_id)
    return _apply_external_graph_overlay(conn, project_id, graph)


def materialize_project_graph(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    graph = build_project_graph(conn, project_id)
    path = graph_index_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        stat = path.stat()
        _GRAPH_CACHE[project_id] = (int(stat.st_mtime_ns), int(stat.st_size), graph)
    except OSError:
        pass
    return graph


def load_project_graph(project_id: str) -> dict[str, Any] | None:
    path = graph_index_path(project_id)
    try:
        stat = path.stat()
    except OSError:
        return None
    cache_key = (int(stat.st_mtime_ns), int(stat.st_size))
    cached = _GRAPH_CACHE.get(project_id)
    if cached is not None and cached[0] == cache_key[0] and cached[1] == cache_key[1]:
        return cached[2]
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(graph, dict):
        return None
    _GRAPH_CACHE[project_id] = (cache_key[0], cache_key[1], graph)
    return graph
