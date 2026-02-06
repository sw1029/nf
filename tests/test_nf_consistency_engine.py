from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo, evidence_repo, ignore_repo, schema_repo
from modules.nf_retrieval.fts.fts_index import index_chunks
from modules.nf_schema.chunking import build_chunks
from modules.nf_shared.protocol.dtos import (
    DocumentType,
    EvidenceMatchType,
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
