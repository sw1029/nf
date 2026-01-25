import pytest

from modules.nf_retrieval import contracts


@pytest.mark.unit
def test_retrieval_request_typed_dict_fields() -> None:
    annotations = contracts.RetrievalRequest.__annotations__
    assert set(annotations.keys()) == {"pid", "query", "filters", "k"}


@pytest.mark.unit
def test_retrieval_result_typed_dict_fields() -> None:
    annotations = contracts.RetrievalResult.__annotations__
    assert set(annotations.keys()) == {"source", "score", "evidence"}


@pytest.mark.unit
def test_searcher_protocols_exist() -> None:
    assert hasattr(contracts, "FTSSearcher")
    assert hasattr(contracts, "VectorSearcher")
    assert hasattr(contracts.FTSSearcher, "search")
    assert hasattr(contracts.VectorSearcher, "search")

