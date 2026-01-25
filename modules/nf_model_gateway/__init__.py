"""
모델 게이트웨이 placeholder.

책임(예정):
- 안전 게이트(evidence_required), 레이트 리밋, 서킷 브레이커
- 로컬 소형 모델(ONNX), 선택형 로컬 생성기, 원격 API 클라이언트
"""

__version__ = "0.0.0-placeholder"

from .gateway import select_model  # noqa: F401
