from __future__ import annotations


def _engine():
    from modules.nf_consistency import engine

    return engine


def _resolve_schema_scope(req):
    return _engine()._resolve_schema_scope(req)


def _normalize_consistency_filters(raw_filters):
    return _engine()._normalize_consistency_filters(raw_filters)


def _build_default_doc_scope(*, project_docs, input_doc_id: str):
    return _engine()._build_default_doc_scope(project_docs=project_docs, input_doc_id=input_doc_id)


def _inject_default_doc_scope(filters, *, project_docs, input_doc_id: str):
    return _engine()._inject_default_doc_scope(filters, project_docs=project_docs, input_doc_id=input_doc_id)


def _has_metadata_scope_filters(filters):
    return _engine()._has_metadata_scope_filters(filters)


def _load_facts_for_scope(conn, *, project_id: str, schema_ver, scope: str):
    return _engine()._load_facts_for_scope(conn, project_id=project_id, schema_ver=schema_ver, scope=scope)


def _resolve_excluded_self_fact_eids(conn, *, facts, input_doc_id: str):
    return _engine()._resolve_excluded_self_fact_eids(conn, facts=facts, input_doc_id=input_doc_id)
