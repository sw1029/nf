from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.nf_consistency import engine as consistency_engine
from modules.nf_consistency.engine import ConsistencyEngineImpl
from modules.nf_consistency.extractors.pipeline import ExtractionPipeline
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo, evidence_repo, ignore_repo, schema_repo
from modules.nf_retrieval.fts.fts_index import index_chunks
from modules.nf_schema.chunking import build_chunks
from modules.nf_shared.config import Settings
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


@pytest.mark.unit
def test_extract_claims_broadens_entity_bound_claim_span_to_full_segment() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)
    text = "재능: 천재"

    claims = consistency_engine._extract_claims(text, pipeline=pipeline, stats={})

    assert len(claims) == 1
    assert claims[0]["slot_key"] == "talent"
    assert claims[0]["claim_text"] == text
    assert claims[0]["claim_start"] == 0
    assert claims[0]["claim_end"] == len(text)


@pytest.mark.unit
def test_extract_claims_broadens_place_claim_span_to_full_segment() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)
    text = "장소는 사천성 남단 덕창(德昌)이었다."

    claims = consistency_engine._extract_claims(text, pipeline=pipeline, stats={})

    assert len(claims) == 1
    assert claims[0]["slot_key"] == "place"
    assert claims[0]["claim_text"] == text


@pytest.mark.unit
def test_extract_claims_keeps_time_claim_span_compact() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)
    text = "시간은 12:30이다."

    claims = consistency_engine._extract_claims(text, pipeline=pipeline, stats={})

    assert len(claims) == 1
    assert claims[0]["slot_key"] == "time"
    assert claims[0]["claim_text"] == "12:30"


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
    entity_id: str | None = None,
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
        entity_id=entity_id,
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
def test_consistency_engine_entity_unresolved_when_only_entity_bound_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    schema_ver = "v1"
    text = "그의 직업은 마법사다."

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
            tag_path="설정/인물/직업",
            value="마법사",
            entity_id="entity-siro",
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": len(text),
                "segment_text": text,
                "claim_start": 0,
                "claim_end": len(text),
                "claim_text": text,
                "slots": {"job": "마법사"},
                "slot_key": "job",
                "slot_confidence": 1.0,
            }
        ],
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
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert "ENTITY_UNRESOLVED" in verdicts[0].unknown_reasons


@pytest.mark.unit
def test_consistency_engine_adds_numeric_conflict_unknown_reason_for_string_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    schema_ver = "v1"
    text = "그의 직업은 12기 마법사다."

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
            tag_path="설정/인물/직업",
            value="13기 마법사",
            entity_id="entity-siro",
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": len(text),
                "segment_text": text,
                "claim_start": 0,
                "claim_end": len(text),
                "claim_text": text,
                "slots": {"job": "12기 마법사"},
                "slot_key": "job",
                "slot_confidence": 1.0,
            }
        ],
    )

    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "schema_ver": schema_ver,
            "filters": {"entity_id": "entity-siro"},
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert "NUMERIC_CONFLICT" in verdicts[0].unknown_reasons


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


@pytest.mark.unit
def test_consistency_engine_detects_natural_language_job_match_without_monkeypatch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    setting_doc_id = "doc-setting"
    setting_snapshot_id = "snap-setting"
    body_doc_id = "doc-body"
    body_snapshot_id = "snap-body"
    schema_ver = "v1"
    setting_text = "직업: 마법사"
    body_text = "그의 직업은 마법사다."

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
            tag_path="설정/인물/직업",
            value="마법사",
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
    assert any(item.verdict is Verdict.OK for item in verdicts)


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
    assert scope == "claim"


@pytest.mark.unit
def test_filter_self_evidence_results_claim_scope_uses_claim_span_not_range() -> None:
    results = [
        {
            "score": 0.1,
            "evidence": {"doc_id": "doc-1", "span_start": 30, "span_end": 35, "chunk_id": "c1"},
        }
    ]
    kept, removed = consistency_engine._filter_self_evidence_results(
        results,
        input_doc_id="doc-1",
        scope="claim",
        claim_abs_start=10,
        claim_abs_end=20,
        range_start=0,
        range_end=100,
    )
    assert removed == 0
    assert len(kept) == 1


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


