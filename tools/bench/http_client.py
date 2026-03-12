from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class ApiRequestError(RuntimeError):
    def __init__(
        self,
        *,
        base_url: str,
        method: str,
        path: str,
        error_class: str,
        detail: str,
        status_code: int | None = None,
        request_body_shape: dict[str, Any] | None = None,
        retry_count: int = 0,
        retryable: bool = False,
        backoff_total_sec: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.method = method
        self.path = path
        self.error_class = error_class
        self.detail = detail
        self.status_code = status_code
        self.request_body_shape = request_body_shape or {}
        self.retry_count = int(retry_count)
        self.retryable = bool(retryable)
        self.backoff_total_sec = float(backoff_total_sec)
        super().__init__(f"{error_class} {method} {path}: {detail}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "method": self.method,
            "request_path": self.path,
            "error_class": self.error_class,
            "detail": self.detail,
            "status_code": self.status_code,
            "request_body_shape": self.request_body_shape,
            "retry_count": self.retry_count,
            "retryable": self.retryable,
            "backoff_total_sec": self.backoff_total_sec,
        }


class ApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
        request_retries: int = 1,
        retry_backoff_sec: float = 0.25,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.request_retries = max(0, int(request_retries))
        self.retry_backoff_sec = max(0.0, float(retry_backoff_sec))

    @staticmethod
    def _request_body_shape(body: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(body, dict):
            return {}
        shape: dict[str, Any] = {}
        for key, value in body.items():
            key_str = str(key)
            if isinstance(value, dict):
                shape[key_str] = sorted(str(item) for item in value.keys())
            elif isinstance(value, list):
                shape[key_str] = f"list[{len(value)}]"
            else:
                shape[key_str] = type(value).__name__
        return shape

    @staticmethod
    def _is_retryable(method: str, path: str, exc: Exception) -> bool:
        if method.upper() == "GET":
            return True
        if method.upper() != "POST":
            return False
        if path in {"/projects", "/query/retrieval"}:
            return True
        return False

    def _request_once(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(url=url, method=method, data=data, headers=headers)
        with request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw) if raw else {}

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        attempts = self.request_retries + 1
        last_exc: Exception | None = None
        request_body_shape = self._request_body_shape(body)
        backoff_total_sec = 0.0
        for attempt in range(attempts):
            try:
                return self._request_once(method, path, body)
            except error.HTTPError as exc:
                payload = exc.read().decode("utf-8", errors="ignore")
                last_exc = ApiRequestError(
                    base_url=self.base_url,
                    method=method,
                    path=path,
                    error_class=type(exc).__name__,
                    detail=payload or f"HTTP {exc.code}",
                    status_code=int(exc.code),
                    request_body_shape=request_body_shape,
                )
            except error.URLError as exc:
                last_exc = ApiRequestError(
                    base_url=self.base_url,
                    method=method,
                    path=path,
                    error_class=type(exc).__name__,
                    detail=str(exc.reason),
                    request_body_shape=request_body_shape,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = ApiRequestError(
                    base_url=self.base_url,
                    method=method,
                    path=path,
                    error_class=type(exc).__name__,
                    detail=str(exc),
                    request_body_shape=request_body_shape,
                )
            retryable = bool(last_exc is not None and self._is_retryable(method, path, last_exc))
            if last_exc is None or attempt >= (attempts - 1) or not retryable:
                assert last_exc is not None
                last_exc.retry_count = attempt
                last_exc.retryable = retryable
                last_exc.backoff_total_sec = backoff_total_sec
                raise last_exc
            backoff = self.retry_backoff_sec * float(attempt + 1)
            backoff_total_sec += backoff
            time.sleep(backoff)
        assert last_exc is not None
        raise last_exc

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, body)

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", path, body)

    def delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path)

    def get_text(self, path: str) -> str:
        url = self.base_url + path
        req = request.Request(url=url, method="GET")
        attempts = self.request_retries + 1
        last_exc: Exception | None = None
        backoff_total_sec = 0.0
        for attempt in range(attempts):
            try:
                with request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8", errors="ignore")
            except error.HTTPError as exc:
                payload = exc.read().decode("utf-8", errors="ignore")
                last_exc = ApiRequestError(
                    base_url=self.base_url,
                    method="GET",
                    path=path,
                    error_class=type(exc).__name__,
                    detail=payload or f"HTTP {exc.code}",
                    status_code=int(exc.code),
                    request_body_shape={},
                )
            except error.URLError as exc:
                last_exc = ApiRequestError(
                    base_url=self.base_url,
                    method="GET",
                    path=path,
                    error_class=type(exc).__name__,
                    detail=str(exc.reason),
                    request_body_shape={},
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = ApiRequestError(
                    base_url=self.base_url,
                    method="GET",
                    path=path,
                    error_class=type(exc).__name__,
                    detail=str(exc),
                    request_body_shape={},
                )
            retryable = bool(last_exc is not None and self._is_retryable("GET", path, last_exc))
            if last_exc is None or attempt >= (attempts - 1) or not retryable:
                assert last_exc is not None
                last_exc.retry_count = attempt
                last_exc.retryable = retryable
                last_exc.backoff_total_sec = backoff_total_sec
                raise last_exc
            backoff = self.retry_backoff_sec * float(attempt + 1)
            backoff_total_sec += backoff
            time.sleep(backoff)
        assert last_exc is not None
        raise last_exc


@dataclass
class JobRun:
    job_id: str
    status: str
    elapsed_ms: float


def wait_for_job(client: ApiClient, job_id: str, *, poll_sec: float = 0.5, timeout_sec: float = 7200.0) -> JobRun:
    start = time.perf_counter()
    while True:
        res = client.get(f"/jobs/{parse.quote(job_id)}")
        job = res.get("job") or {}
        status = str(job.get("status") or "")
        if status in {"SUCCEEDED", "FAILED", "CANCELED"}:
            return JobRun(job_id=job_id, status=status, elapsed_ms=(time.perf_counter() - start) * 1000.0)
        if (time.perf_counter() - start) > timeout_sec:
            return JobRun(job_id=job_id, status="TIMEOUT", elapsed_ms=(time.perf_counter() - start) * 1000.0)
        time.sleep(poll_sec)


def submit_and_wait(
    client: ApiClient,
    *,
    project_id: str,
    job_type: str,
    inputs: dict[str, Any],
    params: dict[str, Any] | None = None,
    timeout_sec: float = 7200.0,
) -> JobRun:
    created = client.post(
        "/jobs",
        {
            "project_id": project_id,
            "type": job_type,
            "inputs": inputs,
            "params": params or {},
        },
    )
    job = created.get("job") or {}
    job_id = str(job.get("job_id") or "")
    if not job_id:
        raise RuntimeError("job_id missing")
    return wait_for_job(client, job_id, timeout_sec=timeout_sec)
