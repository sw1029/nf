from __future__ import annotations

from typing import Any, Protocol

from modules.nf_shared.protocol.dtos import (
    FactID,
    FactStatus,
    Job,
    JobID,
    JobType,
    Project,
    ProjectID,
    SchemaFact,
    SchemaView,
)


class ProjectService(Protocol):
    def list_projects(self) -> list[Project]: ...

    def create_project(self, name: str, settings: dict[str, Any]) -> Project: ...


class SchemaService(Protocol):
    def get_schema_view(self, project_id: ProjectID) -> SchemaView: ...

    def list_facts(
        self,
        project_id: ProjectID,
        *,
        status: FactStatus | None = None,
        layer: str | None = None,
        source: str | None = None,
    ) -> list[SchemaFact]: ...

    def set_fact_status(self, project_id: ProjectID, fact_id: FactID, status: FactStatus) -> SchemaFact: ...


class JobService(Protocol):
    def submit(
        self,
        project_id: ProjectID,
        job_type: JobType,
        inputs: dict[str, Any],
        params: dict[str, Any],
        priority: int = 100,
    ) -> Job: ...

    def cancel(self, job_id: JobID) -> None: ...

    def get(self, job_id: JobID) -> Job: ...
