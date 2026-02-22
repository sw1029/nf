from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import evidence_repo
from modules.nf_shared.protocol.dtos import ReliabilityBreakdown, Span, Verdict, VerdictLog


@pytest.mark.unit
def test_verdict_unknown_reasons_are_persisted_and_loaded(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    verdict = VerdictLog(
        vid="vid-1",
        project_id="project-1",
        input_doc_id="doc-1",
        input_snapshot_id="snap-1",
        schema_ver="schema-1",
        segment_span=Span(start=0, end=12),
        claim_text="claim text",
        verdict=Verdict.UNKNOWN,
        reliability_overall=0.2,
        breakdown=ReliabilityBreakdown(
            fts_strength=0.0,
            evidence_count=0,
            confirmed_evidence=0,
            model_score=0.0,
        ),
        whitelist_applied=False,
        created_at="2026-02-22T00:00:00Z",
        unknown_reasons=("NO_EVIDENCE", "AMBIGUOUS_ENTITY"),
    )

    with db.connect(db_path) as conn:
        evidence_repo.create_verdict_log(conn, verdict)

    with db.connect(db_path) as conn:
        loaded = evidence_repo.get_verdict(conn, "vid-1")
        listed = evidence_repo.list_verdicts(conn, "project-1")

    assert loaded is not None
    assert loaded.unknown_reasons == ("NO_EVIDENCE", "AMBIGUOUS_ENTITY")
    assert len(listed) == 1
    assert listed[0].unknown_reasons == ("NO_EVIDENCE", "AMBIGUOUS_ENTITY")
