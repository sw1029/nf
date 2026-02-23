from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict


ALLOWED_SLOT_KEYS: tuple[str, ...] = (
    "age",
    "time",
    "place",
    "relation",
    "affiliation",
    "job",
    "talent",
    "death",
)

ALLOWED_EXTRACTION_MODES: tuple[str, ...] = (
    "rule_only",
    "hybrid_local",
    "hybrid_remote",
    "hybrid_dual",
)

DEFAULT_MODEL_SLOTS: tuple[str, ...] = ("time", "place", "relation", "affiliation", "job", "talent", "death")


class ExtractionProfile(TypedDict):
    mode: Literal["rule_only", "hybrid_local", "hybrid_remote", "hybrid_dual"]
    use_user_mappings: bool
    model_slots: list[str]
    model_timeout_ms: int


@dataclass(frozen=True)
class ExtractionRule:
    slot_key: str
    pattern: str
    flags: str = ""
    priority: int = 100
    transform: str = "identity"
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractionMapping:
    mapping_id: str
    project_id: str
    slot_key: str
    pattern: str
    flags: str
    transform: str
    priority: int
    enabled: bool
    created_by: str
    created_at: str


@dataclass(frozen=True)
class ExtractionCandidate:
    slot_key: str
    value: object
    confidence: float
    source: str
    span_start: int
    span_end: int
    matched_text: str


@dataclass(frozen=True)
class ExtractionResult:
    slots: dict[str, object]
    candidates: list[ExtractionCandidate]
    rule_eval_ms: float
    model_eval_ms: float


def normalize_extraction_profile(raw: Any) -> ExtractionProfile:
    profile: ExtractionProfile = {
        "mode": "rule_only",
        "use_user_mappings": True,
        "model_slots": list(DEFAULT_MODEL_SLOTS),
        "model_timeout_ms": 1200,
    }
    if not isinstance(raw, dict):
        return profile

    mode = raw.get("mode")
    if isinstance(mode, str) and mode in ALLOWED_EXTRACTION_MODES:
        profile["mode"] = mode

    use_user = raw.get("use_user_mappings")
    if isinstance(use_user, bool):
        profile["use_user_mappings"] = use_user

    model_slots_raw = raw.get("model_slots")
    if isinstance(model_slots_raw, list):
        cleaned = [str(item) for item in model_slots_raw if isinstance(item, str) and item in ALLOWED_SLOT_KEYS]
        if cleaned:
            profile["model_slots"] = cleaned

    timeout_raw = raw.get("model_timeout_ms")
    if isinstance(timeout_raw, int):
        if timeout_raw < 100:
            profile["model_timeout_ms"] = 100
        elif timeout_raw > 60_000:
            profile["model_timeout_ms"] = 60_000
        else:
            profile["model_timeout_ms"] = timeout_raw
    return profile

