from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from modules.nf_model_gateway.local.model_store import describe_model_path, ensure_model, read_model_manifest

_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)
_NUMBER_RE = re.compile(r"-?\d+")
_NEGATION_TOKENS = {"not", "no", "never", "none", "without", "cannot", "can't", "isnt", "isn't"}
_CONTRADICTION_TOKEN_PAIRS = (
    ("alive", "dead"),
    ("before", "after"),
    ("older", "younger"),
    ("inside", "outside"),
    ("same", "different"),
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text or "") if token}


def _contains_negation(tokens: set[str]) -> bool:
    return any(token in _NEGATION_TOKENS for token in tokens)


def _extract_numbers(text: str) -> set[int]:
    values: set[int] = set()
    for raw in _NUMBER_RE.findall(text or ""):
        try:
            values.add(int(raw))
        except ValueError:
            continue
    return values


def _has_token_pair_mismatch(left: set[str], right: set[str]) -> bool:
    for a, b in _CONTRADICTION_TOKEN_PAIRS:
        if (a in left and b in right) or (b in left and a in right):
            return True
    return False


def _heuristic_distribution(
    premise_text: str,
    hypothesis_text: str,
    *,
    fallback_used: bool,
) -> dict[str, Any]:
    effective_backend = "heuristic"
    if not premise_text or not hypothesis_text:
        return {
            "entail": 0.0,
            "contradict": 0.0,
            "neutral": 1.0,
            "effective_backend": effective_backend,
            "fallback_used": fallback_used,
        }

    premise_tokens = _tokens(premise_text)
    hypothesis_tokens = _tokens(hypothesis_text)
    if not premise_tokens or not hypothesis_tokens:
        return {
            "entail": 0.0,
            "contradict": 0.0,
            "neutral": 1.0,
            "effective_backend": effective_backend,
            "fallback_used": fallback_used,
        }

    overlap = premise_tokens.intersection(hypothesis_tokens)
    coverage = len(overlap) / float(max(1, len(hypothesis_tokens)))
    precision = len(overlap) / float(max(1, len(premise_tokens)))

    numbers_premise = _extract_numbers(premise_text)
    numbers_hypothesis = _extract_numbers(hypothesis_text)
    number_mismatch = bool(
        numbers_premise and numbers_hypothesis and numbers_premise.isdisjoint(numbers_hypothesis)
    )
    negation_mismatch = _contains_negation(premise_tokens) ^ _contains_negation(hypothesis_tokens)
    token_pair_mismatch = _has_token_pair_mismatch(premise_tokens, hypothesis_tokens)

    contradiction_signals = 0
    if number_mismatch:
        contradiction_signals += 1
    if negation_mismatch and coverage > 0.25:
        contradiction_signals += 1
    if token_pair_mismatch:
        contradiction_signals += 1

    if coverage >= 0.95 and precision >= 0.55 and contradiction_signals == 0:
        entail = 0.96
        contradict = 0.02
        neutral = 0.02
        return {
            "entail": entail,
            "contradict": contradict,
            "neutral": neutral,
            "effective_backend": effective_backend,
            "fallback_used": fallback_used,
        }

    entail = _clamp01(0.08 + (0.72 * coverage) + (0.20 * precision))
    if contradiction_signals > 0:
        contradict = _clamp01(0.35 + (0.22 * contradiction_signals) + (0.20 * (1.0 - coverage)))
    else:
        contradict = _clamp01(0.04 + (0.16 * (1.0 - coverage)))
    if contradiction_signals > 0 and entail > 0.2:
        entail *= 0.7

    neutral = _clamp01(1.0 - max(entail, contradict))
    total = entail + contradict + neutral
    if total <= 0:
        entail, contradict, neutral = 0.0, 0.0, 1.0
    else:
        entail = _clamp01(entail / total)
        contradict = _clamp01(contradict / total)
        neutral = _clamp01(neutral / total)

    return {
        "entail": entail,
        "contradict": contradict,
        "neutral": neutral,
        "effective_backend": effective_backend,
        "fallback_used": fallback_used,
    }


