from typing import Literal, Sequence


def run_retrieval_job(
    query: str | None = None,
    mode: Literal["fts", "vector"] = "fts",
    filters: Sequence[str] | None = None,
) -> None:
    """
    Run a retrieval job (placeholder).

    Planned:
    - FTS-only for sync requests
    - Vector expansion via background job with streaming results
    """
    _ = (query, mode, filters)
    raise NotImplementedError("nf_retrieval.run_retrieval_job is a placeholder.")
