from __future__ import annotations

from dataclasses import replace

from modules.nf_shared.protocol.dtos import FactSource, FactStatus, SchemaFact


def enforce_fact_status_policy(fact: SchemaFact) -> SchemaFact:
    """
    D3 정책: AUTO 팩트는 사용자 승인 전까지 PROPOSED 상태로 유지.
    """
    if fact.source == FactSource.AUTO and fact.status is not FactStatus.PROPOSED:
        return replace(fact, status=FactStatus.PROPOSED)
    return fact


def enforce_facts_status_policy(facts: list[SchemaFact]) -> list[SchemaFact]:
    return [enforce_fact_status_policy(f) for f in facts]
