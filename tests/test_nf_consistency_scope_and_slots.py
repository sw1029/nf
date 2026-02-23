from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo, evidence_repo, schema_repo
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
    doc_type: DocumentType = DocumentType.EPISODE,
    title: str = "Doc",
    metadata: dict | None = None,
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
        title=title,
        doc_type=doc_type,
        path=str(text_path),
        head_snapshot_id=snapshot_id,
        checksum=checksum,
        version=1,
        metadata=metadata or {},
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
    status: FactStatus,
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
        status=status,
    )
    schema_repo.create_schema_fact(conn, fact)


@pytest.mark.unit
def test_consistency_handles_age_se_format_and_detects_violation(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    setting_doc_id = "doc-setting"
    body_doc_id = "doc-body"
    setting_snapshot_id = "snap-setting"
    body_snapshot_id = "snap-body"
    schema_ver = "v1"
    tag_age = "설정/인물/주인공/나이"
    setting_text = "이름: 시로네\n나이: 14세"
    body_text = "시로네는 올해 50세가 되었다."

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
            tag_path=tag_age,
            value=14,
            status=FactStatus.APPROVED,
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
    assert any(item.verdict in {Verdict.VIOLATE, Verdict.UNKNOWN} for item in verdicts)

    with db.connect(db_path) as conn:
        linked = evidence_repo.list_verdict_evidence(conn, verdicts[0].vid)
    assert any(item["role"] == "CONTRADICT" for item in linked)


@pytest.mark.unit
def test_consistency_detects_job_and_talent_conflicts(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    setting_doc_id = "doc-setting"
    body_doc_id = "doc-body"
    setting_snapshot_id = "snap-setting"
    body_snapshot_id = "snap-body"
    schema_ver = "v1"
    tag_job = "설정/인물/주인공/직업"
    tag_talent = "설정/인물/주인공/재능"
    setting_text = "직업: 노 클래스\n재능: 재능 없음"
    body_text = "그는 9서클 마법사이자 천재였다."

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
            tag_path=tag_job,
            value="노 클래스",
            status=FactStatus.APPROVED,
        )
        _seed_schema_fact(
            conn,
            project_id=project_id,
            doc_id=setting_doc_id,
            snapshot_id=setting_snapshot_id,
            schema_ver=schema_ver,
            tag_path=tag_talent,
            value="재능 없음",
            status=FactStatus.APPROVED,
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
    assert any(item.verdict in {Verdict.VIOLATE, Verdict.UNKNOWN} for item in verdicts)


@pytest.mark.unit
def test_consistency_schema_scope_explicit_only_reads_proposed_explicit_facts(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    setting_doc_id = "doc-setting"
    body_doc_id = "doc-body"
    setting_snapshot_id = "snap-setting"
    body_snapshot_id = "snap-body"
    schema_ver = "v1"
    tag_age = "설정/인물/주인공/나이"
    setting_text = "나이: 14세"
    body_text = "시로네의 나이는 50세였다."

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
            tag_path=tag_age,
            value=14,
            status=FactStatus.PROPOSED,
        )

    engine = ConsistencyEngineImpl(db_path=db_path)
    latest_only = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": body_doc_id,
            "input_snapshot_id": body_snapshot_id,
            "range": {"start": 0, "end": len(body_text)},
            "schema_ver": schema_ver,
            "schema_scope": "latest_approved",
        }
    )
    explicit_only = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": body_doc_id,
            "input_snapshot_id": body_snapshot_id,
            "range": {"start": 0, "end": len(body_text)},
            "schema_ver": schema_ver,
            "schema_scope": "explicit_only",
        }
    )

    assert len(latest_only) == 1
    assert latest_only[0].verdict is Verdict.UNKNOWN
    assert len(explicit_only) == 1
    assert explicit_only[0].verdict is Verdict.VIOLATE


