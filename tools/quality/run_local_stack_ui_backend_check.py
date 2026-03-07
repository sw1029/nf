from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _http_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    url = f"{base_url}{path}"
    req_headers = dict(headers or {})
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            text = raw.decode("utf-8", errors="replace")
            parsed = None
            ctype = response.headers.get("Content-Type", "")
            if "application/json" in ctype:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None
            return {
                "ok": True,
                "status": int(response.status),
                "content_type": ctype,
                "text": text,
                "json": parsed,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        text = raw.decode("utf-8", errors="replace")
        parsed = None
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        if "application/json" in ctype:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        return {
            "ok": False,
            "status": int(exc.code),
            "content_type": ctype,
            "text": text,
            "json": parsed,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": None,
            "content_type": "",
            "text": str(exc),
            "json": None,
        }


def _wait_health(base_url: str, *, token: str | None = None, timeout_s: float = 15.0) -> tuple[bool, dict[str, Any]]:
    deadline = time.time() + timeout_s
    path = "/health"
    if token:
        encoded = urllib.parse.quote(token, safe="")
        path = f"/health?token={encoded}"
    last = _http_request(base_url, path)
    while time.time() < deadline:
        if (
            last.get("status") == 200
            and isinstance(last.get("json"), dict)
            and last["json"].get("status") == "ok"
        ):
            return True, last
        time.sleep(0.25)
        last = _http_request(base_url, path)
    return False, last


class _LocalStack:
    def __init__(
        self,
        *,
        repo_root: Path,
        port: int,
        db_path: Path,
        no_worker: bool,
        api_token: str = "",
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.port = port
        self.db_path = db_path
        self.no_worker = no_worker
        self.api_token = api_token
        self.extra_env = dict(extra_env or {})
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        env = os.environ.copy()
        env.update(self.extra_env)
        args = [
            sys.executable,
            "run_local_stack.py",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--db-path",
            str(self.db_path),
        ]
        if self.no_worker:
            args.append("--no-worker")
        if self.api_token:
            args.extend(["--api-token", self.api_token])
        self.proc = subprocess.Popen(
            args,
            cwd=str(self.repo_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        self._cleanup_db_files()

    def _cleanup_db_files(self) -> None:
        for suffix in ("", "-shm", "-wal"):
            target = Path(str(self.db_path) + suffix)
            try:
                target.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass


def _scenario_default_worker(repo_root: Path) -> dict[str, Any]:
    port = _free_port()
    db_path = Path(tempfile.gettempdir()) / f"nf_verify_default_{int(time.time() * 1000)}.sqlite3"
    stack = _LocalStack(repo_root=repo_root, port=port, db_path=db_path, no_worker=False)
    base_url = f"http://127.0.0.1:{port}"
    try:
        stack.start()
        health_ok, health_res = _wait_health(base_url)
        return {
            "pass": bool(health_ok),
            "health_ok": bool(health_ok),
            "health_status": health_res.get("status"),
            "health_body": health_res.get("json"),
        }
    finally:
        stack.stop()


def _scenario_normal_and_forced_failure(repo_root: Path) -> dict[str, Any]:
    port = _free_port()
    db_path = Path(tempfile.gettempdir()) / f"nf_verify_normal_{int(time.time() * 1000)}.sqlite3"
    stack = _LocalStack(
        repo_root=repo_root,
        port=port,
        db_path=db_path,
        no_worker=True,
        extra_env={
            "NF_ENABLE_DEBUG_WEB_UI": "1",
            "NF_DEBUG_WEB_UI_TOKEN": "verifytoken",
        },
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        stack.start()
        health_ok, _ = _wait_health(base_url)
        root = _http_request(base_url, "/")
        asset = _http_request(base_url, "/assets/user_ui.api.js")
        projects_before = _http_request(base_url, "/projects")
        created_project = _http_request(
            base_url,
            "/projects",
            method="POST",
            body={"name": "integration-check", "settings": {"mode": "dev"}},
        )
        project_id = (
            (created_project.get("json") or {}).get("project", {}).get("project_id")
            if isinstance(created_project.get("json"), dict)
            else None
        )
        docs = (
            _http_request(base_url, f"/projects/{project_id}/documents")
            if isinstance(project_id, str) and project_id
            else {"status": None}
        )
        segment_rules = _http_request(base_url, "/query/segment-rules")
        jobs = _http_request(base_url, "/jobs")
        openapi = _http_request(base_url, "/openapi.json")
        debug_toggle = _http_request(
            base_url,
            "/_debug/toggles?debug_token=verifytoken",
            method="PATCH",
            body={"force_error_code": 503},
        )
        forced_projects = _http_request(base_url, "/projects")
        recovered_projects = _http_request(base_url, "/projects")

        checks = {
            "health_ok": bool(health_ok),
            "root_status": root.get("status"),
            "root_has_setup_modal": 'id="setup-modal"' in str(root.get("text", "")),
            "asset_status": asset.get("status"),
            "asset_has_api_helper": 'async function api(path, method = "GET", body = null)' in str(asset.get("text", "")),
            "projects_get_status": projects_before.get("status"),
            "create_project_status": created_project.get("status"),
            "create_project_has_id": bool(project_id),
            "docs_status": docs.get("status"),
            "segment_rules_status": segment_rules.get("status"),
            "jobs_status": jobs.get("status"),
            "openapi_status": openapi.get("status"),
            "openapi_has_projects_path": bool((openapi.get("json") or {}).get("paths", {}).get("/projects")),
            "debug_toggle_status": debug_toggle.get("status"),
            "forced_projects_status": forced_projects.get("status"),
            "forced_error_code": ((forced_projects.get("json") or {}).get("error") or {}).get("code"),
            "forced_error_message": ((forced_projects.get("json") or {}).get("error") or {}).get("message"),
            "recovered_projects_status": recovered_projects.get("status"),
        }
        all_expected = (
            checks["health_ok"]
            and checks["root_status"] == 200
            and checks["root_has_setup_modal"]
            and checks["asset_status"] == 200
            and checks["asset_has_api_helper"]
            and checks["projects_get_status"] == 200
            and checks["create_project_status"] == 201
            and checks["create_project_has_id"]
            and checks["docs_status"] == 200
            and checks["segment_rules_status"] == 200
            and checks["jobs_status"] == 200
            and checks["openapi_status"] == 200
            and checks["openapi_has_projects_path"]
            and checks["debug_toggle_status"] == 200
            and checks["forced_projects_status"] == 503
            and checks["forced_error_code"] == "POLICY_VIOLATION"
            and checks["forced_error_message"] == "debug forced error"
            and checks["recovered_projects_status"] == 200
        )
        checks["pass"] = bool(all_expected)
        return checks
    finally:
        stack.stop()


def _scenario_token_auth(repo_root: Path) -> dict[str, Any]:
    port = _free_port()
    db_path = Path(tempfile.gettempdir()) / f"nf_verify_auth_{int(time.time() * 1000)}.sqlite3"
    token = "secret-token"
    stack = _LocalStack(repo_root=repo_root, port=port, db_path=db_path, no_worker=True, api_token=token)
    base_url = f"http://127.0.0.1:{port}"
    try:
        stack.start()
        health_ok, _ = _wait_health(base_url, token=token)
        root_without_token = _http_request(base_url, "/")
        projects_without_token = _http_request(base_url, "/projects")
        root_with_query_token = _http_request(base_url, "/?token=secret-token")
        projects_with_auth_header = _http_request(
            base_url,
            "/projects",
            headers={"Authorization": "Bearer secret-token"},
        )
        unauthorized_code = ((projects_without_token.get("json") or {}).get("error") or {}).get("code")
        checks = {
            "health_ok": bool(health_ok),
            "root_without_token_status": root_without_token.get("status"),
            "projects_without_token_status": projects_without_token.get("status"),
            "root_with_query_token_status": root_with_query_token.get("status"),
            "projects_with_auth_header_status": projects_with_auth_header.get("status"),
            "unauthorized_error_code": unauthorized_code,
        }
        checks["pass"] = bool(
            checks["health_ok"]
            and checks["root_without_token_status"] == 401
            and checks["projects_without_token_status"] == 401
            and checks["root_with_query_token_status"] == 200
            and checks["projects_with_auth_header_status"] == 200
            and checks["unauthorized_error_code"] == "POLICY_VIOLATION"
        )
        return checks
    finally:
        stack.stop()


def _scenario_tag_assignments_runtime(repo_root: Path) -> dict[str, Any]:
    port = _free_port()
    db_path = Path(tempfile.gettempdir()) / f"nf_verify_tags_{int(time.time() * 1000)}.sqlite3"
    stack = _LocalStack(repo_root=repo_root, port=port, db_path=db_path, no_worker=True)
    base_url = f"http://127.0.0.1:{port}"
    try:
        stack.start()
        health_ok, _ = _wait_health(base_url)
        created_project = _http_request(
            base_url,
            "/projects",
            method="POST",
            body={"name": "tags-runtime-check", "settings": {}},
        )
        project_id = (
            (created_project.get("json") or {}).get("project", {}).get("project_id")
            if isinstance(created_project.get("json"), dict)
            else None
        )
        created_doc = (
            _http_request(
                base_url,
                f"/projects/{project_id}/documents",
                method="POST",
                body={"title": "doc", "type": "EPISODE", "content": "x"},
            )
            if isinstance(project_id, str) and project_id
            else {"status": None}
        )
        doc_id = (
            (created_doc.get("json") or {}).get("document", {}).get("doc_id")
            if isinstance(created_doc.get("json"), dict)
            else None
        )
        loaded_doc = (
            _http_request(base_url, f"/projects/{project_id}/documents/{doc_id}")
            if isinstance(project_id, str) and project_id and isinstance(doc_id, str) and doc_id
            else {"status": None}
        )
        snapshot_id = (
            (loaded_doc.get("json") or {}).get("document", {}).get("head_snapshot_id")
            if isinstance(loaded_doc.get("json"), dict)
            else None
        )
        assignments = (
            _http_request(
                base_url,
                f"/projects/{project_id}/tags/assignments?doc_id={urllib.parse.quote(doc_id, safe='')}&snapshot_id={urllib.parse.quote(snapshot_id, safe='')}",
            )
            if isinstance(project_id, str)
            and project_id
            and isinstance(doc_id, str)
            and doc_id
            and isinstance(snapshot_id, str)
            and snapshot_id
            else {"status": None, "json": None}
        )
        assignments_payload = assignments.get("json") if isinstance(assignments.get("json"), dict) else {}
        checks = {
            "health_ok": bool(health_ok),
            "create_project_status": created_project.get("status"),
            "create_doc_status": created_doc.get("status"),
            "load_doc_status": loaded_doc.get("status"),
            "head_snapshot_id_exists": bool(snapshot_id),
            "assignments_status": assignments.get("status"),
            "assignments_is_list": isinstance(assignments_payload.get("assignments"), list),
        }
        checks["pass"] = bool(
            checks["health_ok"]
            and checks["create_project_status"] == 201
            and checks["create_doc_status"] == 201
            and checks["load_doc_status"] == 200
            and checks["head_snapshot_id_exists"]
            and checks["assignments_status"] == 200
            and checks["assignments_is_list"]
        )
        return checks
    finally:
        stack.stop()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify run_local_stack UI-backend integration checks.")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Repository root path (default: project root).",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional output path for JSON report.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).resolve()
    if not (repo_root / "run_local_stack.py").exists():
        raise FileNotFoundError(f"run_local_stack.py not found under repo root: {repo_root}")

    report: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo_root": str(repo_root),
        "checks": {
            "startup_default_worker": _scenario_default_worker(repo_root),
            "normal_integration_and_forced_failure": _scenario_normal_and_forced_failure(repo_root),
            "token_auth_behavior": _scenario_token_auth(repo_root),
            "tag_assignments_runtime": _scenario_tag_assignments_runtime(repo_root),
        },
    }
    report["overall_pass"] = all(bool(item.get("pass")) for item in report["checks"].values())

    if args.json_out.strip():
        out_path = Path(args.json_out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
