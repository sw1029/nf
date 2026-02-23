from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_orchestrator.services.query_service import QueryServiceImpl
from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import evidence_repo, schema_repo
from modules.nf_shared.protocol.dtos import (
    EvidenceRole,
    EvidenceMatchType,
    FactSource,
    FactStatus,
    ReliabilityBreakdown,
    SchemaFact,
    SchemaLayer,
    Span,
    Verdict,
    VerdictEvidenceLink,
    VerdictLog,
)


@pytest.mark.unit
def test_get_verdict_detail_includes_fact_paths(tmp_path: Path) -> None:
    service = QueryServiceImpl(db_path=tmp_path / "orchestrator.db")
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    evidence = evidence_repo.new_evidence(
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        chunk_id="chunk-1",
        section_path="body",
        tag_path="character.hero.age",
        snippet_text="hero is 20",
        span_start=0,
        span_end=10,
        fts_score=0.1,
        match_type=EvidenceMatchType.EXACT,
        confirmed=True,
    )
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
            evidence_count=1,
            confirmed_evidence=1,
            model_score=0.0,
        ),
        whitelist_applied=False,
        created_at="2026-02-22T00:00:00Z",
        unknown_reasons=(),
    )
    fact = SchemaFact(
        fact_id="fact-1",
        project_id=project_id,
        schema_ver="schema-1",
        layer=SchemaLayer.EXPLICIT,
        entity_id="entity-hero",
        tag_path="character.hero.age",
        value=20,
        evidence_eid=evidence.eid,
        confidence=1.0,
        source=FactSource.USER,
        status=FactStatus.APPROVED,
    )

    with db.connect(service._db_path) as conn:
        evidence_repo.create_evidence(conn, evidence, commit=False)
        evidence_repo.create_verdict_log(conn, verdict, commit=False)
        evidence_repo.create_verdict_links(
            conn,
            [VerdictEvidenceLink(vid=verdict.vid, eid=evidence.eid, role=EvidenceRole.CONTRADICT)],
            commit=False,
        )
        schema_repo.create_schema_fact(conn, fact, commit=False)
        conn.commit()

    detail = service.get_verdict_detail(project_id, verdict.vid)
    assert detail is not None
    fact_paths = detail.get("fact_paths")
    assert isinstance(fact_paths, list)
    assert fact_paths
    first = fact_paths[0]
    assert first["source"] == "schema_fact"
    assert first["tag_path"] == "character.hero.age"
    assert first["entity_id"] == "entity-hero"