@pytest.mark.unit
def test_resolve_excluded_self_fact_eids_bulk_join_returns_exact_matches(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    expected: set[str] = set()

    with db.connect(db_path) as conn:
        facts: list[SimpleNamespace] = []
        for idx in range(320):
            eid_doc_id = "doc-self" if idx % 2 == 0 else "doc-other"
            ev = evidence_repo.new_evidence(
                project_id="project-1",
                doc_id=eid_doc_id,
                snapshot_id="snap-1",
                chunk_id=None,
                section_path="seed",
                tag_path="설정/인물/주인공/나이",
                snippet_text=f"seed-{idx}",
                span_start=0,
                span_end=1,
                fts_score=0.0,
                match_type=EvidenceMatchType.EXACT,
                confirmed=True,
            )
            evidence_repo.create_evidence(conn, ev, commit=False)
            source = FactSource.AUTO if idx < 300 else FactSource.USER
            status = FactStatus.PROPOSED if idx % 5 != 0 else FactStatus.APPROVED
            facts.append(
                SimpleNamespace(
                    evidence_eid=ev.eid,
                    source=source,
                    status=status,
                )
            )
            if eid_doc_id == "doc-self" and source is FactSource.AUTO and status is FactStatus.PROPOSED:
                expected.add(ev.eid)
        conn.commit()
        excluded = consistency_engine._resolve_excluded_self_fact_eids(
            conn,
            facts=facts,
            input_doc_id="doc-self",
        )

    assert excluded == expected


@pytest.mark.unit
def test_verification_loop_breaks_on_stagnation_and_counts_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "시로는 오늘 북부 성채로 이동했다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": len(text),
                "segment_text": text,
                "claim_start": 0,
                "claim_end": len(text),
                "claim_text": text,
                "slots": {"place": "북부 성채"},
                "slot_key": "place",
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", lambda _conn, _req: [])
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=False, vector_index_mode="DISABLED"),
    )

    stats: dict[str, object] = {}
    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "schema_ver": "",
            "stats": stats,
            "verification_loop": {
                "enabled": True,
                "max_rounds": 2,
                "round_timeout_ms": 250,
            },
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert int(stats.get("verification_loop_trigger_count", 0)) == 1
    assert int(stats.get("verification_loop_attempted_rounds_total", 0)) >= 1
    assert int(stats.get("verification_loop_stagnation_break_count", 0)) >= 1
    assert float(stats.get("verification_loop_round_elapsed_ms_sum", 0.0)) >= 0.0
    assert isinstance(stats.get("verification_loop_round_elapsed_ms_samples"), list)
    assert isinstance(stats.get("verification_loop_candidate_growth_samples"), list)
    exit_reason_counts = stats.get("verification_loop_exit_reason_counts")
    assert isinstance(exit_reason_counts, dict)
    assert any(key in exit_reason_counts for key in ("no_results_fts", "no_results_after_refill", "candidate_stagnation"))


