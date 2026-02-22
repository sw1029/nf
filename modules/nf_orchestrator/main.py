from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from modules.nf_orchestrator.services.document_service import DocumentServiceImpl
from modules.nf_orchestrator.services.entity_service import EntityServiceImpl
from modules.nf_orchestrator.services.episode_service import EpisodeServiceImpl
from modules.nf_orchestrator.services.extraction_service import ExtractionServiceImpl
from modules.nf_orchestrator.services.ignore_service import IgnoreServiceImpl
from modules.nf_orchestrator.services.job_service import JobServiceImpl
from modules.nf_orchestrator.services.project_service import ProjectServiceImpl
from modules.nf_orchestrator.services.query_service import QueryServiceImpl
from modules.nf_orchestrator.services.schema_service import SchemaServiceImpl
from modules.nf_orchestrator.services.tag_service import TagServiceImpl
from modules.nf_orchestrator.services.timeline_service import TimelineServiceImpl
from modules.nf_orchestrator.services.whitelist_service import WhitelistServiceImpl
from modules.nf_orchestrator.storage import db, docstore
from modules.nf_orchestrator.storage.repos import job_repo
from modules.nf_retrieval.vector import shard_store
from modules.nf_shared.config import load_config
from modules.nf_shared.errors import AppError, ErrorCode
from modules.nf_shared.protocol.dtos import (
    DocumentType,
    EntityKind,
    FactSource,
    FactStatus,
    JobEvent,
    JobType,
    SchemaLayer,
    SchemaType,
    SuggestMode,
    TagKind,
)
from modules.nf_shared.protocol.serialization import dump_json
from modules.nf_consistency.extractors import (
    ALLOWED_EXTRACTION_MODES,
    ALLOWED_SLOT_KEYS,
    compile_regex_flags,
    normalize_extraction_profile,
    validate_regex_pattern,
)


_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


def _resolve_resource(filename: str) -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller: Access via _MEIPASS or standard path based on add-data
        # We assume assets are added maintaining the structure
        base_dir = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
        # Map modules/nf_orchestrator structure
        return base_dir / "modules" / "nf_orchestrator" / filename
    return Path(__file__).with_name(filename)


_DEBUG_UI_PATH = _resolve_resource("debug_ui.html")
_USER_UI_PATH = _resolve_resource("user_ui.html")


def _build_openapi_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "nf-orchestrator", "version": "0.1.0"},
        "paths": {
            "/health": {"get": {"summary": "Health check"}},
            "/projects": {"get": {"summary": "List projects"}, "post": {"summary": "Create project"}},
            "/projects/{project_id}": {
                "get": {"summary": "Get project"},
                "patch": {"summary": "Update project"},
                "delete": {"summary": "Delete project"},
            },
            "/projects/{project_id}/documents": {
                "get": {"summary": "List documents"},
                "post": {"summary": "Create document"},
            },
            "/projects/{project_id}/documents/{doc_id}": {
                "get": {"summary": "Get document"},
                "patch": {"summary": "Update document"},
                "delete": {"summary": "Delete document"},
            },
            "/projects/{project_id}/entity-mentions": {"get": {"summary": "List entity mentions"}},
            "/projects/{project_id}/entity-mentions/{mention_id}": {"patch": {"summary": "Update mention status"}},
            "/projects/{project_id}/time-anchors": {"get": {"summary": "List time anchors"}},
            "/projects/{project_id}/time-anchors/{anchor_id}": {"patch": {"summary": "Update time anchor status"}},
            "/projects/{project_id}/timeline-events": {"get": {"summary": "List timeline events"}},
            "/projects/{project_id}/timeline-events/{event_id}": {"patch": {"summary": "Update timeline event status"}},
            "/projects/{project_id}/extraction/mappings": {
                "get": {"summary": "List extraction mappings"},
                "post": {"summary": "Create extraction mapping"},
            },
            "/projects/{project_id}/extraction/mappings/{mapping_id}": {
                "patch": {"summary": "Update extraction mapping"},
                "delete": {"summary": "Delete extraction mapping"},
            },
            "/projects/{project_id}/whitelist": {"post": {"summary": "Add whitelist item"}, "delete": {"summary": "Delete whitelist item"}},
            "/projects/{project_id}/ignore": {"post": {"summary": "Add ignore item"}, "delete": {"summary": "Delete ignore item"}},
            "/jobs": {"post": {"summary": "Submit job"}},
            "/jobs/{job_id}": {"get": {"summary": "Get job"}},
            "/jobs/{job_id}/cancel": {"post": {"summary": "Cancel job"}},
            "/jobs/{job_id}/events": {"get": {"summary": "Stream job events"}},
            "/query/retrieval": {"post": {"summary": "FTS-only retrieval"}},
            "/query/evidence/{eid}": {"get": {"summary": "Get evidence"}},
            "/query/verdicts": {"post": {"summary": "List verdicts"}},
            "/query/verdicts/{vid}": {"get": {"summary": "Get verdict detail"}},
        },
    }


class OrchestratorHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, *, token: str | None = None) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.project_service = ProjectServiceImpl()
        self.document_service = DocumentServiceImpl()
        self.episode_service = EpisodeServiceImpl()
        self.tag_service = TagServiceImpl()
        self.entity_service = EntityServiceImpl()
        self.schema_service = SchemaServiceImpl()
        self.extraction_service = ExtractionServiceImpl()
        self.timeline_service = TimelineServiceImpl()
        self.query_service = QueryServiceImpl()
        self.whitelist_service = WhitelistServiceImpl()
        self.ignore_service = IgnoreServiceImpl()
        self.job_service = JobServiceImpl()
        self.settings = load_config()
        self.token = token
        self.debug_state: dict[str, Any] = {
            "force_error_code": None,
            "force_latency_ms": 0,
            "disable_heavy_job_limit": False,
            "sse_drop_after": 0,
            "sse_fragment_ms": 0,
            "max_loaded_shards": self.settings.max_loaded_shards,
            "max_ram_mb": self.settings.max_ram_mb,
            "max_heavy_jobs": self.settings.max_heavy_jobs,
        }


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
        path = urlparse(self.path).path
        segments = [seg for seg in path.split("/") if seg]

        try:
            if segments[:1] == ["_debug"]:
                if not self._authorize_debug():
                    return
                self._handle_debug(segments[1:])
                return

            if not self._authorize():
                return
            if not self._apply_debug_injections(path):
                return

            # Serve User UI at root or /ui
            if path == "/" or path == "/ui":
                if self.command == "GET":
                    self._serve_user_ui()
                    return
                # Allow POST? No, usually UI is GET.
            
            if self.command == "GET" and path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if self.command == "GET" and path == "/openapi.json":
                self._send_json(HTTPStatus.OK, _build_openapi_spec())
                return

            if segments[:1] == ["projects"]:
                self._handle_projects(segments)
                return

            if segments[:1] == ["jobs"]:
                self._handle_jobs(segments)
                return

            if segments[:1] == ["query"]:
                self._handle_query(segments)
                return

            if segments[:1] == ["assets"]:
                self._handle_assets(segments[1:])
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

        if len(segments) >= 3:
            project_id = segments[1]
            project = self.server.project_service.get_project(project_id)
            if project is None:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "프로젝트를 찾을 수 없습니다")
                return
            resource = segments[2]
            tail = segments[3:]
            if resource == "documents":
                self._handle_documents(project_id, tail)
                return
            if resource == "episodes":
                self._handle_episodes(project_id, tail)
                return
            if resource == "tags":
                self._handle_tags(project_id, tail)
                return
            if resource == "entities":
                self._handle_entities(project_id, tail)
                return
            if resource == "entity-mentions":
                self._handle_entity_mentions(project_id, tail)
                return
            if resource == "time-anchors":
                self._handle_time_anchors(project_id, tail)
                return
            if resource == "timeline-events":
                self._handle_timeline_events(project_id, tail)
                return
            if resource == "extraction":
                self._handle_extraction(project_id, tail)
                return
            if resource == "whitelist":
                self._handle_whitelist(project_id)
                return
            if resource == "ignore":
                self._handle_ignore(project_id)
                return
            if resource == "schema":
                self._handle_schema(project_id, tail)
                return

        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_debug(self, tail: list[str]) -> None:
        if not tail:
            if self.command == "GET":
                self._serve_debug_ui()
                return
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return

        if tail[0] == "config":
            if self.command == "GET":
                self._send_json(HTTPStatus.OK, self._debug_config_payload())
                return
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return
        if tail[0] == "status":
            if self.command == "GET":
                self._send_json(HTTPStatus.OK, self._debug_status_payload())
                return
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return

        if tail[0] == "toggles":
            if self.command == "GET":
                self._send_json(HTTPStatus.OK, {"debug_state": self._debug_state_payload()})
                return
            if self.command == "PATCH":
                payload = self._read_json()
                updated = self._update_debug_toggles(payload)
                self._send_json(HTTPStatus.OK, {"debug_state": updated})
                return
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return

        if tail[0] == "fixtures":
            if self.command == "POST":
                payload = self._read_json()
                result = self._create_debug_fixtures(payload)
                self._send_json(HTTPStatus.CREATED, result)
                return
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return

        if tail[0] == "reset":
            if self.command == "POST":
                payload = self._read_json()
                confirm = payload.get("confirm")
                if confirm != "RESET":
                    raise AppError(ErrorCode.VALIDATION_ERROR, "confirm=RESET가 필요합니다")
                result = self._reset_debug_storage()
                self._send_json(HTTPStatus.OK, result)
                return
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return

        self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "찾을 수 없음")

    def _handle_documents(self, project_id: str, tail: list[str]) -> None:
        if not tail:
            if self.command == "GET":
                docs = self.server.document_service.list_documents(project_id)
                self._send_json(HTTPStatus.OK, {"documents": dump_json(docs)})
                return
            if self.command == "POST":
                payload = self._read_json()
                title = payload.get("title")
                doc_type_raw = payload.get("type")
                content = payload.get("content")
                metadata = payload.get("metadata")
                if not isinstance(title, str) or not title.strip():
                    raise AppError(ErrorCode.VALIDATION_ERROR, "title이 필요합니다")
                if not isinstance(doc_type_raw, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "type이 필요합니다")
                if not isinstance(content, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "content가 필요합니다")
                if metadata is not None and not isinstance(metadata, dict):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "metadata는 객체여야 합니다")
                try:
                    doc_type = DocumentType(doc_type_raw)
                except ValueError as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, f"지원하지 않는 문서 타입: {doc_type_raw}") from exc
                doc = self.server.document_service.create_document(
                    project_id, title.strip(), doc_type, content, metadata=metadata
                )
                self._send_json(HTTPStatus.CREATED, {"document": dump_json(doc)})
                return
        
        if tail[0] == "reorder" and self.command == "POST":
            # Batch reorder: { "updates": [ { "doc_id": "...", "order": 1, "group": "..." }, ... ] }
            payload = self._read_json()
            updates = payload.get("updates")
            if not isinstance(updates, list):
                raise AppError(ErrorCode.VALIDATION_ERROR, "updates는 리스트여야 합니다")
            
            # Simple loop for now. Transaction support would be better if Service allowed it.
            results = []
            for item in updates:
                did = item.get("doc_id")
                if not did: continue
                # We expect partial metadata update.
                # Since update_document replaces metadata, we fetch first? 
                # Or we assume frontend sends full metadata or we merge here.
                # Let's assume frontend sends strictly what needs to be Merged or Replaced?
                # Actually, our repo UPDATE replaces metadata_json. 
                # So to be safe, we should fetch existing, update fields, and save.
                # However, for reorder, usually we just touch 'order' and 'group'.
                existing = self.server.document_service.get_document(did)
                if not existing: continue
                
                new_meta = dict(existing.metadata or {})
                if "order" in item: new_meta["order"] = item["order"]
                if "group" in item: new_meta["group"] = item["group"]
                if "episode_no" in item: new_meta["episode_no"] = item["episode_no"]
                
                updated = self.server.document_service.update_document(did, metadata=new_meta)
                if updated: results.append(updated)
            
            self._send_json(HTTPStatus.OK, {"updated_count": len(results)})
            return

        if len(tail) == 1:
            doc_id = tail[0]
            if self.command == "GET":
                doc = self.server.document_service.get_document(doc_id)
                if doc is None:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "문서를 찾을 수 없습니다")
                    return
                
                # Hydrate content from file
                doc_dict = dump_json(doc)
                try:
                    content = docstore.read_text(doc.path)
                    doc_dict["content"] = content
                except Exception as e:
                    print(f"Failed to read content for {doc_id}: {e}")
                    doc_dict["content"] = ""
                
                self._send_json(HTTPStatus.OK, {"document": doc_dict})
                return
            if self.command == "PATCH":
                payload = self._read_json()
                title = payload.get("title")
                doc_type_raw = payload.get("type")
                content = payload.get("content")
                metadata = payload.get("metadata")
                if title is not None and not isinstance(title, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "title은 문자열이어야 합니다")
                doc_type = None
                if doc_type_raw is not None:
                    if not isinstance(doc_type_raw, str):
                        raise AppError(ErrorCode.VALIDATION_ERROR, "type은 문자열이어야 합니다")
                    try:
                        doc_type = DocumentType(doc_type_raw)
                    except ValueError as exc:
                        raise AppError(ErrorCode.VALIDATION_ERROR, f"지원하지 않는 문서 타입: {doc_type_raw}") from exc
                if content is not None and not isinstance(content, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "content는 문자열이어야 합니다")
                if metadata is not None and not isinstance(metadata, dict):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "metadata는 객체여야 합니다")
                
                # If metadata is provided, we probably want to merge it with existing unless it's a structural change
                # But here we pass it directly to service. Service/Repo currently REPLACES metadata_json.
                # We should merge here if the intention is a PATCH.
                target_meta = None
                if metadata is not None:
                    existing = self.server.document_service.get_document(doc_id)
                    if existing:
                        target_meta = dict(existing.metadata or {})
                        target_meta.update(metadata)
                    else:
                        target_meta = metadata

                doc = self.server.document_service.update_document(
                    doc_id,
                    title=title.strip() if isinstance(title, str) else None,
                    doc_type=doc_type,
                    content=content,
                    metadata=target_meta
                )
                if doc is None:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "문서를 찾을 수 없습니다")
                    return
                self._send_json(HTTPStatus.OK, {"document": dump_json(doc)})
                return
            if self.command == "DELETE":
                deleted = self.server.document_service.delete_document(doc_id)
                if not deleted:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "문서를 찾을 수 없습니다")
                    return
                self._send_json(HTTPStatus.OK, {"deleted": True})
                return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_episodes(self, project_id: str, tail: list[str]) -> None:
        if tail:
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return
        if self.command == "GET":
            episodes = self.server.episode_service.list_episodes(project_id)
            self._send_json(HTTPStatus.OK, {"episodes": dump_json(episodes)})
            return
        if self.command == "POST":
            payload = self._read_json()
            start_n = payload.get("start_n")
            end_m = payload.get("end_m")
            label = payload.get("label")
            if not isinstance(start_n, int) or not isinstance(end_m, int):
                raise AppError(ErrorCode.VALIDATION_ERROR, "start_n/end_m은 정수여야 합니다")
            if not isinstance(label, str) or not label.strip():
                raise AppError(ErrorCode.VALIDATION_ERROR, "label이 필요합니다")
            episode = self.server.episode_service.create_episode(project_id, start_n, end_m, label.strip())
            self._send_json(HTTPStatus.CREATED, {"episode": dump_json(episode)})
            return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_tags(self, project_id: str, tail: list[str]) -> None:
        if tail and tail[0] != "assignments":
            if len(tail) == 1 and self.command == "DELETE":
                tag_id = tail[0]
                deleted = self.server.tag_service.delete_tag_def(tag_id)
                if not deleted:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "tag를 찾을 수 없습니다")
                    return
                self._send_json(HTTPStatus.OK, {"deleted": True})
                return
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return
        if self.command == "GET":
            if tail and tail[0] == "assignments":
                params = parse_qs(urlparse(self.path).query)
                doc_id = params.get("doc_id", [None])[0]
                snapshot_id = params.get("snapshot_id", [None])[0]
                assignments = self.server.tag_service.list_tag_assignments(
                    project_id,
                    doc_id=doc_id,
                    snapshot_id=snapshot_id,
                )
                self._send_json(HTTPStatus.OK, {"assignments": dump_json(assignments)})
                return
            tags = self.server.tag_service.list_tag_defs(project_id)
            self._send_json(HTTPStatus.OK, {"tags": dump_json(tags)})
            return
        if self.command == "POST":
            if tail and tail[0] == "assignments":
                payload = self._read_json()
                doc_id = payload.get("doc_id")
                snapshot_id = payload.get("snapshot_id")
                span_start = payload.get("span_start")
                span_end = payload.get("span_end")
                tag_path = payload.get("tag_path")
                user_value = payload.get("user_value")
                created_by_raw = payload.get("created_by") or FactSource.USER.value
                if not isinstance(doc_id, str) or not isinstance(snapshot_id, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "doc_id/snapshot_id가 필요합니다")
                if not isinstance(span_start, int) or not isinstance(span_end, int):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "span_start/span_end는 정수여야 합니다")
                if not isinstance(tag_path, str) or not tag_path.strip():
                    raise AppError(ErrorCode.VALIDATION_ERROR, "tag_path가 필요합니다")
                try:
                    created_by = FactSource(created_by_raw)
                except ValueError as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "created_by가 유효하지 않습니다") from exc
                try:
                    assignment = self.server.tag_service.create_tag_assignment(
                        project_id,
                        doc_id,
                        snapshot_id,
                        span_start,
                        span_end,
                        tag_path.strip(),
                        user_value,
                        created_by,
                    )
                except ValueError as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
                self._send_json(HTTPStatus.CREATED, {"assignment": dump_json(assignment)})
                return
            payload = self._read_json()
            tag_path = payload.get("tag_path")
            kind_raw = payload.get("kind")
            schema_type_raw = payload.get("schema_type")
            constraints = payload.get("constraints") or {}
            if not isinstance(tag_path, str) or not tag_path.strip():
                raise AppError(ErrorCode.VALIDATION_ERROR, "tag_path가 필요합니다")
            if not isinstance(kind_raw, str) or not isinstance(schema_type_raw, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "kind/schema_type이 필요합니다")
            if not isinstance(constraints, dict):
                raise AppError(ErrorCode.VALIDATION_ERROR, "constraints는 객체여야 합니다")
            try:
                kind = TagKind(kind_raw)
                schema_type = SchemaType(schema_type_raw)
            except ValueError as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "유효하지 않은 kind/schema_type") from exc
            try:
                tag_def = self.server.tag_service.create_tag_def(
                    project_id,
                    tag_path.strip(),
                    kind,
                    schema_type,
                    constraints,
                )
            except ValueError as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
            self._send_json(HTTPStatus.CREATED, {"tag": dump_json(tag_def)})
            return
        if self.command == "DELETE" and tail and tail[0] == "assignments" and len(tail) == 2:
            assign_id = tail[1]
            deleted = self.server.tag_service.delete_tag_assignment(assign_id)
            if not deleted:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "assignment를 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"deleted": True})
            return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_entities(self, project_id: str, tail: list[str]) -> None:
        if not tail:
            if self.command == "GET":
                entities = self.server.entity_service.list_entities(project_id)
                self._send_json(HTTPStatus.OK, {"entities": dump_json(entities)})
                return
            if self.command == "POST":
                payload = self._read_json()
                kind_raw = payload.get("kind")
                canonical_name = payload.get("canonical_name")
                if not isinstance(kind_raw, str) or not isinstance(canonical_name, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "kind/canonical_name이 필요합니다")
                try:
                    kind = EntityKind(kind_raw)
                except ValueError as exc:
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR, f"지원하지 않는 엔티티 종류: {kind_raw}"
                    ) from exc
                entity = self.server.entity_service.create_entity(project_id, kind, canonical_name.strip())
                self._send_json(HTTPStatus.CREATED, {"entity": dump_json(entity)})
                return
        if len(tail) == 1 and self.command == "DELETE":
            entity_id = tail[0]
            deleted = self.server.entity_service.delete_entity(entity_id)
            if not deleted:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "entity를 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"deleted": True})
            return
        if len(tail) >= 2 and tail[1] == "aliases":
            entity_id = tail[0]
            if len(tail) == 2:
                if self.command == "GET":
                    aliases = self.server.entity_service.list_aliases(project_id, entity_id)
                    self._send_json(HTTPStatus.OK, {"aliases": dump_json(aliases)})
                    return
                if self.command == "POST":
                    payload = self._read_json()
                    alias_text = payload.get("alias_text")
                    created_by_raw = payload.get("created_by") or FactSource.USER.value
                    if not isinstance(alias_text, str) or not alias_text.strip():
                        raise AppError(ErrorCode.VALIDATION_ERROR, "alias_text가 필요합니다")
                    try:
                        created_by = FactSource(created_by_raw)
                    except ValueError as exc:
                        raise AppError(ErrorCode.VALIDATION_ERROR, "created_by가 유효하지 않습니다") from exc
                    alias = self.server.entity_service.create_alias(
                        project_id, entity_id, alias_text.strip(), created_by
                    )
                    self._send_json(HTTPStatus.CREATED, {"alias": dump_json(alias)})
                    return
                if self.command == "DELETE":
                    payload = self._read_json()
                    alias_id = payload.get("alias_id")
                    if not isinstance(alias_id, str):
                        raise AppError(ErrorCode.VALIDATION_ERROR, "alias_id가 필요합니다")
                    deleted = self.server.entity_service.delete_alias(alias_id)
                    if not deleted:
                        self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "alias를 찾을 수 없습니다")
                        return
                    self._send_json(HTTPStatus.OK, {"deleted": True})
                    return
            if len(tail) == 3 and self.command == "DELETE":
                alias_id = tail[2]
                deleted = self.server.entity_service.delete_alias(alias_id)
                if not deleted:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "alias를 찾을 수 없습니다")
                    return
                self._send_json(HTTPStatus.OK, {"deleted": True})
                return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_entity_mentions(self, project_id: str, tail: list[str]) -> None:
        if not tail and self.command == "GET":
            query = parse_qs(urlparse(self.path).query)
            doc_id = query.get("doc_id", [None])[0]
            entity_id = query.get("entity_id", [None])[0]
            status_raw = query.get("status", [None])[0]
            status = None
            if isinstance(status_raw, str):
                try:
                    status = FactStatus(status_raw)
                except ValueError as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "status가 유효하지 않습니다") from exc
            mentions = self.server.timeline_service.list_entity_mentions(
                project_id,
                doc_id=doc_id if isinstance(doc_id, str) else None,
                entity_id=entity_id if isinstance(entity_id, str) else None,
                status=status,
            )
            self._send_json(HTTPStatus.OK, {"mentions": dump_json(mentions)})
            return
        if len(tail) == 1 and self.command == "PATCH":
            mention_id = tail[0]
            payload = self._read_json()
            status_raw = payload.get("status")
            if not isinstance(status_raw, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "status가 필요합니다")
            try:
                status = FactStatus(status_raw)
            except ValueError as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "status가 유효하지 않습니다") from exc
            updated = self.server.timeline_service.set_entity_mention_status(mention_id, status)
            if updated is None:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "mention을 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"mention": dump_json(updated)})
            return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_time_anchors(self, project_id: str, tail: list[str]) -> None:
        if not tail and self.command == "GET":
            query = parse_qs(urlparse(self.path).query)
            doc_id = query.get("doc_id", [None])[0]
            time_key = query.get("time_key", [None])[0]
            timeline_idx_raw = query.get("timeline_idx", [None])[0]
            status_raw = query.get("status", [None])[0]
            timeline_idx = None
            if timeline_idx_raw is not None:
                try:
                    timeline_idx = int(timeline_idx_raw)
                except (TypeError, ValueError):
                    timeline_idx = None
            status = None
            if isinstance(status_raw, str):
                try:
                    status = FactStatus(status_raw)
                except ValueError as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "status가 유효하지 않습니다") from exc
            anchors = self.server.timeline_service.list_time_anchors(
                project_id,
                doc_id=doc_id if isinstance(doc_id, str) else None,
                time_key=time_key if isinstance(time_key, str) else None,
                timeline_idx=timeline_idx,
                status=status,
            )
            self._send_json(HTTPStatus.OK, {"anchors": dump_json(anchors)})
            return
        if len(tail) == 1 and self.command == "PATCH":
            anchor_id = tail[0]
            payload = self._read_json()
            status_raw = payload.get("status")
            if not isinstance(status_raw, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "status가 필요합니다")
            try:
                status = FactStatus(status_raw)
            except ValueError as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "status가 유효하지 않습니다") from exc
            updated = self.server.timeline_service.set_time_anchor_status(anchor_id, status)
            if updated is None:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "anchor를 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"anchor": dump_json(updated)})
            return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_timeline_events(self, project_id: str, tail: list[str]) -> None:
        if not tail and self.command == "GET":
            query = parse_qs(urlparse(self.path).query)
            source_doc_id = query.get("source_doc_id", [None])[0]
            status_raw = query.get("status", [None])[0]
            status = None
            if isinstance(status_raw, str):
                try:
                    status = FactStatus(status_raw)
                except ValueError as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "status가 유효하지 않습니다") from exc
            events = self.server.timeline_service.list_timeline_events(
                project_id,
                source_doc_id=source_doc_id if isinstance(source_doc_id, str) else None,
                status=status,
            )
            self._send_json(HTTPStatus.OK, {"events": dump_json(events)})
            return
        if len(tail) == 1 and self.command == "PATCH":
            event_id = tail[0]
            payload = self._read_json()
            status_raw = payload.get("status")
            if not isinstance(status_raw, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "status가 필요합니다")
            try:
                status = FactStatus(status_raw)
            except ValueError as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "status가 유효하지 않습니다") from exc
            updated = self.server.timeline_service.set_timeline_event_status(event_id, status)
            if updated is None:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "event를 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"event": dump_json(updated)})
            return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_extraction(self, project_id: str, tail: list[str]) -> None:
        if len(tail) == 1 and tail[0] == "mappings":
            if self.command == "GET":
                query = parse_qs(urlparse(self.path).query)
                enabled_only_raw = query.get("enabled_only", ["false"])[0]
                enabled_only = str(enabled_only_raw).lower() in {"1", "true", "yes", "on"}
                mappings = self.server.extraction_service.list_mappings(project_id, enabled_only=enabled_only)
                checksum = self.server.extraction_service.mapping_checksum(project_id)
                self._send_json(HTTPStatus.OK, {"mappings": dump_json(mappings), "mapping_checksum": checksum})
                return
            if self.command == "POST":
                payload = self._read_json()
                validated = self._validate_extraction_mapping_payload(payload, partial=False)
                mapping = self.server.extraction_service.create_mapping(
                    project_id,
                    slot_key=validated["slot_key"],
                    pattern=validated["pattern"],
                    flags=validated["flags"],
                    transform=validated["transform"],
                    priority=validated["priority"],
                    enabled=validated["enabled"],
                    created_by=validated["created_by"],
                )
                checksum = self.server.extraction_service.mapping_checksum(project_id)
                self._send_json(HTTPStatus.CREATED, {"mapping": dump_json(mapping), "mapping_checksum": checksum})
                return
        if len(tail) == 2 and tail[0] == "mappings":
            mapping_id = tail[1]
            if self.command == "PATCH":
                current = self.server.extraction_service.get_mapping(mapping_id)
                if current is None or current.project_id != project_id:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "mapping을 찾을 수 없습니다")
                    return
                payload = self._read_json()
                validated = self._validate_extraction_mapping_payload(payload, partial=True)
                merged_pattern = validated.get("pattern", current.pattern)
                merged_flags = validated.get("flags", current.flags)
                try:
                    re.compile(merged_pattern, compile_regex_flags(merged_flags))
                except re.error as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, f"regex compile failed: {exc}") from exc
                mapping = self.server.extraction_service.update_mapping(
                    mapping_id,
                    slot_key=validated.get("slot_key"),
                    pattern=validated.get("pattern"),
                    flags=validated.get("flags"),
                    transform=validated.get("transform"),
                    priority=validated.get("priority"),
                    enabled=validated.get("enabled"),
                )
                if mapping is None:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "mapping을 찾을 수 없습니다")
                    return
                checksum = self.server.extraction_service.mapping_checksum(project_id)
                self._send_json(HTTPStatus.OK, {"mapping": dump_json(mapping), "mapping_checksum": checksum})
                return
            if self.command == "DELETE":
                current = self.server.extraction_service.get_mapping(mapping_id)
                if current is None or current.project_id != project_id:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "mapping을 찾을 수 없습니다")
                    return
                deleted = self.server.extraction_service.delete_mapping(mapping_id)
                if not deleted:
                    self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "mapping을 찾을 수 없습니다")
                    return
                checksum = self.server.extraction_service.mapping_checksum(project_id)
                self._send_json(HTTPStatus.OK, {"deleted": True, "mapping_checksum": checksum})
                return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _validate_extraction_mapping_payload(self, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        validated: dict[str, Any] = {}
        slot_key = payload.get("slot_key")
        if slot_key is not None:
            if not isinstance(slot_key, str) or slot_key not in ALLOWED_SLOT_KEYS:
                raise AppError(ErrorCode.VALIDATION_ERROR, "slot_key is invalid")
            validated["slot_key"] = slot_key
        elif not partial:
            raise AppError(ErrorCode.VALIDATION_ERROR, "slot_key가 필요합니다")

        pattern = payload.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "pattern must be a string")
            try:
                validate_regex_pattern(pattern)
            except ValueError as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
            validated["pattern"] = pattern
        elif not partial:
            raise AppError(ErrorCode.VALIDATION_ERROR, "pattern이 필요합니다")

        flags = payload.get("flags")
        if flags is not None:
            if not isinstance(flags, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "flags must be a string")
            unknown = [ch for ch in flags if ch.upper() not in {"I", "M", "S", "U", "A"}]
            if unknown:
                raise AppError(ErrorCode.VALIDATION_ERROR, "flags contains unsupported values")
            try:
                if "pattern" in validated:
                    re.compile(validated["pattern"], compile_regex_flags(flags))
            except re.error as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"regex compile failed: {exc}") from exc
            validated["flags"] = flags
        elif not partial:
            validated["flags"] = ""

        transform = payload.get("transform")
        if transform is not None:
            if not isinstance(transform, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "transform must be a string")
            allowed = {"identity", "strip", "lower", "int", "bool", "death_flag"}
            if transform not in allowed:
                raise AppError(ErrorCode.VALIDATION_ERROR, "transform is invalid")
            validated["transform"] = transform
        elif not partial:
            validated["transform"] = "identity"

        priority = payload.get("priority")
        if priority is not None:
            if not isinstance(priority, int):
                raise AppError(ErrorCode.VALIDATION_ERROR, "priority must be an integer")
            if priority < 0 or priority > 1000:
                raise AppError(ErrorCode.VALIDATION_ERROR, "priority must be between 0 and 1000")
            validated["priority"] = priority
        elif not partial:
            validated["priority"] = 100

        enabled = payload.get("enabled")
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise AppError(ErrorCode.VALIDATION_ERROR, "enabled must be boolean")
            validated["enabled"] = enabled
        elif not partial:
            validated["enabled"] = True

        created_by = payload.get("created_by")
        if created_by is not None:
            if not isinstance(created_by, str) or not created_by.strip():
                raise AppError(ErrorCode.VALIDATION_ERROR, "created_by must be a non-empty string")
            validated["created_by"] = created_by.strip()
        elif not partial:
            validated["created_by"] = "USER"

        return validated

    def _handle_whitelist(self, project_id: str) -> None:
        if self.command == "POST":
            payload = self._read_json()
            claim_text = payload.get("claim_text")
            scope = payload.get("scope")
            note = payload.get("note")
            if not isinstance(claim_text, str) or not claim_text.strip():
                raise AppError(ErrorCode.VALIDATION_ERROR, "claim_text가 필요합니다")
            if not isinstance(scope, str) or not scope.strip():
                raise AppError(ErrorCode.VALIDATION_ERROR, "scope가 필요합니다")
            item = self.server.whitelist_service.add_item(project_id, claim_text, scope.strip(), note)
            self._send_json(HTTPStatus.CREATED, {"whitelist": item})
            return
        if self.command == "DELETE":
            payload = self._read_json()
            claim_text = payload.get("claim_text")
            if not isinstance(claim_text, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "claim_text가 필요합니다")
            deleted = self.server.whitelist_service.delete_item(project_id, claim_text)
            if not deleted:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "whitelist를 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"deleted": True})
            return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_ignore(self, project_id: str) -> None:
        if self.command == "POST":
            payload = self._read_json()
            claim_text = payload.get("claim_text")
            scope = payload.get("scope")
            kind = payload.get("kind")
            note = payload.get("note")
            if not isinstance(claim_text, str) or not claim_text.strip():
                raise AppError(ErrorCode.VALIDATION_ERROR, "claim_text가 필요합니다")
            if not isinstance(scope, str) or not scope.strip():
                raise AppError(ErrorCode.VALIDATION_ERROR, "scope가 필요합니다")
            if not isinstance(kind, str) or not kind.strip():
                raise AppError(ErrorCode.VALIDATION_ERROR, "kind가 필요합니다")
            item = self.server.ignore_service.add_item(
                project_id,
                claim_text,
                scope.strip(),
                kind.strip(),
                note,
            )
            self._send_json(HTTPStatus.CREATED, {"ignore": item})
            return
        if self.command == "DELETE":
            payload = self._read_json()
            claim_text = payload.get("claim_text")
            scope = payload.get("scope")
            kind = payload.get("kind")
            if not isinstance(claim_text, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "claim_text가 필요합니다")
            if scope is not None and not isinstance(scope, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "scope는 문자열이어야 합니다")
            if kind is not None and not isinstance(kind, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "kind는 문자열이어야 합니다")
            deleted = self.server.ignore_service.delete_item(
                project_id,
                claim_text,
                scope=scope.strip() if isinstance(scope, str) else None,
                kind=kind.strip() if isinstance(kind, str) else None,
            )
            if not deleted:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "ignore를 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"deleted": True})
            return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_schema(self, project_id: str, tail: list[str]) -> None:
        if not tail:
            if self.command == "GET":
                view = self.server.schema_service.get_schema_view(project_id)
                self._send_json(HTTPStatus.OK, {"schema": dump_json(view)})
                return
        if tail[:1] == ["facts"]:
            if len(tail) == 1:
                if self.command != "GET":
                    self._send_app_error(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        ErrorCode.VALIDATION_ERROR,
                        "허용되지 않는 메서드",
                    )
                    return
                params = parse_qs(urlparse(self.path).query)
                status_raw = params.get("status", [None])[0]
                layer_raw = params.get("layer", [None])[0]


                source_raw = params.get("source", [None])[0]
                try:
                    status = FactStatus(status_raw) if status_raw else None
                except ValueError as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "유효하지 않은 status") from exc
                if layer_raw:
                    try:
                        SchemaLayer(layer_raw)
                    except ValueError as exc:
                        raise AppError(ErrorCode.VALIDATION_ERROR, "유효하지 않은 layer") from exc
                if source_raw:
                    try:
                        FactSource(source_raw)
                    except ValueError as exc:
                        raise AppError(ErrorCode.VALIDATION_ERROR, "유효하지 않은 source") from exc
                facts = self.server.schema_service.list_facts(
                    project_id,
                    status=status,
                    layer=layer_raw,
                    source=source_raw,
                )
                self._send_json(HTTPStatus.OK, {"facts": dump_json(facts)})
                return
            if len(tail) == 2:
                fact_id = tail[1]
                if self.command == "GET":
                    fact = self.server.schema_service.get_fact(fact_id)
                    if fact is None or fact.project_id != project_id:
                        self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "fact를 찾을 수 없습니다")
                        return
                    self._send_json(HTTPStatus.OK, {"fact": dump_json(fact)})
                    return
                if self.command == "PATCH":
                    payload = self._read_json()
                    status_raw = payload.get("status")
                    if not isinstance(status_raw, str):
                        raise AppError(ErrorCode.VALIDATION_ERROR, "status가 필요합니다")
                    try:
                        status = FactStatus(status_raw)
                    except ValueError as exc:
                        raise AppError(ErrorCode.VALIDATION_ERROR, "유효하지 않은 status") from exc
                    try:
                        fact = self.server.schema_service.set_fact_status(project_id, fact_id, status)
                    except ValueError:
                        self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "fact를 찾을 수 없습니다")
                        return
                    self._send_json(HTTPStatus.OK, {"fact": dump_json(fact)})
                    return
        self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")

    def _handle_assets(self, tail: list[str]) -> None:
        if self.command != "GET":
            self._send_app_error(HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드")
            return
        
        if not tail:
             self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "파일을 찾을 수 없음")
             return

        filename = tail[0]
        # Security check
        if ".." in filename or "/" in filename or "\\" in filename:
             self._send_app_error(HTTPStatus.FORBIDDEN, ErrorCode.VALIDATION_ERROR, "잘못된 파일명")
             return
             
        # assets_dir adjustment
        if getattr(sys, "frozen", False):
             base_dir = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
             assets_dir = base_dir / "modules" / "nf_orchestrator" / "assets"
        else:
             assets_dir = Path(__file__).resolve().parent / "assets"

        file_path = assets_dir / filename
        
        if not file_path.exists() or not file_path.is_file():
             self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "파일을 찾을 수 없음")
             return
             
        ctype = "application/octet-stream"
        if filename.lower().endswith(".gif"):
            ctype = "image/gif"
        elif filename.lower().endswith(".png"):
            ctype = "image/png"
        elif filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
            ctype = "image/jpeg"
        elif filename.lower().endswith(".svg"):
            ctype = "image/svg+xml"
            
        try:
            content = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception:
             self._send_app_error(HTTPStatus.INTERNAL_SERVER_ERROR, ErrorCode.INTERNAL_ERROR, "파일 읽기 실패")

    def _handle_query(self, segments: list[str]) -> None:
        if len(segments) == 2 and segments[1] == "retrieval":
            if self.command != "POST":
                self._send_app_error(
                    HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드"
                )
                return
            payload = self._read_json()
            project_id = payload.get("project_id")
            query_text = payload.get("query")
            filters = payload.get("filters") or {}
            k = payload.get("k") or 10
            if not isinstance(project_id, str) or not isinstance(query_text, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "project_id/query가 필요합니다")
            if not isinstance(filters, dict):
                raise AppError(ErrorCode.VALIDATION_ERROR, "filters는 객체여야 합니다")
            try:
                k = int(k)
            except (TypeError, ValueError) as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "k는 정수여야 합니다") from exc
            if self.server.settings.sync_retrieval_mode != "FTS_ONLY":
                raise AppError(ErrorCode.POLICY_VIOLATION, "sync retrieval은 FTS_ONLY만 허용됩니다")
            req = {
                "project_id": project_id,
                "query": query_text,
                "filters": filters,
                "k": k,
            }
            results = self.server.query_service.retrieval_fts(req)
            stored = self.server.query_service.store_evidence_from_results(project_id, results)
            for result, evidence in zip(results, stored):
                evidence_raw = result.get("evidence") or {}
                evidence_raw["eid"] = evidence.eid
                result["evidence"] = evidence_raw
            self._send_json(HTTPStatus.OK, {"results": results})
            return
        if len(segments) == 3 and segments[1] == "evidence":
            if self.command != "GET":
                self._send_app_error(
                    HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드"
                )
                return
            evidence = self.server.query_service.get_evidence(segments[2])
            if evidence is None:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "evidence를 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, {"evidence": dump_json(evidence)})
            return
        if len(segments) == 3 and segments[1] == "verdicts":
            if self.command != "GET":
                self._send_app_error(
                    HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드"
                )
                return
            params = parse_qs(urlparse(self.path).query)
            project_id = params.get("project_id", [None])[0]
            if not isinstance(project_id, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "project_id가 필요합니다")
            detail = self.server.query_service.get_verdict_detail(project_id, segments[2])
            if detail is None:
                self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "verdict를 찾을 수 없습니다")
                return
            self._send_json(HTTPStatus.OK, dump_json(detail))
            return
        if len(segments) == 2 and segments[1] == "verdicts":
            if self.command != "POST":
                self._send_app_error(
                    HTTPStatus.METHOD_NOT_ALLOWED, ErrorCode.VALIDATION_ERROR, "허용되지 않는 메서드"
                )
                return
            payload = self._read_json()
            project_id = payload.get("project_id")
            input_doc_id = payload.get("input_doc_id")
            if not isinstance(project_id, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "project_id가 필요합니다")
            verdicts = self.server.query_service.list_verdicts(project_id, input_doc_id=input_doc_id)
            self._send_json(HTTPStatus.OK, {"verdicts": dump_json(verdicts)})
            return
        self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "찾을 수 없음")

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
            priority = payload.get("priority", 100)
            if not isinstance(inputs, dict) or not isinstance(params, dict):
                raise AppError(ErrorCode.VALIDATION_ERROR, "inputs와 params는 객체여야 합니다")
            if not isinstance(priority, int):
                raise AppError(ErrorCode.VALIDATION_ERROR, "priority는 정수여야 합니다")
            self._validate_job_payload(job_type, inputs)
            self._validate_job_params(job_type, params)
            self._enforce_job_policy(job_type, inputs, params, project.settings)
            job = self.server.job_service.submit(project_id, job_type, inputs, params, priority=priority)
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

    def _validate_job_payload(self, job_type: JobType, inputs: dict[str, Any]) -> None:
        def require_str(key: str) -> None:
            if not isinstance(inputs.get(key), str):
                raise AppError(ErrorCode.VALIDATION_ERROR, f"{key}가 필요합니다")

        def require_dict(key: str) -> None:
            if not isinstance(inputs.get(key), dict):
                raise AppError(ErrorCode.VALIDATION_ERROR, f"{key}가 필요합니다")

        if job_type == JobType.INGEST:
            require_str("doc_id")
        elif job_type == JobType.INDEX_FTS:
            require_str("scope")
            snapshot_id = inputs.get("snapshot_id")
            scope = inputs.get("scope")
            if snapshot_id is not None and not isinstance(snapshot_id, str):
                raise AppError(ErrorCode.VALIDATION_ERROR, "snapshot_id는 문자열이어야 합니다")
            if isinstance(snapshot_id, str) and snapshot_id.strip() and scope == "global":
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "snapshot_id는 scope=global과 함께 사용할 수 없습니다",
                )
        elif job_type == JobType.INDEX_VEC:
            require_str("scope")
            require_dict("shard_policy")
        elif job_type == JobType.CONSISTENCY:
            require_str("input_doc_id")
            require_str("input_snapshot_id")
            require_dict("range")
            filters = inputs.get("filters")
            if filters is not None:
                if not isinstance(filters, dict):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "filters는 객체여야 합니다")
                entity_id = filters.get("entity_id")
                time_key = filters.get("time_key")
                timeline_idx = filters.get("timeline_idx")
                if entity_id is not None and not isinstance(entity_id, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "filters.entity_id는 문자열이어야 합니다")
                if time_key is not None and not isinstance(time_key, str):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "filters.time_key는 문자열이어야 합니다")
                if timeline_idx is not None:
                    try:
                        int(timeline_idx)
                    except (TypeError, ValueError) as exc:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR, "filters.timeline_idx는 정수여야 합니다"
                        ) from exc
            preflight = inputs.get("preflight")
            if preflight is not None:
                if not isinstance(preflight, dict):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "preflight must be an object")
                ensure_ingest = preflight.get("ensure_ingest")
                ensure_index_fts = preflight.get("ensure_index_fts")
                schema_scope = preflight.get("schema_scope")
                if ensure_ingest is not None and not isinstance(ensure_ingest, bool):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "preflight.ensure_ingest must be boolean")
                if ensure_index_fts is not None and not isinstance(ensure_index_fts, bool):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "preflight.ensure_index_fts must be boolean")
                if schema_scope is not None and schema_scope not in {"latest_approved", "explicit_only"}:
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR,
                        "preflight.schema_scope must be latest_approved or explicit_only",
                    )
            schema_scope = inputs.get("schema_scope")
            if schema_scope is not None and schema_scope not in {"latest_approved", "explicit_only"}:
                raise AppError(ErrorCode.VALIDATION_ERROR, "schema_scope must be latest_approved or explicit_only")
        elif job_type == JobType.RETRIEVE_VEC:
            require_str("query")
            if "filters" in inputs and not isinstance(inputs.get("filters"), dict):
                raise AppError(ErrorCode.VALIDATION_ERROR, "filters는 객체여야 합니다")
        elif job_type == JobType.SUGGEST:
            require_dict("range")
            require_str("mode")
        elif job_type == JobType.PROOFREAD:
            require_str("doc_id")
            require_str("snapshot_id")
        elif job_type == JobType.EXPORT:
            require_dict("range")
            require_str("format")

    def _validate_job_params(self, job_type: JobType, params: dict[str, Any]) -> None:
        if job_type not in {JobType.INGEST, JobType.CONSISTENCY}:
            return
        if job_type == JobType.CONSISTENCY:
            consistency_raw = params.get("consistency")
            if consistency_raw is not None:
                if not isinstance(consistency_raw, dict):
                    raise AppError(ErrorCode.VALIDATION_ERROR, "params.consistency must be an object")
                policy_raw = consistency_raw.get("evidence_link_policy")
                if policy_raw is not None:
                    if not isinstance(policy_raw, str) or policy_raw not in {"full", "cap", "contradict_only"}:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.evidence_link_policy is invalid",
                        )
                cap_raw = consistency_raw.get("evidence_link_cap")
                if cap_raw is not None:
                    if not isinstance(cap_raw, int):
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.evidence_link_cap must be integer",
                        )
                    if cap_raw < 1:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.evidence_link_cap must be >= 1",
                        )
                exclude_self_raw = consistency_raw.get("exclude_self_evidence")
                if exclude_self_raw is not None and not isinstance(exclude_self_raw, bool):
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR,
                        "params.consistency.exclude_self_evidence must be boolean",
                    )
                self_scope_raw = consistency_raw.get("self_evidence_scope")
                if self_scope_raw is not None:
                    if not isinstance(self_scope_raw, str) or self_scope_raw not in {"range", "doc"}:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.self_evidence_scope is invalid",
                        )
                graph_expand_raw = consistency_raw.get("graph_expand_enabled")
                if graph_expand_raw is not None and not isinstance(graph_expand_raw, bool):
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR,
                        "params.consistency.graph_expand_enabled must be boolean",
                    )
                graph_hops_raw = consistency_raw.get("graph_max_hops")
                if graph_hops_raw is not None:
                    if not isinstance(graph_hops_raw, int) or graph_hops_raw not in {1, 2}:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.graph_max_hops must be 1 or 2",
                        )
                graph_cap_raw = consistency_raw.get("graph_doc_cap")
                if graph_cap_raw is not None:
                    if not isinstance(graph_cap_raw, int):
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.graph_doc_cap must be integer",
                        )
                    if graph_cap_raw < 1:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.graph_doc_cap must be >= 1",
                        )
                layer3_promotion_raw = consistency_raw.get("layer3_verdict_promotion")
                if layer3_promotion_raw is not None and not isinstance(layer3_promotion_raw, bool):
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR,
                        "params.consistency.layer3_verdict_promotion must be boolean",
                    )
                layer3_min_fts_raw = consistency_raw.get("layer3_min_fts_for_promotion")
                if layer3_min_fts_raw is not None:
                    if not isinstance(layer3_min_fts_raw, (int, float)):
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.layer3_min_fts_for_promotion must be number",
                        )
                    if not 0.0 <= float(layer3_min_fts_raw) <= 1.0:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.layer3_min_fts_for_promotion must be between 0 and 1",
                        )
                layer3_max_claim_chars_raw = consistency_raw.get("layer3_max_claim_chars")
                if layer3_max_claim_chars_raw is not None:
                    if not isinstance(layer3_max_claim_chars_raw, int):
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.layer3_max_claim_chars must be integer",
                        )
                    if layer3_max_claim_chars_raw < 1:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.layer3_max_claim_chars must be >= 1",
                        )
                layer3_ok_threshold_raw = consistency_raw.get("layer3_ok_threshold")
                if layer3_ok_threshold_raw is not None:
                    if not isinstance(layer3_ok_threshold_raw, (int, float)):
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.layer3_ok_threshold must be number",
                        )
                    if not 0.0 <= float(layer3_ok_threshold_raw) <= 1.0:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "params.consistency.layer3_ok_threshold must be between 0 and 1",
                        )
        extraction_raw = params.get("extraction")
        if extraction_raw is None:
            return
        if not isinstance(extraction_raw, dict):
            raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction must be an object")
        mode_raw = extraction_raw.get("mode")
        if mode_raw is not None:
            if not isinstance(mode_raw, str) or mode_raw not in ALLOWED_EXTRACTION_MODES:
                raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction.mode is invalid")
        use_user_raw = extraction_raw.get("use_user_mappings")
        if use_user_raw is not None and not isinstance(use_user_raw, bool):
            raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction.use_user_mappings must be boolean")
        model_slots_raw = extraction_raw.get("model_slots")
        if model_slots_raw is not None:
            if not isinstance(model_slots_raw, list):
                raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction.model_slots must be an array")
            for slot_raw in model_slots_raw:
                if not isinstance(slot_raw, str) or slot_raw not in ALLOWED_SLOT_KEYS:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction.model_slots contains invalid slot")
        timeout_raw = extraction_raw.get("model_timeout_ms")
        if timeout_raw is not None and not isinstance(timeout_raw, int):
            raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction.model_timeout_ms must be integer")
        normalized = normalize_extraction_profile(extraction_raw)
        mode = normalized["mode"]
        if mode not in ALLOWED_EXTRACTION_MODES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction.mode is invalid")
        for slot in normalized["model_slots"]:
            if slot not in ALLOWED_SLOT_KEYS:
                raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction.model_slots contains invalid slot")
        timeout_ms = normalized["model_timeout_ms"]
        if not isinstance(timeout_ms, int) or timeout_ms < 100:
            raise AppError(ErrorCode.VALIDATION_ERROR, "params.extraction.model_timeout_ms must be >= 100")

    def _enforce_job_policy(
        self,
        job_type: JobType,
        inputs: dict[str, Any],
        params: dict[str, Any],
        project_settings: dict[str, Any] | None = None,
    ) -> None:
        project_settings = project_settings or {}
        if job_type == JobType.SUGGEST:
            mode_raw = inputs.get("mode")
            if isinstance(mode_raw, str):
                try:
                    mode = SuggestMode(mode_raw)
                except ValueError as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "유효하지 않은 mode") from exc
                if mode is SuggestMode.API:
                    if not self.server.settings.enable_remote_api:
                        raise AppError(ErrorCode.POLICY_VIOLATION, "remote API가 비활성화되었습니다")
                    if not project_settings.get("enable_remote_api", False):
                        raise AppError(ErrorCode.POLICY_VIOLATION, "프로젝트 remote API가 비활성화되었습니다")
                if mode is SuggestMode.LOCAL_GEN:
                    if not self.server.settings.enable_local_generator:
                        raise AppError(ErrorCode.POLICY_VIOLATION, "local generator가 비활성화되었습니다")
                    if not project_settings.get("enable_local_generator", False):
                        raise AppError(ErrorCode.POLICY_VIOLATION, "프로젝트 local generator가 비활성화되었습니다")
        if job_type in {JobType.INGEST, JobType.CONSISTENCY}:
            extraction_raw = params.get("extraction")
            if isinstance(extraction_raw, dict):
                mode = normalize_extraction_profile(extraction_raw)["mode"]
                if mode in {"hybrid_remote", "hybrid_dual"}:
                    if not self.server.settings.enable_remote_api:
                        raise AppError(ErrorCode.POLICY_VIOLATION, "remote extraction API가 비활성화되었습니다")
                    if not project_settings.get("enable_remote_api", False):
                        raise AppError(ErrorCode.POLICY_VIOLATION, "프로젝트 remote API가 비활성화되었습니다")

    def _enforce_heavy_job_semaphore(self, job_type: JobType) -> None:
        if self.server.debug_state.get("disable_heavy_job_limit"):
            return
        heavy_types = [JobType.INDEX_VEC, JobType.CONSISTENCY, JobType.RETRIEVE_VEC]
        if job_type not in heavy_types:
            return
        with db.connect() as conn:
            running = job_repo.count_running_jobs(conn, heavy_types)
        max_heavy_jobs = max(1, int(self.server.settings.max_heavy_jobs))
        if running >= max_heavy_jobs:
            raise AppError(ErrorCode.POLICY_VIOLATION, "heavy job 동시 실행이 제한됩니다")

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

        drop_after = int(self.server.debug_state.get("sse_drop_after") or 0)
        fragment_ms = int(self.server.debug_state.get("sse_fragment_ms") or 0)

        events = self.server.job_service.list_events(job_id, after_seq=after_seq)
        sent = 0
        for seq, event in events:
            self._write_sse_event(seq, event, fragment_ms=fragment_ms)
            sent += 1
            if drop_after and sent >= drop_after:
                return
        self.wfile.write(b": keep-alive\n\n")

    def _write_sse_event(self, seq: int, event: JobEvent, *, fragment_ms: int = 0) -> None:
        payload = json.dumps(dump_json(event), ensure_ascii=False)
        if fragment_ms > 0:
            self.wfile.write(f"id: {seq}\n".encode("utf-8"))
            self.wfile.write(b"event: message\n")
            self.wfile.flush()
            time.sleep(fragment_ms / 1000)
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()
            return
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

    def _send_html(self, html_content: str) -> None:
        body = html_content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_debug_ui(self) -> None:
        if not _DEBUG_UI_PATH.exists():
            self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "Debug UI file missing")
            return
        html = _DEBUG_UI_PATH.read_text(encoding="utf-8")
        self._send_html(html)

    def _serve_user_ui(self) -> None:
        if not _USER_UI_PATH.exists():
            self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "User UI file missing")
            return
        html = _USER_UI_PATH.read_text(encoding="utf-8")
        self._send_html(html)

    def _debug_state_payload(self) -> dict[str, Any]:
        return dict(self.server.debug_state)

    def _debug_config_payload(self) -> dict[str, Any]:
        settings = self.server.settings
        return {
            "debug_ui_enabled": settings.enable_debug_web_ui,
            "require_api_token": bool(self.server.token),
            "settings": {
                "enable_remote_api": settings.enable_remote_api,
                "enable_layer3_model": settings.enable_layer3_model,
                "enable_local_generator": settings.enable_local_generator,
                "sync_retrieval_mode": settings.sync_retrieval_mode,
                "vector_index_mode": settings.vector_index_mode,
                "max_loaded_shards": settings.max_loaded_shards,
                "max_ram_mb": settings.max_ram_mb,
                "max_heavy_jobs": settings.max_heavy_jobs,
                "evidence_required_for_model_output": settings.evidence_required_for_model_output,
                "implicit_fact_auto_approve": settings.implicit_fact_auto_approve,
                "explicit_fact_auto_approve": settings.explicit_fact_auto_approve,
            },
            "debug_state": self._debug_state_payload(),
        }

    def _debug_status_payload(self) -> dict[str, Any]:
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        last_event = None
        status_counts: dict[str, int] = {}
        with db.connect() as conn:
            row = conn.execute(
                "SELECT seq, job_id, ts, level, message FROM job_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                last_event = {
                    "seq": row["seq"],
                    "job_id": row["job_id"],
                    "ts": row["ts"],
                    "level": row["level"],
                    "message": row["message"],
                }
            counts = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status"
            ).fetchall()
        for row in counts:
            status_counts[row["status"]] = int(row["cnt"])
        return {
            "now": now_ts,
            "orchestrator": {"ok": True},
            "worker_last_event": last_event,
            "job_status_counts": status_counts,
        }

    def _update_debug_toggles(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.server.debug_state
        if "force_error_code" in payload:
            raw = payload.get("force_error_code")
            if raw in (None, "", 0):
                state["force_error_code"] = None
            else:
                try:
                    state["force_error_code"] = int(raw)
                except (TypeError, ValueError) as exc:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "force_error_code는 정수여야 합니다") from exc
        if "force_latency_ms" in payload:
            raw = payload.get("force_latency_ms")
            try:
                latency_ms = int(raw)
            except (TypeError, ValueError) as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "force_latency_ms는 정수여야 합니다") from exc
            if latency_ms < 0:
                raise AppError(ErrorCode.VALIDATION_ERROR, "force_latency_ms는 0 이상이어야 합니다")
            state["force_latency_ms"] = latency_ms
        if "disable_heavy_job_limit" in payload:
            state["disable_heavy_job_limit"] = bool(payload.get("disable_heavy_job_limit"))
        if "sse_drop_after" in payload:
            raw = payload.get("sse_drop_after")
            try:
                drop_after = int(raw)
            except (TypeError, ValueError) as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "sse_drop_after는 정수여야 합니다") from exc
            if drop_after < 0:
                raise AppError(ErrorCode.VALIDATION_ERROR, "sse_drop_after는 0 이상이어야 합니다")
            state["sse_drop_after"] = drop_after
        if "sse_fragment_ms" in payload:
            raw = payload.get("sse_fragment_ms")
            try:
                fragment_ms = int(raw)
            except (TypeError, ValueError) as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "sse_fragment_ms는 정수여야 합니다") from exc
            if fragment_ms < 0:
                raise AppError(ErrorCode.VALIDATION_ERROR, "sse_fragment_ms는 0 이상이어야 합니다")
            state["sse_fragment_ms"] = fragment_ms
        reload_config = False
        if "max_loaded_shards" in payload:
            raw = payload.get("max_loaded_shards")
            try:
                max_loaded = int(raw)
            except (TypeError, ValueError) as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "max_loaded_shards는 정수여야 합니다") from exc
            if max_loaded <= 0:
                raise AppError(ErrorCode.VALIDATION_ERROR, "max_loaded_shards는 1 이상이어야 합니다")
            os.environ["NF_MAX_LOADED_SHARDS"] = str(max_loaded)
            state["max_loaded_shards"] = max_loaded
            reload_config = True
        if "max_ram_mb" in payload:
            raw = payload.get("max_ram_mb")
            try:
                max_ram = int(raw)
            except (TypeError, ValueError) as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "max_ram_mb는 정수여야 합니다") from exc
            if max_ram <= 0:
                raise AppError(ErrorCode.VALIDATION_ERROR, "max_ram_mb는 1 이상이어야 합니다")
            os.environ["NF_MAX_RAM_MB"] = str(max_ram)
            state["max_ram_mb"] = max_ram
            reload_config = True
        if "max_heavy_jobs" in payload:
            raw = payload.get("max_heavy_jobs")
            try:
                max_heavy_jobs = int(raw)
            except (TypeError, ValueError) as exc:
                raise AppError(ErrorCode.VALIDATION_ERROR, "max_heavy_jobs must be an integer") from exc
            if max_heavy_jobs <= 0:
                raise AppError(ErrorCode.VALIDATION_ERROR, "max_heavy_jobs must be >= 1")
            os.environ["NF_MAX_HEAVY_JOBS"] = str(max_heavy_jobs)
            state["max_heavy_jobs"] = max_heavy_jobs
            reload_config = True
        if reload_config:
            self.server.settings = load_config()
        return self._debug_state_payload()

    def _create_debug_fixtures(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_name = payload.get("project_name") or "Sample Project"
        if not isinstance(project_name, str) or not project_name.strip():
            raise AppError(ErrorCode.VALIDATION_ERROR, "project_name은 문자열이어야 합니다")
        project = self.server.project_service.create_project(project_name.strip(), settings={})
        text = (
            "Episode 1\n"
            "The night market wakes up, and a courier slips through the crowd.\n"
            "A quiet exchange happens under a broken sign.\n"
        )
        doc = self.server.document_service.create_document(
            project.project_id,
            "Sample Episode",
            DocumentType.EPISODE,
            text,
        )
        tags = self.server.tag_service.list_tag_defs(project.project_id)
        return {
            "project": dump_json(project),
            "document": dump_json(doc),
            "tags_seeded": len(tags),
        }

    def _reset_debug_storage(self) -> dict[str, Any]:
        db_path = db.get_db_path()
        if db_path.exists():
            db_path.unlink()
        shutil.rmtree(docstore.DEFAULT_DOCSTORE_PATH, ignore_errors=True)
        shutil.rmtree(docstore.DEFAULT_EXPORT_PATH, ignore_errors=True)
        shutil.rmtree(shard_store.DEFAULT_VECTOR_PATH, ignore_errors=True)
        return {"reset": True}

    def _apply_debug_injections(self, path: str) -> bool:
        state = self.server.debug_state
        latency_ms = state.get("force_latency_ms") or 0
        if isinstance(latency_ms, int) and latency_ms > 0:
            time.sleep(latency_ms / 1000)
        error_code = state.get("force_error_code")
        if error_code:
            state["force_error_code"] = None
            try:
                status = HTTPStatus(int(error_code))
            except (TypeError, ValueError):
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_app_error(status, ErrorCode.POLICY_VIOLATION, "debug forced error")
            return False
        return True

    def _authorize_debug(self) -> bool:
        settings = self.server.settings
        token = settings.debug_web_ui_token
        if not settings.enable_debug_web_ui or not token:
            self._send_app_error(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, "찾을 수 없음")
            return False
        provided = self.headers.get("X-NF-Debug-Token")
        if not provided:
            params = parse_qs(urlparse(self.path).query)
            provided = params.get("debug_token", [None])[0]
        if provided == token:
            return True
        self._send_app_error(HTTPStatus.UNAUTHORIZED, ErrorCode.POLICY_VIOLATION, "인증되지 않음")
        return False

    def _authorize(self) -> bool:
        token = self.server.token
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth.split(" ", 1)[1] == token:
            return True
        if self.headers.get("X-NF-Token") == token:
            return True
        params = parse_qs(urlparse(self.path).query)
        query_token = params.get("token", [None])[0] or params.get("nf_token", [None])[0]
        if query_token == token:
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


def run_orchestrator(host: str = "127.0.0.1", port: int = 8080, *, start_worker: bool = True) -> None:
    """
    오케스트레이터 API 서버 실행(루프백 HTTP).
    """
    if start_worker:
        from modules.nf_workers.runner import run_worker

        worker_thread = threading.Thread(target=lambda: run_worker(db_path=None), daemon=True)
        worker_thread.start()
        print("Background worker started.")
    else:
        print("Background worker disabled.")

    token = os.environ.get("NF_ORCHESTRATOR_TOKEN")
    server = OrchestratorHTTPServer((host, port), OrchestratorHandler, token=token)
    server.serve_forever()
