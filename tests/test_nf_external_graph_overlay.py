from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib import request

import pytest

from modules.nf_orchestrator.main import OrchestratorHTTPServer, OrchestratorHandler
from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import external_graph_repo
from modules.nf_retrieval.graph.external_adapter import bundle_from_artifacts, bundle_from_project_kg
from modules.nf_retrieval.graph.rerank import rerank_results_with_graph
from modules.nf_retrieval.graph.story_package import decode_story_package, make_story_package


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.unit
def test_dataset_artifact_adapter_namespaces_and_truncates_source_text() -> None:
    long_quote = "가" * 500
    artifacts = {
        "kg_nodes.jsonl": "\n".join(
            [
                json.dumps(
                    {
                        "id": "char-1",
                        "type": "Character",
                        "canonical_name": "서윤",
                        "aliases": ["Seoyun"],
                        "evidence_ids": ["ev-1"],
                        "quote": long_quote,
                        "schema_version": "draft",
                    },
                    ensure_ascii=False,
                ),
                json.dumps({"id": "place-1", "type": "Place", "name": "검은 등대"}, ensure_ascii=False),
            ]
        ),
        "kg_edges.jsonl": json.dumps(
            {
                "edge_id": "edge-1",
                "source_id": "char-1",
                "target_id": "place-1",
                "edge_type": "located_at",
                "evidence_id": "ev-2",
            },
            ensure_ascii=False,
        ),
    }

    bundle = bundle_from_artifacts(
        source_id="source-a",
        source_label="외부 KG",
        artifacts=artifacts,
        schema_version="draft-v1",
    )

    assert bundle["adapter_version"] == "nf-external-kg-v1"
    assert bundle["schema_version"] == "draft-v1"
    assert {node["node_ref"] for node in bundle["nodes"]} == {
        "ext:source-a:char-1",
        "ext:source-a:place-1",
    }
    assert bundle["edges"][0]["src_node_ref"] == "ext:source-a:char-1"
    assert bundle["edges"][0]["dst_node_ref"] == "ext:source-a:place-1"
    char_node = next(node for node in bundle["nodes"] if node["native_id"] == "char-1")
    assert char_node["payload"]["quote"].endswith("...")
    assert char_node["payload"]["quote_truncated"] is True
    assert "ev-1" in char_node["evidence_refs"]


@pytest.mark.unit
def test_nf_project_adapter_preserves_internal_kg_edges() -> None:
    kg = {
        "build": {"build_id": "build-1"},
        "nodes": [
            {
                "node_id": "entity-1",
                "node_type": "entity",
                "label": "서윤",
                "payload": {"kind": "CHAR", "canonical_name": "서윤", "aliases": ["Seoyun"]},
                "status": "ACTIVE",
                "confidence": 1.0,
            },
            {
                "node_id": "doc-1",
                "node_type": "document",
                "label": "1화",
                "payload": {"doc_id": "doc-1"},
                "status": "ACTIVE",
                "confidence": 1.0,
            },
        ],
        "edges": [
            {
                "edge_id": "edge-1",
                "src_node_id": "entity-1",
                "dst_node_id": "doc-1",
                "edge_type": "MENTIONED_IN",
                "payload": {},
                "status": "ACTIVE",
                "confidence": 1.0,
            }
        ],
    }

    bundle = bundle_from_project_kg(
        source_id="source-b",
        source_label="다른 작품",
        linked_project_id="project-b",
        kg=kg,
    )

    assert bundle["source_kind"] == "nf_project"
    assert bundle["metadata"]["linked_project_id"] == "project-b"
    assert [node["node_ref"] for node in bundle["nodes"]] == [
        "ext:source-b:entity-1",
        "ext:source-b:doc-1",
    ]
    assert bundle["edges"][0]["edge_type"] == "MENTIONED_IN"


