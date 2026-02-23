"""
Orchestrator (loopback HTTP) core.

Responsibilities:
- Projects CRUD
- Job submission/status/events (SSE)
- Loopback-only access with optional token
"""

__version__ = "0.1.0"

from .main import run_orchestrator  # noqa: F401
