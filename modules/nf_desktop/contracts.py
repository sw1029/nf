from __future__ import annotations

from typing import Iterator, Protocol


class OrchestratorClient(Protocol):
    def post_query_retrieval_fts(
        self, project_id: str, query: str, filters: dict, k: int
    ) -> list[dict]: ...

    def submit_job(self, project_id: str, job_type: str, inputs: dict, params: dict) -> dict: ...

    def stream_job_events(self, job_id: str) -> Iterator[dict]: ...


class ProofreadRuleEngine(Protocol):
    def lint(self, text: str) -> list[dict]: ...
