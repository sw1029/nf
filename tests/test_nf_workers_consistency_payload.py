from __future__ import annotations

import json
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
