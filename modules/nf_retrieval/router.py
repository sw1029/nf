from typing import Literal, Sequence


def run_retrieval_job(
    query: str | None = None,
    mode: Literal["fts", "vector"] = "fts",
    filters: Sequence[str] | None = None,
) -> None:
    """
    검색 잡 실행(placeholder).

    예정:
    - 동기 요청은 FTS-only
    - 백그라운드 잡으로 벡터 확장 + 스트리밍 결과
    """
    _ = (query, mode, filters)
    raise NotImplementedError("nf_retrieval.run_retrieval_job는 placeholder입니다.")
