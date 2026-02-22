from __future__ import annotations

from typing import Any

from modules.nf_model_gateway.local.text_pair_classifier import classify_text_pair

def infer_nli_distribution(
    premise: str,
    hypothesis: str,
    *,
    enabled: bool = False,
    model_id: str | None = None,
) -> dict[str, Any]:
    return classify_text_pair(
        premise,
        hypothesis,
        enabled=enabled,
        model_id=model_id,
    )


def infer_nli(premise: str, hypothesis: str) -> float:
    scores = infer_nli_distribution(premise, hypothesis, enabled=False, model_id=None)
    try:
        entail = float(scores.get("entail", 0.0))
    except (TypeError, ValueError):
        entail = 0.0
    return max(0.0, min(1.0, entail))
