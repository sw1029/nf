from __future__ import annotations

from datetime import datetime, timezone

import pytest

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import kg_repo
from modules.nf_retrieval.graph.materialized import build_project_graph, materialize_project_kg
from modules.nf_retrieval.graph.rerank import expand_candidate_docs_with_graph


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_project(conn, project_id: str, *, timeline_doc_id: str | None = None) -> None:
    settings_json = "{}" if timeline_doc_id is None else f'{{"timeline_doc_id": "{timeline_doc_id}"}}'
    conn.execute(
        """
        INSERT INTO projects (project_id, name, settings_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, project_id, settings_json, _ts(), _ts()),
    )


def _insert_document(conn, project_id: str, *, doc_id: str, snapshot_id: str) -> None:
    conn.execute(
        """
        INSERT INTO doc_snapshots (snapshot_id, project_id, doc_id, version, path, checksum, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, project_id, doc_id, 1, f"{doc_id}.txt", f"checksum:{doc_id}", _ts()),
    )
    conn.execute(
        """
        INSERT INTO documents (
            doc_id, project_id, title, type, path, head_snapshot_id,
            checksum, version, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (doc_id, project_id, doc_id, "EPISODE", f"{doc_id}.txt", snapshot_id, f"checksum:{doc_id}", 1, _ts(), _ts()),
    )


@pytest.mark.unit
def test_materialize_project_kg_creates_db_graph_and_projection(tmp_path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-kg"

    with db.connect(db_path) as conn:
        _insert_project(conn, project_id, timeline_doc_id="doc-timeline")
        _insert_document(conn, project_id, doc_id="doc-a", snapshot_id="snap-a")
        _insert_document(conn, project_id, doc_id="doc-timeline", snapshot_id="snap-timeline")
        conn.execute(
            "INSERT INTO entity (entity_id, project_id, kind, canonical_name, created_at) VALUES (?, ?, ?, ?, ?)",
            ("entity-siro", project_id, "CHAR", "Siro", _ts()),
        )
        conn.execute(
            """
            INSERT INTO entity_alias (alias_id, project_id, entity_id, alias_text, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("alias-1", project_id, "entity-siro", "시로", "USER", _ts()),
        )
        conn.execute(
            """
            INSERT INTO entity_mention_span (
                mention_id, project_id, doc_id, snapshot_id, entity_id,
                span_start, span_end, status, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("mention-1", project_id, "doc-a", "snap-a", "entity-siro", 0, 2, "APPROVED", "AUTO", _ts()),
        )
        conn.execute(
            """
            INSERT INTO evidence (
                eid, project_id, doc_id, snapshot_id, chunk_id, section_path, tag_path,
                snippet_text, span_start, span_end, fts_score, match_type, confirmed, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "eid-1",
                project_id,
                "doc-a",
                "snap-a",
                None,
                "",
                "profile.affiliation",
                "Siro belongs to Academy.",
                0,
                24,
                1.0,
                "EXACT",
                1,
                _ts(),
            ),
        )
        conn.execute(
            """
            INSERT INTO schema_facts (
                fact_id, project_id, schema_ver, layer, entity_id, tag_path,
                value_json, evidence_eid, confidence, source, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "fact-1",
                project_id,
                "schema-1",
                "explicit",
                "entity-siro",
                "profile.affiliation",
                '"Academy"',
                "eid-1",
                0.95,
                "USER",
                "APPROVED",
            ),
        )
        conn.execute(
            """
            INSERT INTO timeline_event (
                timeline_event_id, project_id, timeline_idx, label, time_key,
                source_doc_id, source_snapshot_id, span_start, span_end, status, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("timeline-1", project_id, 1, "Opening", "T-001", "doc-timeline", "snap-timeline", 0, 10, "APPROVED", "AUTO", _ts()),
        )
        conn.execute(
            """
            INSERT INTO time_anchor (
                anchor_id, project_id, doc_id, snapshot_id, span_start, span_end,
                time_key, timeline_idx, status, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("anchor-1", project_id, "doc-a", "snap-a", 0, 8, "T-001", 1, "APPROVED", "AUTO", _ts()),
        )
        conn.execute(
            """
            INSERT INTO tag_assignment (
                assign_id, project_id, doc_id, snapshot_id, span_start, span_end,
                tag_path, user_value_json, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("assign-1", project_id, "doc-a", "snap-a", 0, 24, "profile.affiliation", '"Academy"', "USER", _ts()),
        )
        conn.commit()

        build = materialize_project_kg(conn, project_id)
        kg = kg_repo.load_latest_project_kg(conn, project_id)
        graph = build_project_graph(conn, project_id)
        candidates, meta = expand_candidate_docs_with_graph(
            conn,
            project_id=project_id,
            query="",
            filters={},
            slots={"affiliation": "Academy"},
            slot_key="affiliation",
            claim_text="Siro affiliation is Academy.",
            max_hops=1,
        )

    assert build["status"] == "SUCCEEDED"
    assert build["source_health"]["entity_registry_ready"] is True
    assert build["source_health"]["entity_mentions_usable"] is True
    assert build["source_health"]["time_anchors_usable"] is True
    assert build["source_health"]["timeline_available"] is True
    assert build["source_health"]["timeline_doc_id"] == "doc-timeline"
    assert kg is not None
    node_types = {node["node_type"] for node in kg["nodes"]}
    edge_types = {edge["edge_type"] for edge in kg["edges"]}
    assert {
        "document",
        "snapshot",
        "entity",
        "evidence",
        "schema_fact",
        "time_anchor",
        "timeline_event",
        "tag_assignment",
    } <= node_types
    assert {
        "MENTIONED_IN",
        "HAS_FACT",
        "FACT_ABOUT_ENTITY",
        "EVIDENCED_BY",
        "ANCHOR_IN_DOC",
        "ANCHOR_AT_TIME",
        "PART_OF_TIMELINE",
        "TAGGED_SPAN",
    } <= edge_types
    assert graph["kg_build_id"] == build["build_id"]
    assert graph["source_health"]["approved_fact_count"] == 1
    assert "doc-a" in graph["entity_doc_ids"]["entity-siro"]
    assert "doc-a" in graph["time_doc_ids"]["T-001"]
    assert "doc-timeline" in graph["timeline_doc_ids"]["1"]
    assert "profile.affiliation" in graph["entity_terms"]["entity-siro"]
    assert candidates == ["doc-a"]
    assert meta["applied"] is True
    assert int(meta["seed_source_counts"].get("slot_hint_match", 0)) >= 1
    assert meta["kg_build_id"] == build["build_id"]


@pytest.mark.unit
def test_materialize_project_kg_reports_sparse_sources_without_blocking_fact_nodes(tmp_path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-sparse"

    with db.connect(db_path) as conn:
        _insert_project(conn, project_id)
        _insert_document(conn, project_id, doc_id="doc-fact", snapshot_id="snap-fact")
        conn.execute(
            """
            INSERT INTO evidence (
                eid, project_id, doc_id, snapshot_id, chunk_id, section_path, tag_path,
                snippet_text, span_start, span_end, fts_score, match_type, confirmed, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("eid-sparse", project_id, "doc-fact", "snap-fact", None, "", "profile.job", "Job evidence", 0, 12, 1.0, "EXACT", 1, _ts()),
        )
        conn.execute(
            """
            INSERT INTO schema_facts (
                fact_id, project_id, schema_ver, layer, entity_id, tag_path,
                value_json, evidence_eid, confidence, source, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("fact-sparse", project_id, "schema-1", "explicit", None, "profile.job", '"Archivist"', "eid-sparse", 0.9, "USER", "APPROVED"),
        )
        conn.commit()

        build = materialize_project_kg(conn, project_id)
        graph = build_project_graph(conn, project_id)
        candidates, meta = expand_candidate_docs_with_graph(
            conn,
            project_id=project_id,
            query="Archivist",
            filters={},
            graph=graph,
        )

    health = build["source_health"]
    sparse = health["sparse_reason_counts"]
    assert health["timeline_available"] is False
    assert health["timeline_doc_id"] is None
    assert health["entity_registry_ready"] is False
    assert health["approved_fact_count"] == 1
    assert health["evidence_linkable_count"] == 1
    assert sparse["entity_missing"] == 1
    assert sparse["timeline_doc_id_missing"] == 1
    assert build["node_counts"]["schema_fact"] == 1
    assert build["node_counts"]["evidence"] == 1
    assert build["node_counts"]["document"] == 1
    assert build["edge_counts"]["EVIDENCED_BY"] == 1
    assert graph["source_health"]["timeline_available"] is False
    assert candidates == []
    assert meta["skip_reason_counts"]["no_seeds"] == 1
    assert meta["skip_reason_counts"]["kg_sparse_entity"] == 1
    assert meta["skip_reason_counts"]["kg_sparse_timeline"] == 1
