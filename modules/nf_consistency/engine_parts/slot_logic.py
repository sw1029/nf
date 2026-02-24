from __future__ import annotations


def _engine():
    from modules.nf_consistency import engine

    return engine


def _normalize_slot_key(tag_path: str):
    return _engine()._normalize_slot_key(tag_path)


def _fact_slot_key(tag_path: str, *, tag_def=None):
    return _engine()._fact_slot_key(tag_path, tag_def=tag_def)


def _build_fact_index(facts, *, tag_defs):
    return _engine()._build_fact_index(facts, tag_defs=tag_defs)


def _compare_slot(slot_key: str, claim_value, fact_value):
    return _engine()._compare_slot(slot_key, claim_value, fact_value)


def _judge_with_fact_index(
    slots,
    fact_index,
    *,
    target_entity_id=None,
    evidence_link_policy="cap",
    evidence_link_cap=20,
    comparison_cache=None,
    excluded_fact_eids=None,
):
    return _engine()._judge_with_fact_index(
        slots,
        fact_index,
        target_entity_id=target_entity_id,
        evidence_link_policy=evidence_link_policy,
        evidence_link_cap=evidence_link_cap,
        comparison_cache=comparison_cache,
        excluded_fact_eids=excluded_fact_eids,
    )
