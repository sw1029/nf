"""
Workers placeholder.

Responsibilities (planned):
- Job runner (INGEST/INDEX/CONSISTENCY/RETRIEVE_VEC/SUGGEST/PROOFREAD/EXPORT)
- Heartbeat/lease/cancel handling
"""

__version__ = "0.0.0-placeholder"

from .runner import run_worker  # noqa: F401

