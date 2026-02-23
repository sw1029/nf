from __future__ import annotations

import pytest

from modules.nf_orchestrator.main import OrchestratorHandler
from modules.nf_shared.errors import AppError, ErrorCode


@pytest.mark.unit
def test_validate_extraction_mapping_payload_compiles_regex_with_flags() -> None:
    handler = object.__new__(OrchestratorHandler)
    validated = handler._validate_extraction_mapping_payload(
        {
            "slot_key": "job",
            "pattern": r"class:\s*([^\n,.]+)",
            "flags": "I",
            "transform": "strip",
            "priority": 100,
            "enabled": True,
            "created_by": "USER",
        },
        partial=False,
    )
    assert validated["slot_key"] == "job"
    assert validated["flags"] == "I"


@pytest.mark.unit
def test_validate_extraction_mapping_payload_rejects_bad_flags() -> None:
    handler = object.__new__(OrchestratorHandler)
    with pytest.raises(AppError) as exc_info:
        handler._validate_extraction_mapping_payload(
            {
                "slot_key": "job",
                "pattern": r"class:\s*([^\n,.]+)",
                "flags": "IZ",
                "transform": "strip",
                "priority": 100,
                "enabled": True,
                "created_by": "USER",
            },
            partial=False,
        )
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR

