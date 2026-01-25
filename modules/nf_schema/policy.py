from __future__ import annotations

from dataclasses import replace

from modules.nf_shared.protocol.dtos import FactSource, FactStatus, SchemaFact


def enforce_fact_status_policy(fact: SchemaFact) -> SchemaFact:
    """
    D3 policy: AUTO facts must be PROPOSED until user approval.
    """
    if fact.source == FactSource.AUTO and fact.status is not FactStatus.PROPOSED:
        return replace(fact, status=FactStatus.PROPOSED)
    return fact


def enforce_facts_status_policy(facts: list[SchemaFact]) -> list[SchemaFact]:
    return [enforce_fact_status_policy(f) for f in facts]

