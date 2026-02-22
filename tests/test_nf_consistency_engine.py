from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from modules.nf_consistency import engine as consistency_engine
from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo, evidence_repo, ignore_repo, schema_repo
from modules.nf_retrieval.fts.fts_index import index_chunks
from modules.nf_schema.chunking import build_chunks
from modules.nf_shared.protocol.dtos import (
    DocumentType,
    EvidenceMatchType,
    EvidenceRole,
    FactSource,
    FactStatus,
    SchemaFact,
    SchemaLayer,
    Verdict,
)


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
    chunks = build_chunks(project_id=project_id, doc_id=doc_id, snapshot_id=snapshot_id, text=text)
    index_chunks(conn, snapshot_id=snapshot_id, chunks=chunks, text=text)


def _seed_schema_fact(
    conn,
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    schema_ver: str,
    tag_path: str,
    value: object,
) -> None:
    ev = evidence_repo.new_evidence(
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        chunk_id=None,
        section_path="seed",
        tag_path=tag_path,
        snippet_text="seed",
        span_start=0,
        span_end=0,
        fts_score=0.0,
        match_type=EvidenceMatchType.EXACT,
        confirmed=True,
    )
    evidence_repo.create_evidence(conn, ev)
    fact = SchemaFact(
        fact_id=str(uuid.uuid4()),
        project_id=project_id,
        schema_ver=schema_ver,
        layer=SchemaLayer.EXPLICIT,
        entity_id=None,
        tag_path=tag_path,
        value=value,
        evidence_eid=ev.eid,
        confidence=1.0,
        source=FactSource.USER,
        status=FactStatus.APPROVED,
    )
    schema_repo.create_schema_fact(conn, fact)


@pytest.mark.unit
def test_consistency_engine_unknown_when_no_matching_facts(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "나이 11살"

    with db.connect(db_path) as conn:
        _seed_document(conn, tmp_path=tmp_path, project_id=project_id, doc_id=doc_id, snapshot_id=snapshot_id, text=text)

    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "schema_ver": "",
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN


@pytest.mark.unit
def test_consistency_engine_ok_when_fact_matches(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    schema_ver = "v1"
    text = "나이 11살"

    with db.connect(db_path) as conn:
        _seed_document(conn, tmp_path=tmp_path, project_id=project_id, doc_id=doc_id, snapshot_id=snapshot_id, text=text)
        schema_repo.create_schema_version(
            conn,
            project_id=project_id,
            source_snapshot_id=snapshot_id,
            schema_ver=schema_ver,
        )
        _seed_schema_fact(
            conn,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            schema_ver=schema_ver,
            tag_path="인물/나이",
            value=11,
        )

    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "schema_ver": schema_ver,
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.OK


@pytest.mark.unit
def test_consistency_engine_violate_when_fact_mismatches(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    schema_ver = "v1"
    text = "나이 11살"

    with db.connect(db_path) as conn:
        _seed_document(conn, tmp_path=tmp_path, project_id=project_id, doc_id=doc_id, snapshot_id=snapshot_id, text=text)
        schema_repo.create_schema_version(
            conn,
            project_id=project_id,
            source_snapshot_id=snapshot_id,
            schema_ver=schema_ver,
        )
        _seed_schema_fact(
            conn,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            schema_ver=schema_ver,
            tag_path="인물/나이",
            value=10,
        )

    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "schema_ver": schema_ver,
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.VIOLATE


@pytest.mark.unit
def test_consistency_engine_skips_ignored_claims(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "나이 11살"

    with db.connect(db_path) as conn:
        _seed_document(conn, tmp_path=tmp_path, project_id=project_id, doc_id=doc_id, snapshot_id=snapshot_id, text=text)
        ignore_repo.create_ignore_item(
            conn,
            project_id=project_id,
            claim_fingerprint=f"sha256:{hashlib.sha256(text.strip().encode('utf-8')).hexdigest()}",
            scope=doc_id,
            kind="CONSISTENCY",
            note="suppress",
        )

    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "schema_ver": "",
        }
    )

    assert verdicts == []


@pytest.mark.unit
def test_consistency_engine_detects_natural_language_age_violation_and_links_schema_evidence(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    setting_doc_id = "doc-setting"
    setting_snapshot_id = "snap-setting"
    body_doc_id = "doc-body"
    body_snapshot_id = "snap-body"
    schema_ver = "v1"
    setting_text = "이름: 시로네\n나이: 12세"
    body_text = "시로네는 40살의 중년 남성이다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=setting_doc_id,
            snapshot_id=setting_snapshot_id,
            text=setting_text,
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=body_doc_id,
            snapshot_id=body_snapshot_id,
            text=body_text,
        )
        schema_repo.create_schema_version(
            conn,
            project_id=project_id,
            source_snapshot_id=setting_snapshot_id,
            schema_ver=schema_ver,
        )
        _seed_schema_fact(
            conn,
            project_id=project_id,
            doc_id=setting_doc_id,
            snapshot_id=setting_snapshot_id,
            schema_ver=schema_ver,
            tag_path="설정/인물/주인공/나이",
            value=12,
        )

    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": body_doc_id,
            "input_snapshot_id": body_snapshot_id,
            "range": {"start": 0, "end": len(body_text)},
            "schema_ver": schema_ver,
        }
    )

    assert verdicts
    violate_verdict = next((item for item in verdicts if item.verdict is Verdict.VIOLATE), None)
    assert violate_verdict is not None

    with db.connect(db_path) as conn:
        linked = evidence_repo.list_verdict_evidence(conn, violate_verdict.vid)

    assert linked, "verdict should keep linked evidence"
    assert any(
        item["role"] == "CONTRADICT" and item["evidence"].doc_id == setting_doc_id
        for item in linked
    )


