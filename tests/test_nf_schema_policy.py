import pytest

from modules.nf_schema.policy import enforce_fact_status_policy
from modules.nf_shared.protocol.dtos import FactSource, FactStatus, SchemaFact, SchemaLayer


@pytest.mark.unit
def test_auto_fact_is_forced_to_proposed() -> None:
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
        source=FactSource.AUTO,
        status=FactStatus.APPROVED,
    )

    enforced = enforce_fact_status_policy(fact)
    assert enforced.source == FactSource.AUTO
    assert enforced.status == FactStatus.PROPOSED


@pytest.mark.unit
def test_user_fact_keeps_status() -> None:
    fact = SchemaFact(
        fact_id="f-2",
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

    enforced = enforce_fact_status_policy(fact)
    assert enforced == fact

