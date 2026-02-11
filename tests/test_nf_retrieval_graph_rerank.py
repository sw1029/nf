from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db
from modules.nf_retrieval.graph.rerank import rerank_results_with_graph


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.unit
def test_graph_rerank_boosts_seeded_doc(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    entity_id = "entity-siro"

    with db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO entity (entity_id, project_id, kind, canonical_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entity_id, project_id, "CHAR", "시로", _ts()),
        )
        conn.execute(
            """
            INSERT INTO entity_alias (alias_id, project_id, entity_id, alias_text, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), project_id, entity_id, "시로", "AUTO", _ts()),
        )
        conn.execute(
            """
            INSERT INTO entity_mention_span (
                mention_id, project_id, doc_id, snapshot_id, entity_id,
                span_start, span_end, status, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), project_id, "doc-a", "snap-a", entity_id, 0, 12, "APPROVED", "AUTO", _ts()),
        )
        conn.commit()

        results = [
            {
                "source": "vector",
                "score": 0.40,
                "evidence": {"doc_id": "doc-b", "span_start": 0, "span_end": 10},
            },
            {
                "source": "vector",
                "score": 0.20,
                "evidence": {"doc_id": "doc-a", "span_start": 0, "span_end": 10},
            },
        ]
        reranked, meta = rerank_results_with_graph(
            conn,
            project_id=project_id,
            query="시로는 누구인가",
            results=results,
            filters={},
            max_hops=1,
            rerank_weight=0.30,
        )

    assert meta["applied"] is True
    assert reranked[0]["evidence"]["doc_id"] == "doc-a"
    assert float(reranked[0]["score"]) > float(reranked[1]["score"])


@pytest.mark.unit
def test_graph_rerank_skips_when_no_seed(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"

    with db.connect(db_path) as conn:
        results = [
            {
                "source": "vector",
                "score": 0.40,
                "evidence": {"doc_id": "doc-b", "span_start": 0, "span_end": 10},
            }
        ]
        reranked, meta = rerank_results_with_graph(
            conn,
            project_id=project_id,
            query="무관한 질의",
            results=results,
            filters={},
            max_hops=1,
            rerank_weight=0.25,
        )

    assert meta["applied"] is False
    assert reranked == results

