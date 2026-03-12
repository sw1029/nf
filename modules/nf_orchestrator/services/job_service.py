from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import job_repo
from modules.nf_shared.protocol.dtos import Job, JobEvent, JobEventLevel, JobType


class JobServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def submit(
        self,
        project_id: str,
        job_type: JobType,
        inputs: dict[str, Any],
        params: dict[str, Any],
        *,
        priority: int = 100,
    ) -> Job:
        def _action(conn):  # noqa: ANN001
            job = job_repo.create_job(conn, project_id, job_type, inputs, params, priority=priority)
            job_repo.add_job_event(
                conn,
                job.job_id,
                JobEventLevel.INFO,
                f"잡 {job.job_id} 큐 등록",
                progress=0.0,
                metrics={"job_type": job_type.value},
            )
            return job
        return db.run_with_retry(self._db_path, _action)

    def cancel(self, job_id: str) -> Job | None:
        def _action(conn):  # noqa: ANN001
            job = job_repo.cancel_job(conn, job_id)
            if job is not None:
                job_repo.add_job_event(
                    conn,
                    job_id,
                    JobEventLevel.WARN,
                    "잡 취소됨",
                    progress=1.0,
                )
            return job
        return db.run_with_retry(self._db_path, _action)

    def get(self, job_id: str) -> Job | None:
        return db.run_with_retry(self._db_path, lambda conn: job_repo.get_job(conn, job_id))

    def list(self, *, project_id: str | None = None, limit: int = 20) -> list[Job]:
        return db.run_with_retry(
            self._db_path,
            lambda conn: job_repo.list_jobs(conn, project_id=project_id, limit=limit),
        )

    def get_payloads(self, job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        return db.run_with_retry(self._db_path, lambda conn: job_repo.get_job_payloads(conn, job_id))

    def set_result(self, job_id: str, result: dict[str, Any] | None) -> None:
        db.run_with_retry(self._db_path, lambda conn: job_repo.set_job_result(conn, job_id, result=result))

    def list_events(self, job_id: str, *, after_seq: int = 0) -> list[tuple[int, JobEvent]]:
        return db.run_with_retry(
            self._db_path,
            lambda conn: job_repo.list_job_events(conn, job_id, after_seq=after_seq),
        )
