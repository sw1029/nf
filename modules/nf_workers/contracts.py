from __future__ import annotations

from typing import Any, Mapping, Protocol

from modules.nf_shared.protocol.dtos import JobEvent, JobID, JobType, ProjectID


class JobContext(Protocol):
    job_id: JobID
    project_id: ProjectID
    payload: Mapping[str, Any]

    def emit(self, event: JobEvent) -> None: ...

    def check_cancelled(self) -> bool: ...


class JobHandler(Protocol):
    job_type: JobType

    def run(self, ctx: JobContext) -> None: ...

