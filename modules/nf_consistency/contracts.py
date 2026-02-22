from __future__ import annotations

from typing import Literal, Protocol, TypedDict

from modules.nf_shared.protocol.dtos import VerdictLog


class ConsistencyPreflight(TypedDict, total=False):
    ensure_ingest: bool
    ensure_index_fts: bool
    schema_scope: Literal["latest_approved", "explicit_only"]


ConsistencyEvidenceLinkPolicy = Literal["full", "cap", "contradict_only"]
ConsistencySelfEvidenceScope = Literal["range", "doc"]


class ConsistencyRequest(TypedDict, total=False):
    project_id: str
    input_doc_id: str
    input_snapshot_id: str
    range: dict
    schema_ver: str
    preflight: ConsistencyPreflight
    schema_scope: Literal["latest_approved", "explicit_only"]
    filters: dict
    stats: dict
    extraction: dict
    evidence_link_policy: ConsistencyEvidenceLinkPolicy
    evidence_link_cap: int
    exclude_self_evidence: bool
    self_evidence_scope: ConsistencySelfEvidenceScope
    graph_expand_enabled: bool
    graph_max_hops: int
    graph_doc_cap: int
    layer3_verdict_promotion: bool
    layer3_min_fts_for_promotion: float
    layer3_max_claim_chars: int
    layer3_ok_threshold: float


class ConsistencyEngine(Protocol):
    def run(self, req: ConsistencyRequest) -> list[VerdictLog]: ...
