import pytest

from modules.nf_consistency import contracts


@pytest.mark.unit
def test_consistency_request_typed_dict_fields() -> None:
    annotations = contracts.ConsistencyRequest.__annotations__
    assert set(annotations.keys()) == {"pid", "input_doc_id", "input_snapshot_id", "range", "schema_ver"}


@pytest.mark.unit
def test_consistency_engine_protocol_exists() -> None:
    assert hasattr(contracts, "ConsistencyEngine")
    assert hasattr(contracts.ConsistencyEngine, "run")

