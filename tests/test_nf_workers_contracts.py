import pytest

from modules.nf_workers import contracts


@pytest.mark.unit
def test_worker_contracts_exist() -> None:
    assert hasattr(contracts, "JobContext")
    assert hasattr(contracts, "JobHandler")


@pytest.mark.unit
def test_job_context_required_members() -> None:
    assert hasattr(contracts.JobContext, "emit")
    assert hasattr(contracts.JobContext, "check_cancelled")


@pytest.mark.unit
def test_job_handler_required_members() -> None:
    assert "job_type" in getattr(contracts.JobHandler, "__annotations__", {})
    assert hasattr(contracts.JobHandler, "run")
