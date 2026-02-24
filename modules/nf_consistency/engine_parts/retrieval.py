from __future__ import annotations


def _engine():
    from modules.nf_consistency import engine

    return engine


def _claim_cache_key(claim_text: str, *, filters):
    return _engine()._claim_cache_key(claim_text, filters=filters)


def _rerank_results_for_consistency(
    *,
    results,
    claim_text: str,
    filters,
    graph_doc_distances,
    gateway,
    enable_model: bool,
    settings,
):
    return _engine()._rerank_results_for_consistency(
        results=results,
        claim_text=claim_text,
        filters=filters,
        graph_doc_distances=graph_doc_distances,
        gateway=gateway,
        enable_model=enable_model,
        settings=settings,
    )


def _filter_self_evidence_results(
    results,
    *,
    input_doc_id: str,
    scope: str,
    claim_abs_start: int,
    claim_abs_end: int,
    range_start,
    range_end,
):
    return _engine()._filter_self_evidence_results(
        results,
        input_doc_id=input_doc_id,
        scope=scope,
        claim_abs_start=claim_abs_start,
        claim_abs_end=claim_abs_end,
        range_start=range_start,
        range_end=range_end,
    )


def _promote_confirmed_evidence(conn, *, project_id: str, results, user_tag_span_cache, approved_evidence_span_cache):
    return _engine()._promote_confirmed_evidence(
        conn,
        project_id=project_id,
        results=results,
        user_tag_span_cache=user_tag_span_cache,
        approved_evidence_span_cache=approved_evidence_span_cache,
    )


def _build_verdict_links(*, verdict_id: str, evidences, fact_links, policy: str, cap: int):
    return _engine()._build_verdict_links(
        verdict_id=verdict_id,
        evidences=evidences,
        fact_links=fact_links,
        policy=policy,
        cap=cap,
    )
