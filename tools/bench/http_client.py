from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class ApiClient:
    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(url=url, method=method, data=data, headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code} {path}: {payload}") from exc

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, body)

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", path, body)

    def get_text(self, path: str) -> str:
        url = self.base_url + path
        req = request.Request(url=url, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code} {path}: {payload}") from exc


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