@pytest.mark.unit
def test_consistency_default_doc_scope_limits_vector_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    input_doc_id = "doc-episode-20"
    input_snapshot_id = "snap-episode-20"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=input_doc_id,
            snapshot_id=input_snapshot_id,
            text="hero line",
            doc_type=DocumentType.EPISODE,
            title="Episode 20",
            metadata={"episode_no": 20},
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-episode-25",
            snapshot_id="snap-episode-25",
            text="near episode",
            doc_type=DocumentType.EPISODE,
            title="Episode 25",
            metadata={"episode_no": 25},
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-episode-99",
            snapshot_id="snap-episode-99",
            text="far episode",
            doc_type=DocumentType.EPISODE,
            title="Episode 99",
            metadata={"episode_no": 99},
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-setting",
            snapshot_id="snap-setting",
            text="world setting",
            doc_type=DocumentType.SETTING,
            title="Setting",
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-char",
            snapshot_id="snap-char",
            text="character profile",
            doc_type=DocumentType.CHAR,
            title="Character",
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id="doc-plot",
            snapshot_id="snap-plot",
            text="plot timeline",
            doc_type=DocumentType.PLOT,
            title="Plot",
        )

    monkeypatch.setattr("modules.nf_consistency.engine.select_model", lambda purpose: None)
    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda _text, pipeline=None, stats=None: [
            {
                "claim_text": "hero line",
                "segment_text": "hero line",
                "claim_start": 0,
                "claim_end": 9,
                "slots": {"relation": "hero"},
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", lambda _conn, _req: [])

    captured_filters: list[dict[str, object]] = []

    def fake_vector_search(req):  # noqa: ANN001
        filters = req.get("filters")
        if isinstance(filters, dict):
            captured_filters.append(dict(filters))
        return []

    monkeypatch.setattr("modules.nf_consistency.engine.vector_search", fake_vector_search)

    engine = ConsistencyEngineImpl(db_path=db_path)
    engine.run(
        {
            "project_id": project_id,
            "input_doc_id": input_doc_id,
            "input_snapshot_id": input_snapshot_id,
            "range": {"start": 0, "end": 9},
        }
    )

    assert captured_filters
    doc_ids = captured_filters[0].get("doc_ids")
    assert isinstance(doc_ids, list)
    assert input_doc_id in doc_ids
    assert "doc-episode-25" in doc_ids
    assert "doc-setting" in doc_ids
    assert "doc-char" in doc_ids
    assert "doc-plot" in doc_ids
    assert "doc-episode-99" not in doc_ids


@pytest.mark.unit
def test_consistency_vector_fallback_preserves_requested_doc_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    input_doc_id = "doc-body"
    input_snapshot_id = "snap-body"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=input_doc_id,
            snapshot_id=input_snapshot_id,
            text="hero line",
        )

    monkeypatch.setattr("modules.nf_consistency.engine.select_model", lambda purpose: None)
    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda _text, pipeline=None, stats=None: [
            {
                "claim_text": "hero line",
                "segment_text": "hero line",
                "claim_start": 0,
                "claim_end": 9,
                "slots": {"relation": "hero"},
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", lambda _conn, _req: [])

    captured_filters: list[dict[str, object]] = []

    def fake_vector_search(req):  # noqa: ANN001
        filters = req.get("filters")
        if isinstance(filters, dict):
            captured_filters.append(dict(filters))
        return []

    monkeypatch.setattr("modules.nf_consistency.engine.vector_search", fake_vector_search)

    engine = ConsistencyEngineImpl(db_path=db_path)
    engine.run(
        {
            "project_id": project_id,
            "input_doc_id": input_doc_id,
            "input_snapshot_id": input_snapshot_id,
            "range": {"start": 0, "end": 9},
            "filters": {"doc_ids": ["doc-custom"]},
        }
    )

    assert captured_filters
    assert captured_filters[0].get("doc_ids") == ["doc-custom"]
