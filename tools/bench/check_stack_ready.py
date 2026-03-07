from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from urllib import parse

from http_client import ApiClient, submit_and_wait


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an orchestrator stack can complete a lightweight job round-trip.")
    parser.add_argument("--base-url", required=True, help="Base orchestrator URL, e.g. http://127.0.0.1:8085")
    parser.add_argument("--timeout-sec", type=float, default=8.0, help="Total probe timeout in seconds.")
    parser.add_argument("--label", default="ready", help="Short label used in the temporary project name.")
    parser.add_argument("--quiet", action="store_true", help="Suppress success output.")
    return parser.parse_args()


def _wait_for_health(client: ApiClient, *, timeout_sec: float) -> tuple[bool, dict[str, object]]:
    deadline = time.perf_counter() + max(1.0, timeout_sec)
    last_error = ""
    while time.perf_counter() < deadline:
        try:
            payload = client.get("/health")
            return True, {"health": payload}
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(0.25)
    return False, {"health_error": last_error or "health probe timed out"}


def probe_stack_ready(client: ApiClient, *, probe_label: str, timeout_sec: float) -> dict[str, object]:
    started = time.perf_counter()
    health_ok, health_detail = _wait_for_health(client, timeout_sec=min(timeout_sec, 5.0))
    result: dict[str, object] = {
        "ok": False,
        "base_url": client.base_url,
        "label": probe_label,
        "health_ok": health_ok,
        **health_detail,
    }
    if not health_ok:
        result["stage"] = "health"
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        return result

    project_name = f"bench-ready-probe:{probe_label}:{uuid.uuid4().hex[:8]}"
    project_id = ""
    cleanup_error = ""
    try:
        created = client.post("/projects", {"name": project_name, "settings": {"mode": "bench-ready-probe"}})
        project = created.get("project") or {}
        project_id = str(project.get("project_id") or "")
        if not project_id:
            result["stage"] = "create_project"
            result["error"] = "project_id missing"
            return result

        remaining_timeout = max(1.0, timeout_sec - (time.perf_counter() - started))
        run = submit_and_wait(
            client,
            project_id=project_id,
            job_type="INDEX_FTS",
            inputs={"scope": "global"},
            params={},
            timeout_sec=remaining_timeout,
        )
        result["project_id"] = project_id
        result["job_id"] = run.job_id
        result["job_status"] = run.status
        result["job_elapsed_ms"] = round(run.elapsed_ms, 2)
        result["ok"] = run.status == "SUCCEEDED"
        if not result["ok"]:
            result["stage"] = "job_roundtrip"
            result["error"] = f"job finished with status={run.status}"
        else:
            result["stage"] = "completed"
        return result
    except Exception as exc:  # noqa: BLE001
        result["stage"] = "job_roundtrip"
        result["error"] = str(exc)
        if project_id:
            result["project_id"] = project_id
        return result
    finally:
        if project_id:
            try:
                client.delete(f"/projects/{parse.quote(project_id)}")
            except Exception as exc:  # noqa: BLE001
                cleanup_error = str(exc)
        if cleanup_error:
            result["cleanup_error"] = cleanup_error
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 2)


def main() -> int:
    args = _parse_args()
    client = ApiClient(args.base_url, timeout=max(3.0, min(15.0, float(args.timeout_sec))))
    result = probe_stack_ready(client, probe_label=str(args.label or "ready"), timeout_sec=max(1.0, float(args.timeout_sec)))
    payload = json.dumps(result, ensure_ascii=False)
    if result.get("ok"):
        if not args.quiet:
            print(payload)
        return 0
    print(payload, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
