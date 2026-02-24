from __future__ import annotations


def _engine():
    from modules.nf_consistency import engine

    return engine


def _fingerprint(text: str) -> str:
    return _engine()._fingerprint(text)


def _now_ts() -> str:
    return _engine()._now_ts()


def _trimmed_span(text: str, start: int, end: int):
    return _engine()._trimmed_span(text, start, end)


def _segment_text(text: str):
    return _engine()._segment_text(text)


def _extract_slots(claim_text: str):
    return _engine()._extract_slots(claim_text)


def _extract_claims(text: str, *, pipeline, stats=None):
    return _engine()._extract_claims(text, pipeline=pipeline, stats=stats)
