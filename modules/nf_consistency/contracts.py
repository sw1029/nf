from __future__ import annotations

from typing import Protocol, TypedDict

from modules.nf_shared.protocol.dtos import VerdictLog


class ConsistencyRequest(TypedDict):
    pid: str
    input_doc_id: str
    input_snapshot_id: str
    range: dict
    schema_ver: str


class ConsistencyEngine(Protocol):
    def run(self, req: ConsistencyRequest) -> list[VerdictLog]: ...
