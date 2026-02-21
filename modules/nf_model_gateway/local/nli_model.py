from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text or "") if token}


def infer_nli(premise: str, hypothesis: str) -> float:
    if not premise or not hypothesis:
        return 0.0
    premise_tokens = _tokens(premise)
    hypothesis_tokens = _tokens(hypothesis)
    if not premise_tokens or not hypothesis_tokens:
        return 0.0
    overlap = len(premise_tokens & hypothesis_tokens)
    coverage = overlap / max(1, len(hypothesis_tokens))
    # Conservative score to avoid overconfident promotion.
    return max(0.0, min(1.0, 0.1 + (0.8 * coverage)))