@pytest.mark.unit
def test_external_graph_repo_keeps_overlay_separate_from_project_kg(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-a"
    bundle = bundle_from_artifacts(
        source_id="source-c",
        source_label="외부 KG",
        artifacts={"kg_nodes.jsonl": json.dumps({"id": "node-1", "type": "Character", "name": "서윤"}, ensure_ascii=False)},
    )

    with db.connect(db_path) as conn:
        source = external_graph_repo.replace_external_graph_source(conn, project_id=project_id, bundle=bundle)
        link = external_graph_repo.create_external_link(
            conn,
            project_id=project_id,
            source_id=source["source_id"],
            src_node_ref="entity:current-1",
            dst_node_ref="ext:source-c:node-1",
            relation_type="SAME_ENTITY",
            label="같은 인물/대상",
        )
        overlay = external_graph_repo.load_external_graph_overlay(conn, project_id)
        kg_nodes = conn.execute("SELECT COUNT(*) AS cnt FROM kg_node").fetchone()["cnt"]

    assert source["enabled"] is True
    assert overlay["nodes"][0]["node_ref"] == "ext:source-c:node-1"
    assert overlay["links"][0]["link_id"] == link["link_id"]
    assert kg_nodes == 0


@pytest.mark.unit
def test_external_manual_link_adds_graphrag_bridge_signal(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-a"
    entity_id = "entity-hero"
    external_source_id = "source-d"

    bundle = bundle_from_artifacts(
        source_id=external_source_id,
        source_label="검은 등대",
        artifacts={
            "kg_nodes.jsonl": json.dumps(
                {
                    "id": "external-hero",
                    "type": "Character",
                    "canonical_name": "Black Lighthouse Keeper",
                    "aliases": ["검은 등대지기"],
                },
                ensure_ascii=False,
            )
        },
    )

    with db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO entity (entity_id, project_id, kind, canonical_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entity_id, project_id, "CHAR", "서윤", _ts()),
        )
        conn.execute(
            """
            INSERT INTO entity_mention_span (
                mention_id, project_id, doc_id, snapshot_id, entity_id,
                span_start, span_end, status, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), project_id, "doc-current", "snap-1", entity_id, 0, 2, "APPROVED", "AUTO", _ts()),
        )
        external_graph_repo.replace_external_graph_source(conn, project_id=project_id, bundle=bundle)
        external_graph_repo.create_external_link(
            conn,
            project_id=project_id,
            source_id=external_source_id,
            src_node_ref=f"entity:{entity_id}",
            dst_node_ref=f"ext:{external_source_id}:external-hero",
            relation_type="SAME_ENTITY",
            label="같은 인물/대상",
        )
        conn.commit()

        results = [
            {"source": "vector", "score": 0.40, "evidence": {"doc_id": "doc-other", "span_start": 0, "span_end": 5}},
            {"source": "vector", "score": 0.20, "evidence": {"doc_id": "doc-current", "span_start": 0, "span_end": 5}},
        ]
        reranked, meta = rerank_results_with_graph(
            conn,
            project_id=project_id,
            query="검은 등대지기는 누구인가",
            results=results,
            filters={},
            max_hops=1,
            rerank_weight=0.3,
        )

    assert meta["applied"] is True
    assert meta["external_graph_overlay"]["bridge_signal_count"] >= 1
    assert meta["external_graph_overlay"]["link_count"] == 1
    assert reranked[0]["evidence"]["doc_id"] == "doc-current"


def _json_request(base_url: str, path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=5) as res:  # noqa: S310 - local test server only.
        return json.loads(res.read().decode("utf-8"))


@pytest.mark.unit
def test_external_graph_http_endpoints_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "orchestrator.db"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    server: ThreadingHTTPServer = OrchestratorHTTPServer(("127.0.0.1", 0), OrchestratorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        created = _json_request(base_url, "/projects", method="POST", payload={"name": "Current", "settings": {}})
        project_id = created["project"]["project_id"]
        source_res = _json_request(
            base_url,
            f"/projects/{project_id}/graph/external-sources",
            method="POST",
            payload={
                "source_kind": "dataset_artifact_set",
                "source_label": "외부 KG",
                "artifacts": {
                    "kg_nodes.jsonl": json.dumps(
                        {"id": "ext-node", "type": "Character", "name": "외부 인물"},
                        ensure_ascii=False,
                    )
                },
            },
        )
        source_id = source_res["source"]["source_id"]
        view = _json_request(base_url, f"/projects/{project_id}/graph/view")
        assert view["external_graph"]["nodes"][0]["node_ref"] == f"ext:{source_id}:ext-node"

        link_res = _json_request(
            base_url,
            f"/projects/{project_id}/graph/external-links",
            method="POST",
            payload={
                "src_node_ref": "doc:current-doc",
                "dst_node_ref": f"ext:{source_id}:ext-node",
                "relation_type": "SAME_ENTITY",
                "label": "같은 인물/대상",
            },
        )
        link_id = link_res["link"]["link_id"]
        view = _json_request(base_url, f"/projects/{project_id}/graph/view")
        assert view["external_graph"]["links"][0]["link_id"] == link_id

        _json_request(base_url, f"/projects/{project_id}/graph/external-links/{link_id}", method="DELETE")
        view = _json_request(base_url, f"/projects/{project_id}/graph/view")
        assert view["external_graph"]["links"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.unit
def test_story_package_obfuscates_and_roundtrips_knowledge_graph() -> None:
    payload = {
        "bundle": {
            "source_label": "검은 등대",
            "nodes": [{"id": "char-1", "type": "Character", "name": "서윤"}],
            "edges": [],
        }
    }

    package = make_story_package(
        display_name="검은 등대 정리",
        content_kind="knowledge_graph",
        payload=payload,
        payload_encoding="obfuscated-v1",
    )

    assert package["format"] == "nf-story-package-v1"
    assert package["payload_encoding"] == "obfuscated-v1"
    assert "서윤" not in str(package["payload"])
    content_kind, decoded = decode_story_package(package)
    assert content_kind == "knowledge_graph"
    assert decoded == payload


@pytest.mark.unit
def test_graph_story_package_import_and_favorites_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "orchestrator.db"
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", db_path)
    server: ThreadingHTTPServer = OrchestratorHTTPServer(("127.0.0.1", 0), OrchestratorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        created = _json_request(base_url, "/projects", method="POST", payload={"name": "Current", "settings": {}})
        project_id = created["project"]["project_id"]
        package = make_story_package(
            display_name="Imported Story",
            content_kind="knowledge_graph",
            payload={
                "bundle": {
                    "source_label": "Imported Story",
                    "nodes": [{"id": "node-a", "type": "Character", "name": "A"}],
                    "edges": [],
                }
            },
            payload_encoding="obfuscated-v1",
        )
        imported = _json_request(
            base_url,
            f"/projects/{project_id}/graph/story-package/import",
            method="POST",
            payload={"package": package},
        )
        source_id = imported["source"]["source_id"]
        node_ref = f"ext:{source_id}:node-a"

        favorite = _json_request(
            base_url,
            f"/projects/{project_id}/graph/favorites",
            method="POST",
            payload={
                "node_ref": node_ref,
                "node_kind": "Character",
                "source_id": source_id,
                "label_snapshot": "A",
            },
        )
        assert favorite["favorite"]["node_ref"] == node_ref

        view = _json_request(base_url, f"/projects/{project_id}/graph/view")
        assert view["external_graph"]["favorites"][0]["node_ref"] == node_ref

        _json_request(base_url, f"/projects/{project_id}/graph/favorites", method="DELETE", payload={"node_ref": node_ref})
        view = _json_request(base_url, f"/projects/{project_id}/graph/view")
        assert view["external_graph"]["favorites"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.unit
def test_graph_view_public_copy_hides_internal_dataset_terms() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    js = Path("modules/nf_orchestrator/assets/user_ui.graph_view.js").read_text(encoding="utf-8")
    visible_surface = "\n".join(
        line for line in (html + "\n" + js).splitlines() if "id=" not in line and "dataset." not in line
    )

    forbidden = ["--_dataset", "kg_nodes", "kg_edges", "evidence 파일", "외부 KG", "dataset 산출물"]
    for term in forbidden:
        assert term not in visible_surface

    assert "세계관 연결" in html
    assert "작품 정리 파일" in html
