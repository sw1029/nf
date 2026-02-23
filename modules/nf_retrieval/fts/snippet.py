from __future__ import annotations


def make_snippet(text: str, query: str, *, max_len: int = 200) -> str:
    if not text:
        return ""
    if not query:
        return text[:max_len]
    lowered = text.lower()
    for token in query.lower().split():
        idx = lowered.find(token)
        if idx >= 0:
            start = max(idx - max_len // 4, 0)
            end = min(start + max_len, len(text))
            return text[start:end]
    return text[:max_len]
