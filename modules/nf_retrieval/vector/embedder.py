from __future__ import annotations

import hashlib
import math
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


def _stable_token_bucket(token: str, *, dim: int) -> tuple[int, float]:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], byteorder="little", signed=False) % max(1, dim)
    sign = 1.0 if (digest[4] & 1) == 0 else -1.0
    return bucket, sign


def hashed_embedding(text: str, *, dim: int = 96) -> list[float]:
    width = max(1, int(dim))
    vec = [0.0] * width
    counts = token_vector(tokenize(text))
    for token, count in counts.items():
        bucket, sign = _stable_token_bucket(token, dim=width)
        vec[bucket] += sign * float(count)
    norm = math.sqrt(sum(value * value for value in vec))
    if norm <= 0.0:
        return vec
    return [value / norm for value in vec]


def cosine_similarity(lhs: Iterable[float], rhs: Iterable[float]) -> float:
    left = list(lhs)
    right = list(rhs)
    if not left or not right:
        return 0.0
    if len(left) != len(right):
        width = min(len(left), len(right))
        left = left[:width]
        right = right[:width]
    dot = sum(l * r for l, r in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    denom = left_norm * right_norm
    if denom <= 0.0:
        return 0.0
    return dot / denom


def hashed_embedding_score(query_text: str, doc_text: str, *, dim: int = 96) -> float:
    query_vec = hashed_embedding(query_text, dim=dim)
    doc_vec = hashed_embedding(doc_text, dim=dim)
    return max(0.0, cosine_similarity(query_vec, doc_vec))
