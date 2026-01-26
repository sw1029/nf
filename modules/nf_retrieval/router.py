from typing import Any, Literal

from modules.nf_orchestrator.storage import db
from modules.nf_retrieval.contracts import RetrievalRequest, RetrievalResult
from modules.nf_retrieval.fts.fts_index import fts_search


def run_retrieval_job(
    project_id: str,
    query: str,
    *,
    mode: Literal["fts", "vector"] = "fts",
    filters: dict[str, Any] | None = None,
    k: int = 10,
    db_path=None,
) -> list[RetrievalResult]:
    """
    검색 실행(FTS-only 기본). 벡터 모드는 추후 확장.
    """
    req: RetrievalRequest = {
        "project_id": project_id,
        "query": query,
        "filters": filters or {},
        "k": k,
    }
    with db.connect(db_path) as conn:
        if mode == "fts":
            return fts_search(conn, req)
        return fts_search(conn, req)
