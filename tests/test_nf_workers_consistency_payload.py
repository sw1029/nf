from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo
from modules.nf_shared.protocol.dtos import (
    DocumentType,
    ReliabilityBreakdown,
    Span,
    Verdict,
    VerdictLog,
)
from modules.nf_workers import runner


def _seed_document(
    conn,
    *,
    tmp_path: Path,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    text: str,
) -> None:
    text_path = tmp_path / f"{doc_id}_{snapshot_id}.txt"
    text_path.write_text(text, encoding="utf-8")
    checksum = docstore.checksum_text(text)
    document_repo.create_snapshot(
        conn,
        snapshot_id=snapshot_id,
        project_id=project_id,
        doc_id=doc_id,
        version=1,
        path=str(text_path),
        checksum=checksum,
    )
    document_repo.create_document(
        conn,
        doc_id=doc_id,
        project_id=project_id,
        title="Doc",
        doc_type=DocumentType.EPISODE,
        path=str(text_path),
        head_snapshot_id=snapshot_id,
        checksum=checksum,
        version=1,
    )


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
    payload = json.loads(row["payload_json"])
    assert isinstance(payload, dict)
    return payload


@pytest.mark.unit
def test_consistency_complete_payload_includes_unknown_reason_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "시로는 10살이다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    def fake_run(self, req):  # noqa: ANN001
        stats = req.get("stats")
        if isinstance(stats, dict):
            stats["unknown_reason_counts"] = {"NO_EVIDENCE": 1, "SLOT_UNCOMPARABLE": 1}
        return [
            VerdictLog(
                vid="vid-1",
                project_id=project_id,
                input_doc_id=doc_id,
                input_snapshot_id=snapshot_id,
                schema_ver="",
                segment_span=Span(start=0, end=len(text)),
                claim_text=text,
                verdict=Verdict.UNKNOWN,
                reliability_overall=0.25,
                breakdown=ReliabilityBreakdown(
                    fts_strength=0.0,
                    evidence_count=1,
                    confirmed_evidence=0,
                    model_score=0.0,
                ),
                whitelist_applied=False,
                created_at="2026-02-22T00:00:00Z",
            )
        ]

    monkeypatch.setattr("modules.nf_workers.runner.ConsistencyEngineImpl.run", fake_run)

    ctx = runner.WorkerContext(
        job_id="job-consistency-1",
        project_id=project_id,
        payload={
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "preflight": {
                "ensure_ingest": False,
                "ensure_index_fts": False,
                "schema_scope": "latest_approved",
            },
        },
        params={},
        db_path=db_path,
    )
    runner._handle_consistency(ctx)

    with db.connect(db_path) as conn:
        payload = _last_event_payload(conn, ctx.job_id)
    reason_counts = payload.get("unknown_reason_counts")
    assert isinstance(reason_counts, dict)
    assert int(reason_counts.get("NO_EVIDENCE", 0)) == 1
    assert int(reason_counts.get("SLOT_UNCOMPARABLE", 0)) == 1
    assert payload.get("graph_mode") == "off"
    assert "graph_expand_applied_count" in payload
    assert "graph_auto_trigger_count" in payload
    assert "graph_auto_skip_count" in payload
    assert "metadata_grouping_enabled" in payload
    assert "entity_unresolved_skip_count" in payload
    assert "numeric_conflict_unknown_count" in payload
    assert "confirmed_overlap_rejected_count" in payload
    assert "layer3_rerank_applied_count" in payload
    assert "layer3_model_fallback_count" in payload
    assert "layer3_model_enabled" in payload
    assert "layer3_local_nli_enabled" in payload
    assert "layer3_local_reranker_enabled" in payload
    assert "layer3_remote_api_enabled" in payload
    assert "layer3_nli_capable" in payload
    assert "layer3_reranker_capable" in payload
    assert "layer3_effective_capable" in payload
    assert "layer3_promotion_enabled" in payload
    assert "layer3_inactive_reasons" in payload
    assert "verification_loop_trigger_count" in payload
    assert "verification_loop_attempted_rounds_total" in payload
    assert "verification_loop_rounds_total" in payload
    assert "verification_loop_timeout_count" in payload
    assert "verification_loop_stagnation_break_count" in payload
    assert "verification_loop_round_elapsed_ms_sum" in payload
    assert "verification_loop_round_elapsed_ms_max" in payload
    assert "verification_loop_round_elapsed_ms_samples" in payload
    assert "verification_loop_candidate_growth_total" in payload
    assert "verification_loop_candidate_growth_samples" in payload
    assert "verification_loop_exit_reason_counts" in payload
    assert "verification_loop_reason_transition_counts" in payload
    assert "self_evidence_filtered_count" in payload
    assert "layer3_promoted_ok_count" in payload


