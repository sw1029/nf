from __future__ import annotations


def build_query(text: str) -> str:
    return " ".join(text.strip().split())
