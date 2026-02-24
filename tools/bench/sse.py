from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request


def parse_sse_events(raw: str) -> list[tuple[int, dict[str, Any]]]:
    if not raw:
        return []
    out: list[tuple[int, dict[str, Any]]] = []
    current_id: int | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal current_id, data_lines
        if not data_lines:
            current_id = None
            return
        data_raw = "\n".join(data_lines).strip()
        data_lines = []
        if not data_raw:
            current_id = None
            return
        try:
            payload = json.loads(data_raw)
        except json.JSONDecodeError:
            current_id = None
            return
        if isinstance(payload, dict):
            out.append((int(current_id or 0), payload))
        current_id = None

    for line in raw.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("id:"):
            try:
                current_id = int(line.split(":", 1)[1].strip())
            except (TypeError, ValueError):
                current_id = None
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())
            continue
        if not line.strip():
            flush()
    flush()
    return out


def read_job_events(
    *,
    base_url: str,
    job_id: str,
    after_seq: int = 0,
    timeout: float = 60.0,
) -> list[tuple[int, dict[str, Any]]]:
    url = base_url.rstrip("/") + f"/jobs/{parse.quote(job_id)}/events?after={after_seq}"
    req = request.Request(url=url, method="GET")

    out: list[tuple[int, dict[str, Any]]] = []
    current_id: int | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal current_id, data_lines
        if not data_lines:
            current_id = None
            return
        data_raw = "\n".join(data_lines).strip()
        data_lines = []
        if not data_raw:
            current_id = None
            return
        try:
            payload = json.loads(data_raw)
        except json.JSONDecodeError:
            current_id = None
            return
        if isinstance(payload, dict):
            out.append((int(current_id or 0), payload))
        current_id = None

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            while True:
                raw_line = resp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
                if line.startswith(":"):
                    if line.startswith(": keep-alive"):
                        break
                    continue
                if line.startswith("id:"):
                    try:
                        current_id = int(line.split(":", 1)[1].strip())
                    except (TypeError, ValueError):
                        current_id = None
                    continue
                if line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
                    continue
                if not line.strip():
                    flush()
    except TimeoutError:
        pass
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code} /jobs/{job_id}/events: {payload}") from exc

    flush()
    return out