class _DummyEvidence:
    def __init__(self, eid: str) -> None:
        self.eid = eid


@pytest.mark.unit
def test_build_verdict_links_cap_limits_total_links() -> None:
    links = consistency_engine._build_verdict_links(
        verdict_id="vid-1",
        evidences=[_DummyEvidence("e1"), _DummyEvidence("e2"), _DummyEvidence("e3")],
        fact_links=[("f1", EvidenceRole.CONTRADICT), ("f2", EvidenceRole.SUPPORT)],
        policy="cap",
        cap=2,
    )
    assert len(links) == 2
    assert [item.eid for item in links] == ["e1", "e2"]


@pytest.mark.unit
def test_build_verdict_links_contradict_only_filters_non_contradict_roles() -> None:
    links = consistency_engine._build_verdict_links(
        verdict_id="vid-2",
        evidences=[_DummyEvidence("e1"), _DummyEvidence("e2")],
        fact_links=[
            ("f1", EvidenceRole.SUPPORT),
            ("f2", EvidenceRole.CONTRADICT),
            ("f3", EvidenceRole.CONTRADICT),
        ],
        policy="contradict_only",
        cap=10,
    )
    assert [item.eid for item in links] == ["f2", "f3"]
    assert all(item.role is EvidenceRole.CONTRADICT for item in links)


@pytest.mark.unit
def test_resolve_evidence_link_options_invalid_values_fallback_to_defaults() -> None:
    policy, cap = consistency_engine._resolve_evidence_link_options(
        {"evidence_link_policy": "invalid", "evidence_link_cap": 0}
    )
    assert policy == "full"
    assert cap == 1


@pytest.mark.unit
def test_resolve_self_evidence_options_defaults() -> None:
    exclude, scope = consistency_engine._resolve_self_evidence_options({})
    assert exclude is True
    assert scope == "range"


@pytest.mark.unit
def test_filter_self_evidence_results_range_scope_filters_overlap_only() -> None:
    results = [
        {
            "score": 0.1,
            "evidence": {"doc_id": "doc-1", "span_start": 10, "span_end": 20, "chunk_id": "c1"},
        },
        {
            "score": 0.2,
            "evidence": {"doc_id": "doc-1", "span_start": 25, "span_end": 30, "chunk_id": "c2"},
        },
        {
            "score": 0.3,
            "evidence": {"doc_id": "doc-2", "span_start": 12, "span_end": 18, "chunk_id": "c3"},
        },
    ]
    kept, removed = consistency_engine._filter_self_evidence_results(
        results,
        input_doc_id="doc-1",
        scope="range",
        claim_abs_start=12,
        claim_abs_end=18,
        range_start=None,
        range_end=None,
    )
    assert removed == 1
    kept_chunks = [item["evidence"]["chunk_id"] for item in kept]
    assert kept_chunks == ["c2", "c3"]


@pytest.mark.unit
def test_filter_self_evidence_results_doc_scope_filters_same_doc() -> None:
    results = [
        {
            "score": 0.1,
            "evidence": {"doc_id": "doc-1", "span_start": 10, "span_end": 20, "chunk_id": "c1"},
        },
        {
            "score": 0.2,
            "evidence": {"doc_id": "doc-2", "span_start": 25, "span_end": 30, "chunk_id": "c2"},
        },
    ]
    kept, removed = consistency_engine._filter_self_evidence_results(
        results,
        input_doc_id="doc-1",
        scope="doc",
        claim_abs_start=12,
        claim_abs_end=18,
        range_start=None,
        range_end=None,
    )
    assert removed == 1
    assert len(kept) == 1
    assert kept[0]["evidence"]["doc_id"] == "doc-2"
