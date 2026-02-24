from __future__ import annotations


def _engine():
    from modules.nf_consistency import engine

    return engine


def _resolve_evidence_link_options(req):
    return _engine()._resolve_evidence_link_options(req)


def _resolve_self_evidence_options(req):
    return _engine()._resolve_self_evidence_options(req)


def _resolve_graph_expand_options(req):
    return _engine()._resolve_graph_expand_options(req)


def _resolve_graph_mode(req, *, legacy_enabled=False):
    return _engine()._resolve_graph_mode(req, legacy_enabled=legacy_enabled)


def _resolve_layer3_promotion_options(req):
    return _engine()._resolve_layer3_promotion_options(req)


def _resolve_verifier_options(req):
    return _engine()._resolve_verifier_options(req)


def _resolve_triage_options(req):
    return _engine()._resolve_triage_options(req)


def _resolve_verification_loop_options(req):
    return _engine()._resolve_verification_loop_options(req)
