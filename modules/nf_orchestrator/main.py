from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from modules.nf_orchestrator.services.job_service import JobServiceImpl
from modules.nf_orchestrator.services.project_service import ProjectServiceImpl
from modules.nf_shared.errors import AppError, ErrorCode
from modules.nf_shared.protocol.dtos import JobEvent, JobType
from modules.nf_shared.protocol.serialization import dump_json


_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


class OrchestratorHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, *, token: str | None = None) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.project_service = ProjectServiceImpl()
        self.job_service = JobServiceImpl()
        self.token = token


class OrchestratorHandler(BaseHTTPRequestHandler):
    server: OrchestratorHTTPServer

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        if not self._enforce_loopback():
            return
        if not self._authorize():
            return

        path = urlparse(self.path).path
        segments = [seg for seg in path.split("/") if seg]

        try:
            if self.command == "GET" and path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return

            if segments[:1] == ["projects"]:
                self._handle_projects(segments)
                return

            if segments[:1] == ["jobs"]:
                self._handle_jobs(segments)
                return

            self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "찾을 수 없음")
        except AppError as exc:
            self._send_app_error(HTTPStatus.BAD_REQUEST, exc.code, exc.message, exc.details)

    def _handle_projects(self, segments: list[str]) -> None:
        if len(segments) == 1:
            if self.command == "GET":
                projects = self.server.project_service.list_projects()
                self._send_json(HTTPStatus.OK, {"projects": dump_json(projects)})
                return
            if self.command == "POST":
                payload = self._read_json()
                name = payload.get("name")
                if not isinstance(name, str) or not name.strip():
                    raise AppError(ErrorCode.VALIDATION_ERROR, "name이 필요합니다")
                settings = payload.get("settings") or {}
                if not isinstance(settings, dict):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "settings는 객체여야 합니다")
                project = self.server.project_service.create_project(name.strip(), settings)
                self._send_json(HTTPStatus.CREATED, {"project": dump_json(project)})
                return

        if len(segments) == 2:
            project_id = segments[1]
            if self.command == "GET":
                project = self.server.project_service.get_project(project_id)
                if project is None:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "프로젝트를 찾을 수 없습니다")
                    return
                self._send_json(HTTPStatus.OK, {"project": dump_json(project)})
                return
            if self.command == "PATCH":
                payload = self._read_json()
                name = payload.get("name")
                settings = payload.get("settings")
                if name is not None and not isinstance(name, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "name은 문자열이어야 합니다")
                if settings is not None and not isinstance(settings, dict):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "settings는 객체여야 합니다")
                project = self.server.project_service.update_project(project_id, name, settings)
                if project is None:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "프로젝트를 찾을 수 없습니다")
                    return
                self._send_json(HTTPStatus.OK, {"project": dump_json(project)})
                return
            if self.command == "DELETE":
                deleted = self.server.project_service.delete_project(project_id)
                if not deleted:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "프로젝트를 찾을 수 없습니다")
                    return
                self._send_json(HTTPStatus.OK, {"deleted": True})
                return

        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_jobs(self, segments: list[str]) -> None:
        if len(segments) == 1:
            if self.command != "POST":
                self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
                return
            payload = self._read_json()
            job_type_raw = payload.get("type")
            project_id = payload.get("project_id")
            if not isinstance(job_type_raw, str) or not isinstance(project_id, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "type과 project_id가 필요합니다")
            try:
                job_type = JobType(job_type_raw)
            except ValueError as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"지원하지 않는 job type: {job_type_raw}") from exc

            project = self.server.project_service.get_project(project_id)
            if project is None:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "프로젝트를 찾을 수 없습니다")
                return
            inputs = payload.get("inputs") or {}
            params = payload.get("params") or {}
            if not isinstance(inputs, dict) or not isinstance(params, dict):
                raise AppError(ErrorCode.VALIDATION_ERROR, "inputs와 params는 객체여야 합니다")
            job = self.server.job_service.submit(project_id, job_type, inputs, params)
            self._send_json(HTTPStatus.CREATED, {"job": dump_json(job)})
            return

        if len(segments) == 2:
            job_id = segments[1]
            if self.command == "GET":
                job = self.server.job_service.get(job_id)
                if job is None:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "잡을 찾을 수 없습니다")
                    return
                self._send_json(HTTPStatus.OK, {"job": dump_json(job)})
                return

        if len(segments) == 3 and segments[2] == "cancel":
            job_id = segments[1]
            if self.command != "POST":
                self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
                return
            job = self.server.job_service.cancel(job_id)
            if job is None:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "잡을 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"job": dump_json(job)})
            return

        if len(segments) == 3 and segments[2] == "events":
            job_id = segments[1]
            if self.command != "GET":
                self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
                return
            self._stream_job_events(job_id)
            return

        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _stream_job_events(self, job_id: str) -> None:
        job = self.server.job_service.get(job_id)
        if job is None:
            self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "잡을 찾을 수 없습니다")
            return

        after_seq = 0
        last_event_id = self.headers.get("Last-Event-ID")
        if last_event_id:
            try:
                after_seq = int(last_event_id)
            except ValueError:
                after_seq = 0
        else:
            query = urlparse(self.path).query
            params = parse_qs(query)
            after = params.get("after", ["0"])[0]
            try:
                after_seq = int(after)
            except ValueError:
                after_seq = 0

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        events = self.server.job_service.list_events(job_id, after_seq=after_seq)
        for seq, event in events:
            self._write_sse_event(seq, event)
        self.wfile.write(b": keep-alive\n\n")

    def _write_sse_event(self, seq: int, event: JobEvent) -> None:
        payload = json.dumps(dump_json(event), ensure_ascii=False)
        self.wfile.write(f"id: {seq}\n".encode("utf-8"))
        self.wfile.write(b"event: message\n")
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, "유효하지 않은 JSON 본문") from exc
        if not isinstance(payload, dict):
            raise AppError(ErrorCode.VALIDATION_ERROR, "JSON 본문은 객체여야 합니다")
        return payload

    def _authorize(self) -> bool:
        token = self.server.token
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth.split(" ", 1)[1] == token:
            return True
        if self.headers.get("X-NF-Token") == token:
            return True
        self._send_app_error(HTTPStatus.UNAUTHORIZED, ErrorCode.POLICY_VIOLATION, "인증되지 않음")
        return False

    def _enforce_loopback(self) -> bool:
        if self.client_address[0] in _LOOPBACK_HOSTS:
            return True
        self._send_app_error(HTTPStatus.FORBIDDEN, ErrorCode.POLICY_VIOLATION, "루프백만 허용")
        return False

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_app_error(
        self,
        status: HTTPStatus,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        err = AppError(code, message, details)
        self._send_json(status, err.to_dict())

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def run_orchestrator(host: str = "127.0.0.1", port: int = 8080) -> None:
    """
    오케스트레이터 API 서버 실행(루프백 HTTP).
    """
    token = os.environ.get("NF_ORCHESTRATOR_TOKEN")
    server = OrchestratorHTTPServer((host, port), OrchestratorHandler, token=token)
    server.serve_forever()
