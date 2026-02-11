from __future__ import annotations

import json
import re
from typing import Literal

from modules.nf_model_gateway.contracts import (
    EvidenceBundle,
    ExtractionBundle,
    ExtractionCandidate,
    ModelGateway,
)
from modules.nf_model_gateway.prompting import build_remote_extraction_prompt, build_remote_prompt
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

    def extract_slots_local(self, bundle: ExtractionBundle) -> list[ExtractionCandidate]:
        if not self._settings.enable_layer3_model and not self._settings.enable_local_generator:
            return []
        return _heuristic_extract(bundle)

    def extract_slots_remote(self, bundle: ExtractionBundle) -> list[ExtractionCandidate]:
        if not self._settings.enable_remote_api:
            return []
        if not self._rate_limiter.allow():
            return []
        if not self._circuit_breaker.allow():
            return []
        try:
            prompt = build_remote_extraction_prompt(bundle)
            self._logger.debug("remote extraction prompt: %s", mask_sensitive(prompt))
            raw = self._remote_provider.complete(prompt)
            self._logger.debug("remote extraction response: %s", mask_sensitive(raw))
            parsed = _parse_remote_extraction_response(raw)
            self._circuit_breaker.record_success()
            return parsed
        except Exception:  # noqa: BLE001
            self._circuit_breaker.record_failure()
            return []


def select_model(
    purpose: Literal["consistency", "suggest_local_rule", "suggest_local_gen", "remote_api"] | None = None
) -> ModelGateway:
    _ = purpose
    return BasicModelGateway()


_AGE_RE = re.compile(r"(\d{1,3})\s*(?:살|세)")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{1,2}월\s*\d{1,2}일)")
_PLACE_RE = re.compile(r"(?:장소|위치)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)")
_REL_RE = re.compile(r"(?:관계)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)")
_AFFIL_RE = re.compile(r"(?:소속)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)")
_JOB_RE = re.compile(r"(?:직업|클래스)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)")
_JOB_FALLBACK_RE = re.compile(r"(\d+\s*서클\s*마법사)")
_TALENT_RE = re.compile(r"(?:재능)\s*(?:[:]|(?:은|는|이|가))\s*([^\n,.]+)")
_NO_TALENT_RE = re.compile(r"(재능\s*(?:이|은|는)?\s*없(?:음|다))")
_DEATH_RE = re.compile(r"(사망|죽었|죽었다|사망했다|사망함)")
_ALIVE_RE = re.compile(r"(생존|살아있)")


def _add_candidate(
    out: list[ExtractionCandidate],
    *,
    slot_key: str,
    value: object,
    confidence: float,
    matched_text: str,
    span_start: int = 0,
    span_end: int = 0,
) -> None:
    out.append(
        {
            "slot_key": slot_key,
            "value": value,
            "confidence": confidence,
            "matched_text": matched_text,
            "span_start": span_start,
            "span_end": span_end,
        }
    )


def _heuristic_extract(bundle: ExtractionBundle) -> list[ExtractionCandidate]:
    text = bundle.get("claim_text", "")
    if not isinstance(text, str) or not text:
        return []
    requested_slots = bundle.get("model_slots") or []
    if isinstance(requested_slots, list) and requested_slots:
        allow = {str(item) for item in requested_slots if isinstance(item, str)}
    else:
        allow = {"age", "time", "place", "relation", "affiliation", "job", "talent", "death"}

    candidates: list[ExtractionCandidate] = []
    if "age" in allow and (m := _AGE_RE.search(text)):
        _add_candidate(
            candidates,
            slot_key="age",
            value=int(m.group(1)),
            confidence=0.55,
            matched_text=m.group(0),
            span_start=m.start(1),
            span_end=m.end(1),
        )
    if "time" in allow and (m := _TIME_RE.search(text)):
        _add_candidate(candidates, slot_key="time", value=m.group(1), confidence=0.5, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
    if "place" in allow and (m := _PLACE_RE.search(text)):
        _add_candidate(candidates, slot_key="place", value=m.group(1).strip(), confidence=0.5, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
    if "relation" in allow and (m := _REL_RE.search(text)):
        _add_candidate(candidates, slot_key="relation", value=m.group(1).strip(), confidence=0.5, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
    if "affiliation" in allow and (m := _AFFIL_RE.search(text)):
        _add_candidate(candidates, slot_key="affiliation", value=m.group(1).strip(), confidence=0.5, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
    if "job" in allow:
        if m := _JOB_RE.search(text):
            _add_candidate(candidates, slot_key="job", value=m.group(1).strip(), confidence=0.55, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
        elif "노 클래스" in text:
            idx = text.find("노 클래스")
            _add_candidate(candidates, slot_key="job", value="노 클래스", confidence=0.45, matched_text="노 클래스", span_start=idx, span_end=idx + len("노 클래스"))
        elif m := _JOB_FALLBACK_RE.search(text):
            _add_candidate(candidates, slot_key="job", value=m.group(1), confidence=0.45, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
    if "talent" in allow:
        if m := _TALENT_RE.search(text):
            _add_candidate(candidates, slot_key="talent", value=m.group(1).strip(), confidence=0.55, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
        elif m := _NO_TALENT_RE.search(text):
            _add_candidate(candidates, slot_key="talent", value="재능 없음", confidence=0.45, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
        elif "천재" in text:
            idx = text.find("천재")
            _add_candidate(candidates, slot_key="talent", value="천재", confidence=0.4, matched_text="천재", span_start=idx, span_end=idx + len("천재"))
    if "death" in allow:
        if m := _DEATH_RE.search(text):
            _add_candidate(candidates, slot_key="death", value=True, confidence=0.55, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
        elif m := _ALIVE_RE.search(text):
            _add_candidate(candidates, slot_key="death", value=False, confidence=0.45, matched_text=m.group(1), span_start=m.start(1), span_end=m.end(1))
    return candidates


def _parse_remote_extraction_response(raw: str) -> list[ExtractionCandidate]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    payload: dict | None = None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        begin = raw.find("{")
        end = raw.rfind("}")
        if begin != -1 and end != -1 and end > begin:
            try:
                payload = json.loads(raw[begin : end + 1])
            except json.JSONDecodeError:
                payload = None
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    parsed: list[ExtractionCandidate] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        slot_key = item.get("slot_key")
        if not isinstance(slot_key, str):
            continue
        parsed.append(
            {
                "slot_key": slot_key,
                "value": item.get("value"),
                "confidence": float(item.get("confidence", 0.5)),
                "matched_text": str(item.get("matched_text", item.get("value", ""))),
                "span_start": int(item.get("span_start", 0)),
                "span_end": int(item.get("span_end", 0)),
            }
        )
    return parsed
