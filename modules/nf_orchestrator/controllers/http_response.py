from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from modules.nf_shared.protocol.serialization import dump_json


def send_json(handler, code: HTTPStatus, payload: Any) -> None:
    body = json.dumps(dump_json(payload), ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_app_error(
    handler,
    code: HTTPStatus,
    error_code,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "error": {
            "code": error_code.value,
            "message": message,
            "details": details or {},
        }
    }
    send_json(handler, code, payload)
