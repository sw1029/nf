"""
Model gateway placeholder.

Responsibilities (planned):
- Safety gate (evidence_required), rate limiting, circuit breaker
- Local small models (ONNX), optional local generators, remote API clients
"""

__version__ = "0.0.0-placeholder"

from .gateway import select_model  # noqa: F401

