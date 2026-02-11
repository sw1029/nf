from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_orchestrator.services.extraction_service import ExtractionServiceImpl


@pytest.mark.unit
def test_extraction_service_crud_and_checksum(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    service = ExtractionServiceImpl(db_path)
    project_id = "project-1"

    checksum_before = service.mapping_checksum(project_id)

    created = service.create_mapping(
        project_id,
        slot_key="job",
        pattern=r"class:\s*([^\n,.]+)",
        flags="I",
        transform="strip",
        priority=100,
        enabled=True,
        created_by="USER",
    )
    assert created.mapping_id
    assert created.project_id == project_id

    listed = service.list_mappings(project_id)
    assert len(listed) == 1
    assert listed[0].mapping_id == created.mapping_id

    fetched = service.get_mapping(created.mapping_id)
    assert fetched is not None
    assert fetched.mapping_id == created.mapping_id

    checksum_after_create = service.mapping_checksum(project_id)
    assert checksum_after_create != checksum_before

    updated = service.update_mapping(created.mapping_id, pattern=r"class:\s*([^\n,.;]+)", priority=120)
    assert updated is not None
    assert updated.priority == 120

    checksum_after_update = service.mapping_checksum(project_id)
    assert checksum_after_update != checksum_after_create

    deleted = service.delete_mapping(created.mapping_id)
    assert deleted is True
    assert service.get_mapping(created.mapping_id) is None
    assert service.list_mappings(project_id) == []

    checksum_after_delete = service.mapping_checksum(project_id)
    assert checksum_after_delete == checksum_before