@pytest.mark.unit
def test_consistency_worker_forwards_layer3_promotion_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "sample"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    captured_req: dict[str, object] = {}

    def fake_run(self, req):  # noqa: ANN001
        captured_req.update(req)
        return []

    monkeypatch.setattr("modules.nf_workers.runner.ConsistencyEngineImpl.run", fake_run)

    ctx = runner.WorkerContext(
        job_id="job-consistency-2",
        project_id=project_id,
        payload={
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "preflight": {
                "ensure_ingest": False,
                "ensure_index_fts": False,
                "schema_scope": "latest_approved",
            },
        },
        params={
            "consistency": {
                "layer3_verdict_promotion": True,
                "layer3_min_fts_for_promotion": 0.33,
                "layer3_max_claim_chars": 180,
                "layer3_ok_threshold": 0.91,
                "layer3_contradict_threshold": 0.86,
                "graph_mode": "auto",
                "verifier": {
                    "mode": "conservative_nli",
                    "promote_ok_threshold": 0.95,
                    "contradict_alert_threshold": 0.70,
                    "max_claim_chars": 220,
                },
                "triage": {
                    "mode": "embedding_anomaly",
                    "anomaly_threshold": 0.66,
                    "max_segments_per_run": 6,
                },
                "verification_loop": {
                    "enabled": True,
                    "max_rounds": 2,
                    "round_timeout_ms": 250,
                },
                "metadata_grouping_enabled": True,
            }
        },
        db_path=db_path,
    )
    runner._handle_consistency(ctx)

    assert captured_req.get("layer3_verdict_promotion") is True
    assert float(captured_req.get("layer3_min_fts_for_promotion", 0.0)) == pytest.approx(0.33)
    assert int(captured_req.get("layer3_max_claim_chars", 0)) == 180
    assert float(captured_req.get("layer3_ok_threshold", 0.0)) == pytest.approx(0.91)
    assert float(captured_req.get("layer3_contradict_threshold", 0.0)) == pytest.approx(0.86)
    assert captured_req.get("graph_mode") == "auto"
    verifier_req = captured_req.get("verifier")
    assert isinstance(verifier_req, dict)
    assert verifier_req.get("mode") == "conservative_nli"
    assert float(verifier_req.get("promote_ok_threshold", 0.0)) == pytest.approx(0.95)
    assert float(verifier_req.get("contradict_alert_threshold", 0.0)) == pytest.approx(0.70)
    assert int(verifier_req.get("max_claim_chars", 0)) == 220
    triage_req = captured_req.get("triage")
    assert isinstance(triage_req, dict)
    assert triage_req.get("mode") == "embedding_anomaly"
    assert float(triage_req.get("anomaly_threshold", 0.0)) == pytest.approx(0.66)
    assert int(triage_req.get("max_segments_per_run", 0)) == 6
    verification_loop_req = captured_req.get("verification_loop")
    assert isinstance(verification_loop_req, dict)
    assert verification_loop_req.get("enabled") is True
    assert int(verification_loop_req.get("max_rounds", 0)) == 2
    assert int(verification_loop_req.get("round_timeout_ms", 0)) == 250
    assert captured_req.get("metadata_grouping_enabled") is True


@pytest.mark.unit
def test_consistency_payload_reports_layer3_capability_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "시로는 10살이다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    def fake_run(self, req):  # noqa: ANN001
        stats = req.get("stats")
        assert isinstance(stats, dict)
        stats["layer3_model_enabled"] = False
        stats["layer3_local_nli_enabled"] = False
        stats["layer3_local_reranker_enabled"] = False
        stats["layer3_remote_api_enabled"] = False
        stats["layer3_nli_capable"] = False
        stats["layer3_reranker_capable"] = False
        stats["layer3_effective_capable"] = False
        stats["layer3_promotion_enabled"] = True
        stats["layer3_inactive_reasons"] = [
            "GLOBAL_LAYER3_MODEL_DISABLED",
            "STRICT_VERIFIER_NLI_UNAVAILABLE",
        ]
        return []

    monkeypatch.setattr("modules.nf_workers.runner.ConsistencyEngineImpl.run", fake_run)

    ctx = runner.WorkerContext(
        job_id="job-consistency-layer3-diag",
        project_id=project_id,
        payload={
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "preflight": {
                "ensure_ingest": False,
                "ensure_index_fts": False,
                "schema_scope": "latest_approved",
            },
        },
        params={
            "consistency": {
                "layer3_verdict_promotion": True,
                "verifier": {"mode": "conservative_nli"},
            }
        },
        db_path=db_path,
    )
    runner._handle_consistency(ctx)

    with db.connect(db_path) as conn:
        payload = _last_event_payload(conn, ctx.job_id)
    assert payload.get("layer3_model_enabled") is False
    assert payload.get("layer3_nli_capable") is False
    assert payload.get("layer3_reranker_capable") is False
    assert payload.get("layer3_effective_capable") is False
    assert payload.get("layer3_promotion_enabled") is True
    inactive = payload.get("layer3_inactive_reasons")
    assert isinstance(inactive, list)
    assert "GLOBAL_LAYER3_MODEL_DISABLED" in inactive
    assert "STRICT_VERIFIER_NLI_UNAVAILABLE" in inactive


@pytest.mark.unit
def test_consistency_worker_retries_transient_sqlite_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "시로는 10살이다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    call_state = {"count": 0}

    def flaky_run(self, req):  # noqa: ANN001
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        stats = req.get("stats")
        assert isinstance(stats, dict)
        return []

    monkeypatch.setattr("modules.nf_workers.runner.ConsistencyEngineImpl.run", flaky_run)
    monkeypatch.setattr("modules.nf_workers.runner.time.sleep", lambda _seconds: None)

    ctx = runner.WorkerContext(
        job_id="job-consistency-retry",
        project_id=project_id,
        payload={
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "preflight": {
                "ensure_ingest": False,
                "ensure_index_fts": False,
                "schema_scope": "latest_approved",
            },
        },
        params={},
        db_path=db_path,
    )
    runner._handle_consistency(ctx)

    assert call_state["count"] == 2
    with db.connect(db_path) as conn:
        events = runner.job_repo.list_job_events(conn, ctx.job_id)
    assert any(event.message == "consistency transient sqlite lock retry" for _, event in events)


@pytest.mark.unit
def test_consistency_preflight_graph_mode_does_not_force_metadata_grouping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "sample"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    captured_params: list[dict[str, object]] = []

    monkeypatch.setattr("modules.nf_workers.runner.ConsistencyEngineImpl.run", lambda _self, _req: [])

    def capture_index_fts(ctx):  # noqa: ANN001
        captured_params.append(dict(ctx.params) if isinstance(ctx.params, dict) else {})

    monkeypatch.setattr("modules.nf_workers.runner._handle_index_fts", capture_index_fts)

    ctx = runner.WorkerContext(
        job_id="job-consistency-preflight-1",
        project_id=project_id,
        payload={
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "preflight": {
                "ensure_ingest": False,
                "ensure_index_fts": True,
                "schema_scope": "latest_approved",
            },
        },
        params={"consistency": {"graph_mode": "auto"}},
        db_path=db_path,
    )
    runner._handle_consistency(ctx)

    assert captured_params
    grouping = captured_params[0].get("grouping")
    assert isinstance(grouping, dict)
    assert grouping.get("graph_extract") is True
    assert grouping.get("entity_mentions") is not True
    assert grouping.get("time_anchors") is not True


@pytest.mark.unit
def test_consistency_preflight_enables_metadata_grouping_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "sample"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    captured_params: list[dict[str, object]] = []

    monkeypatch.setattr("modules.nf_workers.runner.ConsistencyEngineImpl.run", lambda _self, _req: [])

    def capture_index_fts(ctx):  # noqa: ANN001
        captured_params.append(dict(ctx.params) if isinstance(ctx.params, dict) else {})

    monkeypatch.setattr("modules.nf_workers.runner._handle_index_fts", capture_index_fts)

    ctx = runner.WorkerContext(
        job_id="job-consistency-preflight-2",
        project_id=project_id,
        payload={
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "preflight": {
                "ensure_ingest": False,
                "ensure_index_fts": True,
                "schema_scope": "latest_approved",
            },
        },
        params={"consistency": {"graph_mode": "auto", "metadata_grouping_enabled": True}},
        db_path=db_path,
    )
    runner._handle_consistency(ctx)

    assert captured_params
    grouping = captured_params[0].get("grouping")
    assert isinstance(grouping, dict)
    assert grouping.get("graph_extract") is True
    assert grouping.get("entity_mentions") is True
    assert grouping.get("time_anchors") is True
