from __future__ import annotations

from typing import Protocol, TypedDict


class EvidenceBundle(TypedDict):
    claim_text: str
    evidence: list[dict]


class ModelGateway(Protocol):
    def nli_score(self, bundle: EvidenceBundle) -> float: ...

    def suggest_local_rule(self, bundle: EvidenceBundle) -> str: ...

    def suggest_remote_api(self, bundle: EvidenceBundle) -> str: ...

    def suggest_local_gen(self, bundle: EvidenceBundle) -> str: ...  # 차순위(실구현)

