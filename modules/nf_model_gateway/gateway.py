from __future__ import annotations

from typing import Literal

from modules.nf_model_gateway.contracts import EvidenceBundle, ModelGateway
from modules.nf_model_gateway.prompting import build_remote_prompt
from modules.nf_model_gateway.remote.circuit_breaker import CircuitBreaker
from modules.nf_model_gateway.remote.provider import mask_sensitive, select_remote_provider
from modules.nf_model_gateway.remote.rate_limit import RateLimiter
from modules.nf_shared.config import Settings, load_config
from modules.nf_shared.logging import get_logger


class BasicModelGateway:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or load_config()
        self._rate_limiter = RateLimiter()
        self._circuit_breaker = CircuitBreaker()
        self._remote_provider = select_remote_provider()
        self._logger = get_logger(__name__)

    def nli_score(self, bundle: EvidenceBundle) -> float:
        if self._settings.evidence_required_for_model_output and not bundle.get("evidence"):
            return 0.0
        return 0.5

    def suggest_local_rule(self, bundle: EvidenceBundle) -> str:
        evidence_count = len(bundle.get("evidence") or [])
        if self._settings.evidence_required_for_model_output and evidence_count == 0:
            return "insufficient evidence"
        return f"{bundle.get('claim_text', '')} (evidence: {evidence_count})"

    def suggest_remote_api(self, bundle: EvidenceBundle) -> str:
        if not self._settings.enable_remote_api:
            raise RuntimeError("remote api disabled")
        if self._settings.evidence_required_for_model_output and not bundle.get("evidence"):
            return "insufficient evidence"
        if not self._rate_limiter.allow():
            raise RuntimeError("remote api rate limited")
        if not self._circuit_breaker.allow():
            raise RuntimeError("remote api circuit open")
        try:
            prompt = build_remote_prompt(bundle)
            self._logger.debug("remote api prompt: %s", mask_sensitive(prompt))
            result = self._remote_provider.complete(prompt)
            self._logger.debug("remote api response: %s", mask_sensitive(result))
        except Exception as exc:  # noqa: BLE001
            self._circuit_breaker.record_failure()
            raise exc
        self._circuit_breaker.record_success()
        return result

    def suggest_local_gen(self, bundle: EvidenceBundle) -> str:
        if not self._settings.enable_local_generator:
            raise RuntimeError("local generator disabled")
        return self.suggest_local_rule(bundle)


def select_model(
    purpose: Literal["consistency", "suggest_local_rule", "suggest_local_gen", "remote_api"] | None = None
) -> ModelGateway:
    _ = purpose
    return BasicModelGateway()
