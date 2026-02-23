import pytest

from modules.nf_orchestrator import contracts


@pytest.mark.unit
def test_orchestrator_service_protocols_exist() -> None:
    assert hasattr(contracts, "ProjectService")
    assert hasattr(contracts, "SchemaService")
    assert hasattr(contracts, "JobService")


@pytest.mark.unit
def test_orchestrator_project_service_methods() -> None:
    assert hasattr(contracts.ProjectService, "list_projects")
    assert hasattr(contracts.ProjectService, "create_project")


@pytest.mark.unit
def test_orchestrator_schema_service_methods() -> None:
    assert hasattr(contracts.SchemaService, "get_schema_view")
    assert hasattr(contracts.SchemaService, "list_facts")
    assert hasattr(contracts.SchemaService, "set_fact_status")


@pytest.mark.unit
def test_orchestrator_job_service_methods() -> None:
    assert hasattr(contracts.JobService, "submit")
    assert hasattr(contracts.JobService, "cancel")
    assert hasattr(contracts.JobService, "get")

