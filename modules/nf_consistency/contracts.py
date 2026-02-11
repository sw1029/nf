from __future__ import annotations

from typing import Literal, Protocol, TypedDict

from modules.nf_shared.protocol.dtos import VerdictLog


class ConsistencyPreflight(TypedDict, total=False):
    ensure_ingest: bool
    ensure_index_fts: bool
    schema_scope: Literal["latest_approved", "explicit_only"]


class ConsistencyRequest(TypedDict, total=False):
    project_id: str
    input_doc_id: str
    input_snapshot_id: str
    range: dict
    schema_ver: str
    preflight: ConsistencyPreflight
    schema_scope: Literal["latest_approved", "explicit_only"]
    stats: dict


class ConsistencyEngine(Protocol):
    def run(self, req: ConsistencyRequest) -> list[VerdictLog]: ...
