from __future__ import annotations

import re
from typing import Any

from modules.nf_model_gateway.local.model_store import ensure_model

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


def classify_text_pair(
    premise: str,
    hypothesis: str,
    *,
    enabled: bool = False,
    model_id: str | None = None,
) -> dict[str, Any]:
    model_missing = bool(enabled and model_id and ensure_model(model_id) is None)
    premise_text = str(premise or "").strip()
    hypothesis_text = str(hypothesis or "").strip()
    if not premise_text or not hypothesis_text:
        return {
            "entail": 0.0,
            "contradict": 0.0,
            "neutral": 1.0,
            "fallback_used": model_missing,
        }

    premise_tokens = _tokens(premise_text)
    hypothesis_tokens = _tokens(hypothesis_text)
    if not premise_tokens or not hypothesis_tokens:
        return {
            "entail": 0.0,
            "contradict": 0.0,
            "neutral": 1.0,
            "fallback_used": model_missing,
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
            "fallback_used": model_missing,
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
        "fallback_used": model_missing,
    }
