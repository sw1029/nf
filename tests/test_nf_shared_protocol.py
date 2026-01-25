import dataclasses
from pathlib import Path

import pytest

from modules.nf_shared.config import Settings, load_config
from modules.nf_shared.errors import AppError, ErrorCode
from modules.nf_shared.protocol.dtos import (
    Document,
    DocumentType,
    Evidence,
    EvidenceMatchType,
    FactSource,
    FactStatus,
    JobType,
    Project,
    SchemaFact,
    SchemaLayer,
    TagAssignment,
)
from modules.nf_shared.protocol.serialization import dump_json, load_json


@pytest.mark.unit
def test_enums_have_expected_members() -> None:
    assert DocumentType.SETTING.value == "SETTING"
    assert JobType.RETRIEVE_VEC.value == "RETRIEVE_VEC"
    assert FactStatus.PROPOSED.value == "PROPOSED"


@pytest.mark.unit
def test_settings_defaults_match_policies() -> None:
    settings = Settings()
    assert settings.sync_retrieval_mode == "FTS_ONLY"
    assert settings.enable_local_generator is False
    assert settings.explicit_fact_auto_approve is False


@pytest.mark.unit
def test_app_error_to_dict_shape() -> None:
    err = AppError(ErrorCode.VALIDATION_ERROR, "bad", {"field": "reason"})
    payload = err.to_dict()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["details"]["field"] == "reason"


@pytest.mark.unit
def test_dump_and_load_document_round_trip() -> None:
    doc = Document(
        doc_id="doc-1",
        project_id="p-1",
        title="t",
        type=DocumentType.SETTING,
        path="/doc/raw.txt",
        head_snapshot_id="s-1",
        checksum="sha256:abc",
        version=1,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )

    dumped = dump_json(doc)
    assert dumped["type"] == "SETTING"

    loaded = load_json(Document, dumped)
    assert loaded == doc


@pytest.mark.unit
def test_dump_handles_nested_dataclasses_and_enums() -> None:
    fact = SchemaFact(
        fact_id="f-1",
        project_id="p-1",
        schema_ver="v1",
        layer=SchemaLayer.EXPLICIT,
        entity_id=None,
        tag_path="설정/인물/주인공/나이",
        value={"age": 17},
        evidence_eid="e-1",
        confidence=0.9,
        source=FactSource.USER,
        status=FactStatus.APPROVED,
    )
    project = Project(project_id="p-1", name="n", created_at="t", settings={"a": 1})

    dumped_fact = dump_json(fact)
    dumped_project = dump_json(project)

    assert dumped_fact["layer"] == "explicit"
    assert dumped_fact["status"] == "APPROVED"
    assert dumped_project["settings"]["a"] == 1


@pytest.mark.unit
def test_evidence_is_dataclass() -> None:
    assert dataclasses.is_dataclass(Evidence)
    fields = {f.name for f in dataclasses.fields(Evidence)}
    assert {"eid", "doc_id", "snapshot_id", "match_type", "confirmed"} <= fields
    assert EvidenceMatchType.EXACT.value == "EXACT"


@pytest.mark.unit
def test_tag_assignment_is_dataclass() -> None:
    assert dataclasses.is_dataclass(TagAssignment)
    assignment = TagAssignment(
        assign_id="a-1",
        project_id="p-1",
        doc_id="d-1",
        snapshot_id="s-1",
        span_start=0,
        span_end=10,
        tag_path="설정/인물/주인공/나이",
        user_value=20,
        created_by=FactSource.USER,
        created_at="2026-01-01T00:00:00Z",
    )
    dumped = dump_json(assignment)
    assert dumped["tag_path"].endswith("나이")
    loaded = load_json(TagAssignment, dumped)
    assert loaded == assignment


@pytest.mark.unit
def test_version_is_not_placeholder() -> None:
    import modules.nf_shared as nf_shared

    assert isinstance(nf_shared.__version__, str)
    assert not nf_shared.__version__.endswith("placeholder")


@pytest.mark.unit
def test_load_config_reads_file_and_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "nf_config.toml"
    config_path.write_text("enable_remote_api = true\nmax_loaded_shards = 5\n", encoding="utf-8")

    monkeypatch.setenv("NF_MAX_RAM_MB", "1024")

    settings = load_config(config_path)
    assert settings.enable_remote_api is True
    assert settings.max_loaded_shards == 5
    assert settings.max_ram_mb == 1024


@pytest.mark.unit
def test_load_config_defaults_when_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NF_ENABLE_REMOTE_API", raising=False)
    settings = load_config(path=None)
    assert isinstance(settings, Settings)
    assert settings.enable_remote_api is False
