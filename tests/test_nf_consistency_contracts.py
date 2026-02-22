import pytest

from modules.nf_consistency import contracts


@pytest.mark.unit
def test_consistency_request_typed_dict_fields() -> None:
    annotations = contracts.ConsistencyRequest.__annotations__
    assert set(annotations.keys()) == {
        "project_id",
        "input_doc_id",
        "input_snapshot_id",
        "range",
        "schema_ver",
        "preflight",
        "schema_scope",
        "filters",
        "extraction",
        "stats",
        "evidence_link_policy",
        "evidence_link_cap",
        "exclude_self_evidence",
        "self_evidence_scope",
        "graph_expand_enabled",
        "graph_mode",
        "graph_max_hops",
        "graph_doc_cap",
        "layer3_verdict_promotion",
        "layer3_min_fts_for_promotion",
        "layer3_max_claim_chars",
        "layer3_ok_threshold",
        "layer3_contradict_threshold",
    }


@pytest.mark.unit
def test_consistency_engine_protocol_exists() -> None:
    assert hasattr(contracts, "ConsistencyEngine")
    assert hasattr(contracts.ConsistencyEngine, "run")
