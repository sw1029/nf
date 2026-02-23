from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any

from modules.nf_model_gateway.contracts import ModelGateway

from .contracts import (
    DEFAULT_MODEL_SLOTS,
    ExtractionCandidate,
    ExtractionMapping,
    ExtractionProfile,
    ExtractionResult,
    ExtractionRule,
    normalize_extraction_profile,
)
from .rule_extractor import RuleExtractor, builtin_rules


def _checksum_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _merge_candidates(candidates: list[ExtractionCandidate]) -> dict[str, object]:
    slots: dict[str, object] = {}
    for candidate in candidates:
        if candidate.slot_key in slots:
            continue
        slots[candidate.slot_key] = candidate.value
    return slots


class ExtractionPipeline:
    def __init__(
        self,
        *,
        profile: dict[str, Any] | ExtractionProfile | None = None,
        mappings: list[ExtractionMapping] | None = None,
        gateway: ModelGateway | None = None,
    ) -> None:
        self.profile: ExtractionProfile = normalize_extraction_profile(profile)
        self.version = "extractor_v2"
        self._gateway = gateway
        self._segment_cache: OrderedDict[str, ExtractionResult] = OrderedDict()
        self._cache_size = 1024

        self._builtin_extractor = RuleExtractor(builtin_rules())
        enabled_mappings = [item for item in (mappings or []) if item.enabled]
        mapping_rules = []
        for item in enabled_mappings:
            mapping_rules.append(
                ExtractionRule(
                    slot_key=item.slot_key,
                    pattern=item.pattern,
                    flags=item.flags,
                    priority=int(item.priority),
                    transform=item.transform,
                    keywords=(),
                )
            )
        self._mapping_extractor = RuleExtractor(mapping_rules) if mapping_rules else None
        self.ruleset_checksum = _checksum_payload([rule.pattern for rule in builtin_rules()])
        self.mapping_checksum = _checksum_payload(
            [
                {
                    "mapping_id": item.mapping_id,
                    "slot_key": item.slot_key,
                    "pattern": item.pattern,
                    "flags": item.flags,
                    "transform": item.transform,
                    "priority": item.priority,
                    "enabled": item.enabled,
                }
                for item in enabled_mappings
            ]
        )

    def extract(self, segment: str) -> ExtractionResult:
        normalized = " ".join(segment.split()).strip().lower()
        cached = self._segment_cache.get(normalized)
        if cached is not None:
            self._segment_cache.move_to_end(normalized)
            return cached

        rule_start = time.perf_counter()
        candidates: list[ExtractionCandidate] = []
        if self.profile["use_user_mappings"] and self._mapping_extractor is not None:
            candidates.extend(self._mapping_extractor.extract(segment, source="user_mapping", confidence=0.98))
        candidates.extend(self._builtin_extractor.extract(segment, source="rule", confidence=0.85))
        candidates.sort(key=lambda item: (item.source != "user_mapping", -item.confidence))
        slots = _merge_candidates(candidates)
        rule_eval_ms = (time.perf_counter() - rule_start) * 1000.0

        model_eval_ms = 0.0
        mode = self.profile["mode"]
        if mode != "rule_only":
            missing_slots = [slot for slot in self.profile["model_slots"] if slot not in slots]
            if missing_slots:
                model_start = time.perf_counter()
                model_candidates: list[ExtractionCandidate] = []
                if mode in {"hybrid_local", "hybrid_dual"}:
                    model_candidates.extend(self._run_model_local(segment, missing_slots))
                if mode in {"hybrid_remote", "hybrid_dual"}:
                    remote_missing = [slot for slot in missing_slots if slot not in {c.slot_key for c in model_candidates}]
                    if remote_missing:
                        model_candidates.extend(self._run_model_remote(segment, remote_missing))
                for item in model_candidates:
                    if item.slot_key not in slots:
                        candidates.append(item)
                        slots[item.slot_key] = item.value
                model_eval_ms = (time.perf_counter() - model_start) * 1000.0

        result = ExtractionResult(
            slots=slots,
            candidates=candidates,
            rule_eval_ms=rule_eval_ms,
            model_eval_ms=model_eval_ms,
        )
        self._segment_cache[normalized] = result
        self._segment_cache.move_to_end(normalized)
        while len(self._segment_cache) > self._cache_size:
            self._segment_cache.popitem(last=False)
        return result

    def _run_model_local(self, segment: str, model_slots: list[str]) -> list[ExtractionCandidate]:
        if self._gateway is None:
            return []
        try:
            raw = self._gateway.extract_slots_local(
                {
                    "claim_text": segment,
                    "evidence": [],
                    "model_slots": list(model_slots or DEFAULT_MODEL_SLOTS),
                    "timeout_ms": int(self.profile["model_timeout_ms"]),
                }
            )
        except Exception:  # noqa: BLE001
            return []
        return self._from_model_candidates(raw, source="local_model")

    def _run_model_remote(self, segment: str, model_slots: list[str]) -> list[ExtractionCandidate]:
        if self._gateway is None:
            return []
        try:
            raw = self._gateway.extract_slots_remote(
                {
                    "claim_text": segment,
                    "evidence": [],
                    "model_slots": list(model_slots or DEFAULT_MODEL_SLOTS),
                    "timeout_ms": int(self.profile["model_timeout_ms"]),
                }
            )
        except Exception:  # noqa: BLE001
            return []
        return self._from_model_candidates(raw, source="remote_model")

    @staticmethod
    def _from_model_candidates(raw: list[dict[str, Any]] | None, *, source: str) -> list[ExtractionCandidate]:
        if not isinstance(raw, list):
            return []
        parsed: list[ExtractionCandidate] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            slot_key = item.get("slot_key")
            if not isinstance(slot_key, str):
                continue
            confidence_raw = item.get("confidence", 0.5)
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.5
            span_start = item.get("span_start", 0)
            span_end = item.get("span_end", 0)
            try:
                span_start_i = int(span_start)
            except (TypeError, ValueError):
                span_start_i = 0
            try:
                span_end_i = int(span_end)
            except (TypeError, ValueError):
                span_end_i = 0
            matched_text = item.get("matched_text")
            if not isinstance(matched_text, str):
                matched_text = str(item.get("value", ""))
            parsed.append(
                ExtractionCandidate(
                    slot_key=slot_key,
                    value=item.get("value"),
                    confidence=max(0.0, min(1.0, confidence)),
                    source=source,
                    span_start=max(0, span_start_i),
                    span_end=max(0, span_end_i),
                    matched_text=matched_text,
                )
            )
        return parsed