def _normalize_label(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _resolve_label_indices(
    *,
    model: Any,
    manifest: dict[str, Any],
    label_count: int,
) -> tuple[int, int, int]:
    id2label = getattr(getattr(model, "config", None), "id2label", {}) or {}
    normalized_labels: dict[int, str] = {}
    if isinstance(id2label, dict):
        for idx, label in id2label.items():
            try:
                normalized_labels[int(idx)] = _normalize_label(label)
            except (TypeError, ValueError):
                continue
    entail_idx = next((idx for idx, label in normalized_labels.items() if "entail" in label), None)
    contradict_idx = next((idx for idx, label in normalized_labels.items() if "contradict" in label), None)
    neutral_idx = next((idx for idx, label in normalized_labels.items() if "neutral" in label), None)
    if entail_idx is not None and contradict_idx is not None and neutral_idx is not None:
        return entail_idx, contradict_idx, neutral_idx

    manifest_order = manifest.get("label_order")
    if isinstance(manifest_order, list) and len(manifest_order) == label_count:
        normalized = [_normalize_label(item) for item in manifest_order]
        entail_idx = normalized.index("entailment") if "entailment" in normalized else None
        contradict_idx = normalized.index("contradiction") if "contradiction" in normalized else None
        neutral_idx = normalized.index("neutral") if "neutral" in normalized else None
        if entail_idx is not None and contradict_idx is not None and neutral_idx is not None:
            return entail_idx, contradict_idx, neutral_idx

    if label_count == 3:
        return 2, 0, 1
    raise RuntimeError("unable to resolve local NLI label mapping")


@lru_cache(maxsize=2)
def _load_local_sequence_classifier(model_path_str: str) -> tuple[Any, Any, dict[str, Any]]:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_path = Path(model_path_str)
    tokenizer = AutoTokenizer.from_pretrained(model_path_str, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(model_path_str)
    model.eval()
    return tokenizer, model, read_model_manifest(model_path)


def _resolve_max_length(tokenizer: Any, manifest: dict[str, Any]) -> int:
    if manifest.get("max_length") is not None:
        try:
            return max(8, min(1024, int(manifest["max_length"])))
        except (TypeError, ValueError):
            pass
    try:
        model_max_length = int(getattr(tokenizer, "model_max_length", 512))
    except (TypeError, ValueError):
        model_max_length = 512
    if model_max_length <= 0 or model_max_length > 16384:
        model_max_length = 512
    return max(8, min(1024, model_max_length))


def _classify_with_local_model(
    premise_text: str,
    hypothesis_text: str,
    *,
    model_path: Path,
) -> dict[str, Any]:
    import torch

    tokenizer, model, manifest = _load_local_sequence_classifier(str(model_path))
    max_length = _resolve_max_length(tokenizer, manifest)
    encoded = tokenizer(
        premise_text,
        hypothesis_text,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    with torch.inference_mode():
        outputs = model(**encoded)
    logits = outputs.logits[0]
    probs = torch.nn.functional.softmax(logits, dim=-1).detach().cpu().tolist()
    entail_idx, contradict_idx, neutral_idx = _resolve_label_indices(
        model=model,
        manifest=manifest,
        label_count=len(probs),
    )
    entail = _clamp01(float(probs[entail_idx]))
    contradict = _clamp01(float(probs[contradict_idx]))
    neutral = _clamp01(float(probs[neutral_idx]))
    total = entail + contradict + neutral
    if total <= 0:
        entail, contradict, neutral = 0.0, 0.0, 1.0
    else:
        entail = _clamp01(entail / total)
        contradict = _clamp01(contradict / total)
        neutral = _clamp01(neutral / total)
    return {
        "entail": entail,
        "contradict": contradict,
        "neutral": neutral,
        "effective_backend": "local_nli_model",
        "fallback_used": False,
    }


def classify_text_pair(
    premise: str,
    hypothesis: str,
    *,
    enabled: bool = False,
    model_id: str | None = None,
) -> dict[str, Any]:
    premise_text = str(premise or "").strip()
    hypothesis_text = str(hypothesis or "").strip()
    model_ref = ensure_model(model_id) if enabled and model_id else None
    fallback_used = bool(enabled and model_id and model_ref is None)
    if isinstance(model_ref, Path):
        model_status = describe_model_path(model_ref, model_id=str(model_id or ""))
        if bool(model_status.get("runtime_ready")):
            try:
                return _classify_with_local_model(
                    premise_text,
                    hypothesis_text,
                    model_path=model_ref,
                )
            except Exception:
                fallback_used = True
        else:
            fallback_used = True
    return _heuristic_distribution(
        premise_text,
        hypothesis_text,
        fallback_used=fallback_used,
    )
