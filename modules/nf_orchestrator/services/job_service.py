from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import job_repo
from modules.nf_shared.protocol.dtos import Job, JobEvent, JobEventLevel, JobType


class JobServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def submit(self, project_id: str, job_type: JobType, inputs: dict[str, Any], params: dict[str, Any]) -> Job:
        with db.connect(self._db_path) as conn:
            job = job_repo.create_job(conn, project_id, job_type, inputs, params)
            job_repo.add_job_event(
                conn,
                job.job_id,
                JobEventLevel.INFO,
                f"잡 {job.job_id} 큐 등록",
                progress=0.0,
                metrics={"job_type": job_type.value},
            )
            return job

    def cancel(self, job_id: str) -> Job | None:
        with db.connect(self._db_path) as conn:
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

    def get(self, job_id: str) -> Job | None:
        with db.connect(self._db_path) as conn:
            return job_repo.get_job(conn, job_id)

    def list_events(self, job_id: str, *, after_seq: int = 0) -> list[tuple[int, JobEvent]]:
        with db.connect(self._db_path) as conn:
            return job_repo.list_job_events(conn, job_id, after_seq=after_seq)
