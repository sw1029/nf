from __future__ import annotations


def has_evidence(bundle: dict) -> bool:
    return bool(bundle.get("evidence"))
