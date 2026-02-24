from __future__ import annotations


def _engine():
    from modules.nf_consistency import engine

    return engine


def _clamp01(value: float) -> float:
    return _engine()._clamp01(value)


def _compute_reliability(*, verdict, breakdown):
    return _engine()._compute_reliability(verdict=verdict, breakdown=breakdown)


def _add_unknown_reasons(req_stats, reasons):
    return _engine()._add_unknown_reasons(req_stats, reasons)
