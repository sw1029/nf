from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from urllib import error

import pytest


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("http_client")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


@pytest.mark.unit
def test_api_client_retries_get_on_transient_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()
    calls = {"count": 0}

    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            raise error.URLError("connection reset")
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(mod.request, "urlopen", fake_urlopen)
    client = mod.ApiClient("http://127.0.0.1:8085", request_retries=1, retry_backoff_sec=0.0)

    payload = client.get("/health")

    assert payload == {"ok": True}
    assert calls["count"] == 2


@pytest.mark.unit
def test_api_client_retries_post_projects_on_transient_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()
    calls = {"count": 0}

    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            raise error.URLError("temporarily unavailable")
        return _FakeResponse({"project": {"project_id": "project-1"}})

    monkeypatch.setattr(mod.request, "urlopen", fake_urlopen)
    client = mod.ApiClient("http://127.0.0.1:8085", request_retries=1, retry_backoff_sec=0.0)

    payload = client.post("/projects", {"name": "bench"})

    assert payload["project"]["project_id"] == "project-1"
    assert calls["count"] == 2


@pytest.mark.unit
def test_api_client_does_not_retry_post_jobs_on_transient_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()
    calls = {"count": 0}

    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        calls["count"] += 1
        raise error.URLError("temporarily unavailable")

    monkeypatch.setattr(mod.request, "urlopen", fake_urlopen)
    client = mod.ApiClient("http://127.0.0.1:8085", request_retries=1, retry_backoff_sec=0.0)

    with pytest.raises(mod.ApiRequestError):
        client.post("/jobs", {"type": "INDEX_VEC"})

    assert calls["count"] == 1


@pytest.mark.unit
def test_api_request_error_records_retry_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()
    calls = {"count": 0}

    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        calls["count"] += 1
        raise error.URLError("temporarily unavailable")

    monkeypatch.setattr(mod.request, "urlopen", fake_urlopen)
    client = mod.ApiClient("http://127.0.0.1:8085", request_retries=2, retry_backoff_sec=0.0)

    with pytest.raises(mod.ApiRequestError) as exc_info:
        client.post("/projects", {"name": "bench"})

    exc = exc_info.value
    assert calls["count"] == 3
    assert exc.retry_count == 2
    assert exc.retryable is True
    assert exc.request_body_shape == {"name": "str"}
