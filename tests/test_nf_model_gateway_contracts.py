import pytest

from modules.nf_model_gateway import contracts


@pytest.mark.unit
def test_evidence_bundle_fields() -> None:
    annotations = contracts.EvidenceBundle.__annotations__
    assert set(annotations.keys()) == {"claim_text", "evidence"}


@pytest.mark.unit
def test_extraction_bundle_fields() -> None:
    annotations = contracts.ExtractionBundle.__annotations__
    assert set(annotations.keys()) == {"claim_text", "evidence", "model_slots", "timeout_ms"}


@pytest.mark.unit
def test_model_gateway_protocol_methods_exist() -> None:
    assert hasattr(contracts, "ModelGateway")
    assert hasattr(contracts.ModelGateway, "nli_score")
    assert hasattr(contracts.ModelGateway, "suggest_local_rule")
    assert hasattr(contracts.ModelGateway, "suggest_remote_api")
    assert hasattr(contracts.ModelGateway, "suggest_local_gen")
    assert hasattr(contracts.ModelGateway, "extract_slots_local")
    assert hasattr(contracts.ModelGateway, "extract_slots_remote")

