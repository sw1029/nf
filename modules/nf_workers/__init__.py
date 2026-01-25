"""
워커 placeholder.

책임(예정):
- 잡 실행기(INGEST/INDEX/CONSISTENCY/RETRIEVE_VEC/SUGGEST/PROOFREAD/EXPORT)
- 하트비트/리스/취소 처리
"""

__version__ = "0.0.0-placeholder"

from .runner import run_worker  # noqa: F401
