import pytest

from modules.nf_desktop import contracts


@pytest.mark.unit
def test_orchestrator_client_protocol_methods_exist() -> None:
    assert hasattr(contracts, "OrchestratorClient")
    assert hasattr(contracts.OrchestratorClient, "post_query_retrieval_fts")
    assert hasattr(contracts.OrchestratorClient, "submit_job")
    assert hasattr(contracts.OrchestratorClient, "stream_job_events")


@pytest.mark.unit
def test_proofread_rule_engine_protocol_methods_exist() -> None:
    assert hasattr(contracts, "ProofreadRuleEngine")
    assert hasattr(contracts.ProofreadRuleEngine, "lint")

