from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def token_vector(tokens: Iterable[str]) -> Counter[str]:
    return Counter(tokens)


def overlap_score(query_tokens: Iterable[str], doc_tokens: Iterable[str]) -> float:
    query_vec = token_vector(query_tokens)
    doc_vec = token_vector(doc_tokens)
    if not query_vec:
        return 0.0
    overlap = sum(min(query_vec[token], doc_vec.get(token, 0)) for token in query_vec)
    return overlap / max(1, sum(query_vec.values()))
