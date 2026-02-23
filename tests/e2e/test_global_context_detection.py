from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_orchestrator.services.job_service import JobServiceImpl
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import document_repo, evidence_repo, job_repo, project_repo
from modules.nf_shared.protocol.dtos import DocumentType, JobEventLevel, JobStatus, JobType, Verdict
from modules.nf_workers.runner import run_worker


def _seed_document(
    conn,
    *,
    tmp_path: Path,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    title: str,
    doc_type: DocumentType,
    text: str,
) -> None:
    path = tmp_path / f"{doc_id}_{snapshot_id}.txt"
    path.write_text(text, encoding="utf-8")
    checksum = docstore.checksum_text(text)
    document_repo.create_snapshot(
        conn,
        snapshot_id=snapshot_id,
        project_id=project_id,
        doc_id=doc_id,
        version=1,
        path=str(path),
        checksum=checksum,
    )
    document_repo.create_document(
        conn,
        doc_id=doc_id,
        project_id=project_id,
        title=title,
        doc_type=doc_type,
        path=str(path),
        head_snapshot_id=snapshot_id,
        checksum=checksum,
        version=1,
    )


@pytest.mark.e2e_large
def test_consistency_preflight_enables_global_context_detection(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    project_id = ""
    setting_doc_id = "doc-setting"
    setting_snapshot_id = "snap-setting"
    body_doc_id = "doc-body"
    body_snapshot_id = "snap-body"
    setting_text = "이름: 시로네\n나이: 14세\n직업: 노 클래스\n재능: 재능 없음"
    body_text = "시로네는 50세이며 9서클 마법사이자 천재였다."

    with db.connect(db_path) as conn:
        project = project_repo.create_project(conn, "P1", {})
        project_id = project.project_id
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=setting_doc_id,
            snapshot_id=setting_snapshot_id,
            title="설정",
            doc_type=DocumentType.SETTING,
            text=setting_text,
        )
        _seed_document(
            conn,
            tmp_path=tmp_path,
            project_id=project_id,
            doc_id=body_doc_id,
            snapshot_id=body_snapshot_id,
            title="본문",
            doc_type=DocumentType.EPISODE,
            text=body_text,
        )

    job_service = JobServiceImpl(db_path=db_path)
    baseline_job = job_service.submit(
        project_id,
        JobType.CONSISTENCY,
        {
            "input_doc_id": body_doc_id,
            "input_snapshot_id": body_snapshot_id,
            "range": {"start": 0, "end": len(body_text)},
            "preflight": {
                "ensure_ingest": False,
                "ensure_index_fts": False,
                "schema_scope": "latest_approved",
            },
        },
        {},
    )
    run_worker(db_path=db_path, poll_interval=0.01, max_jobs=1)

    with db.connect(db_path) as conn:
        baseline_status = job_repo.get_job(conn, baseline_job.job_id)
        baseline_verdicts = evidence_repo.list_verdicts(conn, project_id, input_doc_id=body_doc_id)
    assert baseline_status is not None
    assert baseline_status.status is JobStatus.SUCCEEDED
    assert baseline_verdicts
    assert baseline_verdicts[-1].verdict is Verdict.UNKNOWN
    before_count = len(baseline_verdicts)

    improved_job = job_service.submit(
        project_id,
        JobType.CONSISTENCY,
        {
            "input_doc_id": body_doc_id,
            "input_snapshot_id": "latest",
            "range": {"start": 0, "end": len(body_text)},
            "preflight": {
                "ensure_ingest": True,
                "ensure_index_fts": True,
                "schema_scope": "explicit_only",
            },
            "schema_scope": "explicit_only",
        },
        {},
    )
    run_worker(db_path=db_path, poll_interval=0.01, max_jobs=1)

    with db.connect(db_path) as conn:
        improved_status = job_repo.get_job(conn, improved_job.job_id)
        verdicts = evidence_repo.list_verdicts(conn, project_id, input_doc_id=body_doc_id)
        new_verdicts = verdicts[before_count:]
        assert new_verdicts
        assert any(v.verdict is Verdict.VIOLATE for v in new_verdicts)

        violate_verdict = next(v for v in new_verdicts if v.verdict is Verdict.VIOLATE)
        links = evidence_repo.list_verdict_evidence(conn, violate_verdict.vid)
        assert any(item["role"] == "CONTRADICT" for item in links)

        events = job_repo.list_job_events(conn, improved_job.job_id)
        completion = next(
            event
            for _, event in events
            if event.level is JobEventLevel.INFO and event.message == "consistency complete"
        )
    assert improved_status is not None
    assert improved_status.status is JobStatus.SUCCEEDED
    assert completion.payload is not None
    for key in (
        "elapsed_ms",
        "rss_mb_peak",
        "claims_processed",
        "chunks_processed",
        "rows_scanned",
        "shards_loaded",
    ):
        assert key in completion.payload
