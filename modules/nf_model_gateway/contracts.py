from __future__ import annotations

from typing import Protocol, TypedDict


class EvidenceBundle(TypedDict):
    claim_text: str
    evidence: list[dict]


class ExtractionBundle(TypedDict, total=False):
    claim_text: str
    evidence: list[dict]
    model_slots: list[str]
    timeout_ms: int


class ExtractionCandidate(TypedDict, total=False):
    slot_key: str
    value: object
    confidence: float
    span_start: int
    span_end: int
    matched_text: str


class ModelGateway(Protocol):
    def nli_score(self, bundle: EvidenceBundle) -> float: ...

    def suggest_local_rule(self, bundle: EvidenceBundle) -> str: ...

    def suggest_remote_api(self, bundle: EvidenceBundle) -> str: ...

    def suggest_local_gen(self, bundle: EvidenceBundle) -> str: ...  # 차순위(실구현)

    def extract_slots_local(self, bundle: ExtractionBundle) -> list[ExtractionCandidate]: ...

    def extract_slots_remote(self, bundle: ExtractionBundle) -> list[ExtractionCandidate]: ...