@pytest.mark.unit
def test_consistency_engine_treats_irrelevant_affiliation_hits_as_no_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "소속: 사도련 백전귀(百戰鬼)"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": len(text),
                "segment_text": text,
                "claim_start": 4,
                "claim_end": 7,
                "claim_text": "사도련",
                "slots": {"affiliation": "사도련"},
                "slot_key": "affiliation",
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.fts_search",
        lambda _conn, _req: [
            {
                "source": "fts",
                "score": 0.11,
                "evidence": {
                    "doc_id": "doc-ref-1",
                    "snapshot_id": "snap-ref",
                    "chunk_id": "chunk-ref-1",
                    "section_path": "body",
                    "tag_path": "",
                    "snippet_text": "완전히 무관한 장면이다.",
                    "span_start": 0,
                    "span_end": 12,
                    "fts_score": 0.11,
                    "match_type": "EXACT",
                    "confirmed": False,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=False, vector_index_mode="DISABLED"),
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

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert "NO_EVIDENCE" in verdicts[0].unknown_reasons
    assert "CONFLICTING_EVIDENCE" not in verdicts[0].unknown_reasons


@pytest.mark.unit
def test_consistency_engine_accepts_explicit_affiliation_corroboration_from_retrieved_snippet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "소속: 사도련 백전귀(百戰鬼)"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": len(text),
                "segment_text": text,
                "claim_start": 4,
                "claim_end": 7,
                "claim_text": "사도련",
                "slots": {"affiliation": "사도련"},
                "slot_key": "affiliation",
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.fts_search",
        lambda _conn, _req: [
            {
                "source": "fts",
                "score": 0.31,
                "evidence": {
                    "doc_id": "doc-ref-1",
                    "snapshot_id": "snap-ref",
                    "chunk_id": "chunk-ref-1",
                    "section_path": "body",
                    "tag_path": "",
                    "snippet_text": "그는 사도련의 백전귀였다.",
                    "span_start": 0,
                    "span_end": 14,
                    "fts_score": 0.31,
                    "match_type": "EXACT",
                    "confirmed": False,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=False, vector_index_mode="DISABLED"),
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

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.OK
    assert verdicts[0].unknown_reasons == ()


@pytest.mark.unit
def test_consistency_engine_accepts_title_affiliation_corroboration_without_full_anchor_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "소속: 라인시스 제국 제1황녀"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": len(text),
                "segment_text": text,
                "claim_start": 4,
                "claim_end": 11,
                "claim_text": "라인시스 제국",
                "slots": {"affiliation": "라인시스 제국"},
                "slot_key": "affiliation",
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.fts_search",
        lambda _conn, _req: [
            {
                "source": "fts",
                "score": 0.31,
                "evidence": {
                    "doc_id": "doc-ref-1",
                    "snapshot_id": "snap-ref",
                    "chunk_id": "chunk-ref-1",
                    "section_path": "body",
                    "tag_path": "",
                    "snippet_text": "그녀는 라인시스의 제1황녀였다.",
                    "span_start": 0,
                    "span_end": 17,
                    "fts_score": 0.31,
                    "match_type": "EXACT",
                    "confirmed": False,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=False, vector_index_mode="DISABLED"),
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

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.OK
    assert verdicts[0].unknown_reasons == ()


@pytest.mark.unit
def test_consistency_engine_excludes_same_doc_hits_for_explicit_profile_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "소속: 사도련 백전귀(百戰鬼)\n사도련은 들썩거린다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": 17,
                "segment_text": "소속: 사도련 백전귀(百戰鬼)",
                "claim_start": 4,
                "claim_end": 7,
                "claim_text": "사도련",
                "slots": {"affiliation": "사도련"},
                "slot_key": "affiliation",
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.fts_search",
        lambda _conn, _req: [
            {
                "source": "fts",
                "score": 0.11,
                "evidence": {
                    "doc_id": doc_id,
                    "snapshot_id": snapshot_id,
                    "chunk_id": "chunk-ref-1",
                    "section_path": "body",
                    "tag_path": "",
                    "snippet_text": "사도련은 들썩거린다.",
                    "span_start": 18,
                    "span_end": len(text),
                    "fts_score": 0.11,
                    "match_type": "EXACT",
                    "confirmed": False,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=False, vector_index_mode="DISABLED"),
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

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert "NO_EVIDENCE" in verdicts[0].unknown_reasons
    assert "CONFLICTING_EVIDENCE" not in verdicts[0].unknown_reasons


@pytest.mark.unit
def test_consistency_engine_treats_unlinked_retrieval_hits_as_no_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "448"

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": len(text),
                "segment_text": text,
                "claim_start": 0,
                "claim_end": len(text),
                "claim_text": text,
                "slots": {"age": 448},
                "slot_key": "age",
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.fts_search",
        lambda _conn, _req: [
            {
                "source": "fts",
                "score": 0.11,
                "evidence": {
                    "doc_id": "doc-ref-1",
                    "snapshot_id": "snap-ref",
                    "chunk_id": "chunk-ref-1",
                    "section_path": "body",
                    "tag_path": "",
                    "snippet_text": "완전히 다른 서술이다.",
                    "span_start": 0,
                    "span_end": 10,
                    "fts_score": 0.11,
                    "match_type": "EXACT",
                    "confirmed": False,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=False, vector_index_mode="DISABLED"),
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

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert "NO_EVIDENCE" in verdicts[0].unknown_reasons
    assert "CONFLICTING_EVIDENCE" not in verdicts[0].unknown_reasons


@pytest.mark.unit
def test_verification_loop_timeout_before_second_round_records_exit_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = "project-1"
    doc_id = "doc-1"
    snapshot_id = "snap-1"
    text = "시로는 오늘 북부 성채로 이동했다."

    with db.connect(db_path) as conn:
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=doc_id,
            snapshot_id=snapshot_id,
            text=text,
        )

    monkeypatch.setattr(
        "modules.nf_consistency.engine._extract_claims",
        lambda *_args, **_kwargs: [
            {
                "segment_start": 0,
                "segment_end": len(text),
                "segment_text": text,
                "claim_start": 0,
                "claim_end": len(text),
                "claim_text": text,
                "slots": {"place": "북부 성채"},
                "slot_key": "place",
                "slot_confidence": 1.0,
            }
        ],
    )
    monkeypatch.setattr(
        "modules.nf_consistency.engine.load_config",
        lambda: Settings(enable_layer3_model=False, vector_index_mode="DISABLED"),
    )

    call_state = {"count": 0}

    def fake_fts_search(_conn, _req):  # noqa: ANN001
        idx = call_state["count"]
        call_state["count"] += 1
        if idx == 0:
            return [
                {
                    "source": "fts",
                    "score": 0.11,
                    "evidence": {
                        "doc_id": "doc-ref-1",
                        "snapshot_id": "snap-ref",
                        "chunk_id": "chunk-ref-1",
                        "section_path": "body",
                        "tag_path": "",
                        "snippet_text": "reference-one",
                        "span_start": 0,
                        "span_end": 8,
                        "fts_score": 0.11,
                        "match_type": "EXACT",
                        "confirmed": False,
                    },
                }
            ]
        if idx == 1:
            time.sleep(0.01)
            return [
                {
                    "source": "fts",
                    "score": 0.12,
                    "evidence": {
                        "doc_id": "doc-ref-2",
                        "snapshot_id": "snap-ref",
                        "chunk_id": "chunk-ref-2",
                        "section_path": "body",
                        "tag_path": "",
                        "snippet_text": "reference-two",
                        "span_start": 0,
                        "span_end": 8,
                        "fts_score": 0.12,
                        "match_type": "EXACT",
                        "confirmed": False,
                    },
                }
            ]
        return []

    monkeypatch.setattr("modules.nf_consistency.engine.fts_search", fake_fts_search)

    stats: dict[str, object] = {}
    engine = ConsistencyEngineImpl(db_path=db_path)
    verdicts = engine.run(
        {
            "project_id": project_id,
            "input_doc_id": doc_id,
            "input_snapshot_id": snapshot_id,
            "range": {"start": 0, "end": len(text)},
            "schema_ver": "",
            "stats": stats,
            "verification_loop": {
                "enabled": True,
                "max_rounds": 2,
                "round_timeout_ms": 1,
            },
        }
    )

    assert len(verdicts) == 1
    assert verdicts[0].verdict is Verdict.UNKNOWN
    assert int(stats.get("verification_loop_trigger_count", 0)) == 1
    assert int(stats.get("verification_loop_attempted_rounds_total", 0)) == 1
    assert int(stats.get("verification_loop_rounds_total", 0)) == 1
    assert int(stats.get("verification_loop_timeout_count", 0)) == 1
    exit_reason_counts = stats.get("verification_loop_exit_reason_counts")
    assert isinstance(exit_reason_counts, dict)
    assert int(exit_reason_counts.get("timeout_before_round", 0)) == 1
    assert float(stats.get("verification_loop_round_elapsed_ms_sum", 0.0)) > 0.0
    assert int(stats.get("verification_loop_candidate_growth_total", 0)) >= 1
