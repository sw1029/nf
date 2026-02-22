from __future__ import annotations

import pytest

from modules.nf_orchestrator.main import OrchestratorHandler
from modules.nf_shared.errors import AppError, ErrorCode
from modules.nf_shared.protocol.dtos import JobType


@pytest.mark.unit
def test_validate_job_params_accepts_valid_consistency_options() -> None:
    handler = object.__new__(OrchestratorHandler)
    handler._validate_job_params(
        JobType.CONSISTENCY,
        {
            "consistency": {
                "evidence_link_policy": "cap",
                "evidence_link_cap": 10,
                "exclude_self_evidence": True,
                "self_evidence_scope": "range",
                "graph_expand_enabled": False,
                "graph_max_hops": 1,
                "graph_doc_cap": 200,
            }
        },
    )


@pytest.mark.unit
def test_validate_job_params_rejects_non_object_consistency_options() -> None:
    handler = object.__new__(OrchestratorHandler)
    with pytest.raises(AppError) as exc_info:
        handler._validate_job_params(JobType.CONSISTENCY, {"consistency": "cap"})
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


@pytest.mark.unit
def test_validate_job_params_rejects_invalid_consistency_cap() -> None:
    handler = object.__new__(OrchestratorHandler)
    with pytest.raises(AppError) as exc_info:
        handler._validate_job_params(
            JobType.CONSISTENCY,
            {
                "consistency": {
                    "evidence_link_policy": "full",
                    "evidence_link_cap": 0,
                }
            },
        )
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


@pytest.mark.unit
def test_validate_job_params_rejects_invalid_self_evidence_scope() -> None:
    handler = object.__new__(OrchestratorHandler)
    with pytest.raises(AppError) as exc_info:
        handler._validate_job_params(
            JobType.CONSISTENCY,
            {"consistency": {"self_evidence_scope": "invalid"}},
        )
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


@pytest.mark.unit
def test_validate_job_params_rejects_invalid_graph_expand_options() -> None:
    handler = object.__new__(OrchestratorHandler)
    with pytest.raises(AppError) as exc_info:
        handler._validate_job_params(
            JobType.CONSISTENCY,
            {
                "consistency": {
                    "graph_expand_enabled": True,
                    "graph_max_hops": 3,
                }
            },
        )
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR

    with pytest.raises(AppError) as exc_info:
        handler._validate_job_params(
            JobType.CONSISTENCY,
            {
                "consistency": {
                    "graph_expand_enabled": True,
                    "graph_max_hops": 1,
                    "graph_doc_cap": 0,
                }
            },
        )
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR
