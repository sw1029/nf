from __future__ import annotations


def infer_nli(premise: str, hypothesis: str) -> float:
    if not premise or not hypothesis:
        return 0.0
    return 0.5
