from __future__ import annotations

import io
import json
from http import HTTPStatus

import pytest

from modules.nf_orchestrator.controllers import http_response
from modules.nf_shared.errors import ErrorCode


class _FakeHandler:
    def __init__(self) -> None:
        self.status_code: int | None = None
        self.headers: dict[str, str] = {}
        self.wfile = io.BytesIO()

    def send_response(self, code: HTTPStatus) -> None:
        self.status_code = int(code)

    def send_header(self, key: str, value: str) -> None:
        self.headers[key] = value

    def end_headers(self) -> None:
        return


@pytest.mark.unit
def test_send_json_serializes_mapping_payload() -> None:
    handler = _FakeHandler()
    payload = {"ok": True, "nested": {"x": 1}}

    http_response.send_json(handler, HTTPStatus.OK, payload)

    assert handler.status_code == int(HTTPStatus.OK)
    assert handler.headers["Content-Type"] == "application/json; charset=utf-8"
    raw = handler.wfile.getvalue().decode("utf-8")
    assert json.loads(raw) == payload


@pytest.mark.unit
def test_send_app_error_serializes_error_object() -> None:
    handler = _FakeHandler()

    http_response.send_app_error(
        handler,
        HTTPStatus.NOT_FOUND,
        ErrorCode.NOT_FOUND,
        "missing",
        {"rid": "1"},
    )

    assert handler.status_code == int(HTTPStatus.NOT_FOUND)
    body = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert body["error"]["code"] == ErrorCode.NOT_FOUND.value
    assert body["error"]["message"] == "missing"
    assert body["error"]["details"] == {"rid": "1"}
