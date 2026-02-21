from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db
from modules.nf_workers import runner


def _last_event_payload(conn, job_id: str) -> dict:
    row = conn.execute(
        """
        SELECT payload_json
        FROM job_events
        WHERE job_id = ?
        ORDER BY seq DESC
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    assert row is not None
    raw = row["payload_json"]
    assert isinstance(raw, str) and raw
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def _sample_result() -> dict:
    return {
        "score": 0.8,
        "source": "vector",
        "evidence": {
            "doc_id": "doc-1",
            "snapshot_id": "snap-1",
            "chunk_id": "chunk-1",
            "snippet_text": "sample evidence",
            "span_start": 0,
            "span_end": 14,
        },
    }


@pytest.mark.unit
def test_retrieve_vec_graph_payload_schema_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "orchestrator.db"
    job_id = f"job-{uuid.uuid4()}"
    ctx = runner.WorkerContext(
        job_id=job_id,
        project_id="project-1",
        payload={"query": "sample", "filters": {}, "k": 10},
        params={"graph": {"enabled": True, "max_hops": 1, "rerank_weight": 0.25}},
        db_path=db_path,
    )

    monkeypatch.setattr(runner, "vector_search", lambda _req: [_sample_result()])
    monkeypatch.setattr(
        runner,
        "rerank_results_with_graph",
        lambda _conn, **_kwargs: (
            [_sample_result()],
            {
                "applied": True,
                "seed_docs": ["doc-1"],
                "expanded_docs": ["doc-1", "doc-2"],
                "boosted_results": 1,
            },
        ),
    )

    runner._handle_retrieve_vec(ctx)

    with db.connect(db_path) as conn:
        payload = _last_event_payload(conn, job_id)
    graph = payload.get("graph")
    assert isinstance(graph, dict)
    assert graph.get("enabled") is True
    assert graph.get("applied") is True
    assert graph.get("seed_docs") == ["doc-1"]
    assert graph.get("expanded_docs") == ["doc-1", "doc-2"]
    assert graph.get("boosted_results") == 1


@pytest.mark.unit
def test_retrieve_vec_graph_payload_schema_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "orchestrator.db"
    job_id = f"job-{uuid.uuid4()}"
    ctx = runner.WorkerContext(
        job_id=job_id,
        project_id="project-1",
        payload={"query": "sample", "filters": {}, "k": 10},
        params={"graph": {"enabled": False}},
        db_path=db_path,
    )

    monkeypatch.setattr(runner, "vector_search", lambda _req: [_sample_result()])

    runner._handle_retrieve_vec(ctx)

    with db.connect(db_path) as conn:
        payload = _last_event_payload(conn, job_id)
    graph = payload.get("graph")
    assert isinstance(graph, dict)
    assert graph.get("enabled") is False
    assert graph.get("applied") is False
    assert isinstance(graph.get("seed_docs"), list)
    assert isinstance(graph.get("expanded_docs"), list)
    assert isinstance(graph.get("boosted_results"), int)
