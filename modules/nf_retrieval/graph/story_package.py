from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Mapping

PACKAGE_FORMAT = "nf-story-package-v1"
DEFAULT_CONTENT_KIND = "knowledge_graph"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def make_story_package(
    *,
    display_name: str,
    payload: Mapping[str, Any],
    content_kind: str = DEFAULT_CONTENT_KIND,
    payload_encoding: str = "obfuscated-v1",
) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if payload_encoding == "json-v1":
        encoded_payload: Any = dict(payload)
        security = {"mode": "none"}
    elif payload_encoding == "obfuscated-v1":
        encoded_payload = _b64url_encode(raw)
        security = {"mode": "obfuscated"}
    else:
        raise ValueError(f"unsupported payload_encoding: {payload_encoding}")
    return {
        "format": PACKAGE_FORMAT,
        "content_kind": content_kind,
        "display_name": str(display_name or "작품 정리 파일"),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "payload_encoding": payload_encoding,
        "security": security,
        "payload": encoded_payload,
    }


def decode_story_package(package: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if package.get("format") != PACKAGE_FORMAT:
        raise ValueError("지원하지 않는 작품 정리 파일입니다")
    content_kind = str(package.get("content_kind") or DEFAULT_CONTENT_KIND)
    encoding = str(package.get("payload_encoding") or "json-v1")
    payload = package.get("payload")
    if encoding == "json-v1":
        if not isinstance(payload, dict):
            raise ValueError("작품 정리 파일 payload가 올바르지 않습니다")
        return content_kind, dict(payload)
    if encoding == "obfuscated-v1":
        if not isinstance(payload, str):
            raise ValueError("작품 정리 파일 payload가 올바르지 않습니다")
        decoded = json.loads(_b64url_decode(payload).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("작품 정리 파일 payload가 올바르지 않습니다")
        return content_kind, decoded
    if encoding == "encrypted-aes-gcm-v1":
        raise ValueError("비밀번호가 있는 작품 정리 파일은 브라우저에서 먼저 열어야 합니다")
    raise ValueError("지원하지 않는 작품 정리 파일 인코딩입니다")
