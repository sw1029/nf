from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_orchestrator.services.query_service import QueryServiceImpl
from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import evidence_repo
from modules.nf_shared.protocol.dtos import (
    EvidenceMatchType,
    EvidenceRole,
    ReliabilityBreakdown,
    Span,
    Verdict,
    VerdictEvidenceLink,
    VerdictLog,
)


@pytest.mark.unit
def test_build_tag_path_preview_by_vid_prioritizes_contradict_and_caps(tmp_path: Path) -> None:
    service = QueryServiceImpl(db_path=tmp_path / "orchestrator.db")
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    verdict = VerdictLog(
        vid="vid-1",
        project_id=project_id,
        input_doc_id=doc_id,
        input_snapshot_id=snapshot_id,
        schema_ver="schema-1",
        segment_span=Span(start=0, end=10),
        claim_text="hero is 21",
        verdict=Verdict.VIOLATE,
        reliability_overall=0.7,
        breakdown=ReliabilityBreakdown(
            fts_strength=0.1,
            evidence_count=3,
            confirmed_evidence=1,
            model_score=0.0,
        ),
        whitelist_applied=False,
        created_at="2026-02-22T00:00:00Z",
        unknown_reasons=(),
    )
    support = evidence_repo.new_evidence(
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        chunk_id="chunk-s",
        section_path="body",
        tag_path="character.hero.name",
        snippet_text="hero name",
        span_start=0,
        span_end=5,
        fts_score=0.2,
        match_type=EvidenceMatchType.EXACT,
        confirmed=True,
    )
    contradict = evidence_repo.new_evidence(
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        chunk_id="chunk-c",
        section_path="body",
        tag_path="character.hero.age",
        snippet_text="hero age",
        span_start=6,
        span_end=10,
        fts_score=0.3,
        match_type=EvidenceMatchType.EXACT,
        confirmed=True,
    )
    support2 = evidence_repo.new_evidence(
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        chunk_id="chunk-s2",
        section_path="body",
        tag_path="timeline.chapter1.event",
        snippet_text="timeline",
        span_start=11,
        span_end=20,
        fts_score=0.1,
        match_type=EvidenceMatchType.EXACT,
        confirmed=True,
    )

    with db.connect(service._db_path) as conn:
        evidence_repo.create_evidence(conn, support, commit=False)
        evidence_repo.create_evidence(conn, contradict, commit=False)
        evidence_repo.create_evidence(conn, support2, commit=False)
        evidence_repo.create_verdict_log(conn, verdict, commit=False)
        evidence_repo.create_verdict_links(
            conn,
            [
                VerdictEvidenceLink(vid=verdict.vid, eid=support.eid, role=EvidenceRole.SUPPORT),
                VerdictEvidenceLink(vid=verdict.vid, eid=contradict.eid, role=EvidenceRole.CONTRADICT),
                VerdictEvidenceLink(vid=verdict.vid, eid=support2.eid, role=EvidenceRole.SUPPORT),
            ],
            commit=False,
        )
        conn.commit()

    previews = service.build_tag_path_preview_by_vid(project_id, [verdict.vid], limit_per_verdict=2)
    assert verdict.vid in previews
    assert previews[verdict.vid][0] == "character.hero.age"
    assert len(previews[verdict.vid]) == 2
