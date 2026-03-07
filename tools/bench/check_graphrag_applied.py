from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from http_client import ApiClient as SharedApiClient, wait_for_job as shared_wait_for_job  # noqa: E402
from sse import read_job_events as shared_read_job_events  # noqa: E402


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ApiClient(SharedApiClient):
    pass


def _wait_for_job(client: ApiClient, job_id: str, *, timeout_sec: float = 1200.0) -> str:
    return shared_wait_for_job(client, job_id, timeout_sec=timeout_sec).status


def _read_job_events(client: ApiClient, job_id: str, *, after_seq: int = 0) -> list[tuple[int, dict[str, Any]]]:
    return shared_read_job_events(
        base_url=client.base_url,
        job_id=job_id,
        after_seq=after_seq,
        timeout=client.timeout,
    )


def _collect_grouping_counts(db_path: Path, project_id: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        entity_total = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM entity_mention_span
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()[0]
        )
        time_total = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM time_anchor
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()[0]
        )
        entity_non_rej = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM entity_mention_span
                WHERE project_id = ? AND status != 'REJECTED' AND entity_id IS NOT NULL AND entity_id != ''
                """,
                (project_id,),
            ).fetchone()[0]
        )
        time_non_rej = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM time_anchor
                WHERE project_id = ? AND status != 'REJECTED' AND time_key IS NOT NULL AND time_key != ''
                """,
                (project_id,),
            ).fetchone()[0]
        )
        timeline_non_rej = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM time_anchor
                WHERE project_id = ? AND status != 'REJECTED' AND timeline_idx IS NOT NULL
                """,
                (project_id,),
            ).fetchone()[0]
        )
        return {
            "entity_mentions_total": entity_total,
            "time_anchors_total": time_total,
            "entity_mentions_usable": entity_non_rej,
            "time_anchors_usable": time_non_rej,
            "timeline_anchors_usable": timeline_non_rej,
        }
    finally:
        conn.close()


def _load_project_id_from_artifact(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise RuntimeError(f"project_id missing in artifact: {path}")
    return project_id.strip()


def _discover_filters(db_path: Path, project_id: str, *, max_filters: int = 8) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        entity_rows = conn.execute(
            """
            SELECT DISTINCT entity_id
            FROM entity_mention_span
            WHERE project_id = ? AND status != 'REJECTED' AND entity_id IS NOT NULL AND entity_id != ''
            LIMIT 3
            """,
            (project_id,),
        ).fetchall()
        time_rows = conn.execute(
            """
            SELECT DISTINCT time_key, doc_id
            FROM time_anchor
            WHERE project_id = ? AND status != 'REJECTED' AND time_key IS NOT NULL AND time_key != ''
            LIMIT 3
            """,
            (project_id,),
        ).fetchall()
        timeline_rows = conn.execute(
            """
            SELECT DISTINCT timeline_idx, doc_id
            FROM time_anchor
            WHERE project_id = ? AND status != 'REJECTED' AND timeline_idx IS NOT NULL
            LIMIT 3
            """,
            (project_id,),
        ).fetchall()
    finally:
        conn.close()

    entity_ids = [str(row["entity_id"]) for row in entity_rows if row["entity_id"] is not None]
    time_keys = [
        {"time_key": str(row["time_key"]), "doc_id": str(row["doc_id"] or "")}
        for row in time_rows
        if row["time_key"] is not None
    ]
    timeline_idxs = [
        {"timeline_idx": int(row["timeline_idx"]), "doc_id": str(row["doc_id"] or "")}
        for row in timeline_rows
        if row["timeline_idx"] is not None
    ]

    candidates: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        candidates.append({"entity_id": entity_id})
    for row in time_keys:
        item: dict[str, Any] = {"time_key": row["time_key"]}
        if row["doc_id"]:
            item["doc_id"] = row["doc_id"]
        candidates.append(item)
    for row in timeline_idxs:
        item = {"timeline_idx": row["timeline_idx"]}
        if row["doc_id"]:
            item["doc_id"] = row["doc_id"]
        candidates.append(item)

    if entity_ids and time_keys:
        item = {"entity_id": entity_ids[0], "time_key": time_keys[0]["time_key"]}
        if time_keys[0]["doc_id"]:
            item["doc_id"] = time_keys[0]["doc_id"]
        candidates.append(item)
    if entity_ids and timeline_idxs:
        item = {"entity_id": entity_ids[0], "timeline_idx": timeline_idxs[0]["timeline_idx"]}
        if timeline_idxs[0]["doc_id"]:
            item["doc_id"] = timeline_idxs[0]["doc_id"]
        candidates.append(item)
    if time_keys and timeline_idxs:
        item = {"time_key": time_keys[0]["time_key"], "timeline_idx": timeline_idxs[0]["timeline_idx"]}
        if time_keys[0]["doc_id"]:
            item["doc_id"] = time_keys[0]["doc_id"]
        candidates.append(item)

    dedup: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        dedup[key] = item
    out = list(dedup.values())
    return out[: max(1, max_filters)]


def _extract_graph_meta(events: list[tuple[int, dict[str, Any]]]) -> dict[str, Any] | None:
    for _seq, event in reversed(events):
        if str(event.get("message") or "").strip().lower() != "retrieve_vec complete":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        graph = payload.get("graph")
        if isinstance(graph, dict):
            return graph
    return None


def _build_probe_query(filters: dict[str, Any]) -> str:
    time_key = filters.get("time_key")
    if isinstance(time_key, str) and time_key.strip():
        marker = "/rel:"
        if marker in time_key:
            rel = time_key.split(marker, 1)[1].strip()
            if rel:
                return rel
        return time_key.strip()
    entity_id = filters.get("entity_id")
    if isinstance(entity_id, str) and entity_id.strip():
        return entity_id.strip()
    timeline_idx = filters.get("timeline_idx")
    if timeline_idx is not None:
        try:
            return f"scene {int(timeline_idx)}"
        except (TypeError, ValueError):
            return "scene"
    return "graph probe"


def _summarize_probe_context(
    *,
    initial_filters_count: int,
    final_filters_count: int,
    bootstrap: dict[str, Any] | None,
    probe_count: int,
    applied_count: int,
    require_applied: bool,
) -> dict[str, Any]:
    bootstrap_used = bootstrap is not None
    bootstrap_status = str((bootstrap or {}).get("status") or "")
    bootstrap_succeeded = bootstrap_status == "SUCCEEDED"
    normal_path_ready = initial_filters_count > 0
    if normal_path_ready:
        validation_mode = "normal_path"
    elif bootstrap_used and bootstrap_succeeded and final_filters_count > 0:
        validation_mode = "bootstrap_assisted"
    else:
        validation_mode = "no_grouping"
    return {
        "probe_count": int(probe_count),
        "applied_count": int(applied_count),
        "require_applied": bool(require_applied),
        "normal_path_filter_count": int(initial_filters_count),
        "final_filter_count": int(final_filters_count),
        "normal_path_ready": bool(normal_path_ready),
        "bootstrap_used": bool(bootstrap_used),
        "bootstrap_status": bootstrap_status,
        "bootstrap_succeeded": bool(bootstrap_succeeded),
        "validation_mode": validation_mode,
    }


def _compact_text(text: str, *, limit: int = 140) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].strip()


def _query_from_anchor_span(db_path: Path, project_id: str, filters: dict[str, Any]) -> str | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        time_key = filters.get("time_key")
        if isinstance(time_key, str) and time_key:
            row = conn.execute(
                """
                SELECT ta.snapshot_id, ta.span_start, ta.span_end, ds.path
                FROM time_anchor ta
                JOIN doc_snapshots ds ON ds.snapshot_id = ta.snapshot_id
                WHERE ta.project_id = ? AND ta.time_key = ? AND ta.status != 'REJECTED'
                ORDER BY ta.created_at ASC
                LIMIT 1
                """,
                (project_id, time_key),
            ).fetchone()
            if row is not None:
                snapshot_path = Path(str(row["path"]))
                if snapshot_path.exists():
                    raw = snapshot_path.read_text(encoding="utf-8", errors="ignore")
                    start = max(0, int(row["span_start"]) - 24)
                    end = min(len(raw), int(row["span_end"]) + 48)
                    snippet = _compact_text(raw[start:end])
                    if snippet:
                        return snippet

        entity_id = filters.get("entity_id")
        if isinstance(entity_id, str) and entity_id:
            row = conn.execute(
                """
                SELECT em.snapshot_id, em.span_start, em.span_end, ds.path
                FROM entity_mention_span em
                JOIN doc_snapshots ds ON ds.snapshot_id = em.snapshot_id
                WHERE em.project_id = ? AND em.entity_id = ? AND em.status != 'REJECTED'
                ORDER BY em.created_at ASC
                LIMIT 1
                """,
                (project_id, entity_id),
            ).fetchone()
            if row is not None:
                snapshot_path = Path(str(row["path"]))
                if snapshot_path.exists():
                    raw = snapshot_path.read_text(encoding="utf-8", errors="ignore")
                    start = max(0, int(row["span_start"]) - 24)
                    end = min(len(raw), int(row["span_end"]) + 48)
                    snippet = _compact_text(raw[start:end])
                    if snippet:
                        return snippet
    finally:
        conn.close()
    return None


def _bootstrap_grouping(
    client: ApiClient,
    *,
    project_id: str,
    timeout_sec: float = 7200.0,
) -> dict[str, Any]:
    payload = {
        "type": "INDEX_FTS",
        "project_id": project_id,
        "inputs": {
            "scope": "global",
        },
        "params": {
            "grouping": {
                "entity_mentions": True,
                "time_anchors": True,
                "graph_extract": True,
            }
        },
    }
    created = client.post("/jobs", payload)
    job_id = str((created.get("job") or {}).get("job_id") or "")
    if not job_id:
        return {"job_id": "", "status": "CREATE_FAILED", "payload": None}
    status = _wait_for_job(client, job_id, timeout_sec=timeout_sec)
    step_payload: dict[str, Any] | None = None
    if status == "SUCCEEDED":
        events = _read_job_events(client, job_id, after_seq=0)
        for _seq, event in reversed(events):
            if str(event.get("message") or "").strip().lower() != "fts indexed":
                continue
            payload_obj = event.get("payload")
            if isinstance(payload_obj, dict):
                step_payload = payload_obj
            break
    return {"job_id": job_id, "status": status, "payload": step_payload}


def _raise_jobs_submit_context(
    *,
    stage: str,
    exc: RuntimeError,
    project_id: str,
    base_url: str,
    db_path: Path,
) -> None:
    message = str(exc)
    if "HTTP 404 /jobs" in message:
        raise SystemExit(
            f"{stage} failed: {message} "
            f"(hint: artifact-origin stack mismatch; project_id={project_id} base_url={base_url} db_path={db_path})"
        ) from exc
    raise exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe GraphRAG applied path using metadata filters.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8085")
    parser.add_argument("--db-path", default="nf_orchestrator.sqlite3")
    parser.add_argument("--pipeline-artifact", default=None)
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--graph-max-hops", type=int, default=1)
    parser.add_argument("--graph-rerank-weight", type=float, default=0.25)
    parser.add_argument("--max-probes", type=int, default=8)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output-dir", default="verify/benchmarks")
    parser.add_argument("--require-applied", action="store_true")
    parser.add_argument("--no-stop-on-first-applied", action="store_true")
    parser.add_argument("--bootstrap-grouping-if-empty", action="store_true")
    args = parser.parse_args()

    if args.graph_max_hops not in {1, 2}:
        raise SystemExit("--graph-max-hops must be 1 or 2")
    if not (0.0 <= args.graph_rerank_weight <= 0.5):
        raise SystemExit("--graph-rerank-weight must be between 0.0 and 0.5")
    if args.max_probes < 1:
        raise SystemExit("--max-probes must be >= 1")
    if args.k < 1:
        raise SystemExit("--k must be >= 1")

    project_id = (args.project_id or "").strip()
    if not project_id:
        artifact = args.pipeline_artifact
        if not artifact:
            raise SystemExit("one of --project-id or --pipeline-artifact is required")
        project_id = _load_project_id_from_artifact(Path(artifact))

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"db not found: {db_path}")

    bootstrap: dict[str, Any] | None = None
    filters_list = _discover_filters(db_path, project_id, max_filters=args.max_probes)
    initial_filters_count = len(filters_list)
    initial_counts = _collect_grouping_counts(db_path, project_id)
    final_counts = dict(initial_counts)
    if not filters_list and args.bootstrap_grouping_if_empty:
        try:
            bootstrap = _bootstrap_grouping(client=ApiClient(args.base_url), project_id=project_id)
        except RuntimeError as exc:
            _raise_jobs_submit_context(
                stage="bootstrap_grouping",
                exc=exc,
                project_id=project_id,
                base_url=args.base_url,
                db_path=db_path,
            )
        final_counts = _collect_grouping_counts(db_path, project_id)
        filters_list = _discover_filters(db_path, project_id, max_filters=args.max_probes)
    if not filters_list:
        summary = _summarize_probe_context(
            initial_filters_count=initial_filters_count,
            final_filters_count=0,
            bootstrap=bootstrap,
            probe_count=0,
            applied_count=0,
            require_applied=bool(args.require_applied),
        )
        result = {
            "ok": False,
            "project_id": project_id,
            "reason": "no_filters_discovered",
            "bootstrap": bootstrap,
            "counts": {"before": initial_counts, "after": final_counts},
            "probes": [],
            "summary": summary,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 2 if args.require_applied else 0

    client = ApiClient(args.base_url)
    probes: list[dict[str, Any]] = []
    applied_count = 0

    for idx, filters in enumerate(filters_list, start=1):
        query = _query_from_anchor_span(db_path, project_id, filters) or _build_probe_query(filters)
        payload = {
            "type": "RETRIEVE_VEC",
            "project_id": project_id,
            "inputs": {
                "query": query,
                "filters": filters,
                "k": int(args.k),
            },
            "params": {
                "graph": {
                    "enabled": True,
                    "max_hops": int(args.graph_max_hops),
                    "rerank_weight": float(args.graph_rerank_weight),
                }
            },
        }
        try:
            created = client.post("/jobs", payload)
        except RuntimeError as exc:
            _raise_jobs_submit_context(
                stage=f"probe#{idx}_submit",
                exc=exc,
                project_id=project_id,
                base_url=args.base_url,
                db_path=db_path,
            )
        job_id = str((created.get("job") or {}).get("job_id") or "")
        if not job_id:
            probes.append(
                {
                    "probe_idx": idx,
                    "query": query,
                    "filters": filters,
                    "job_id": "",
                    "status": "CREATE_FAILED",
                    "applied": False,
                    "graph": None,
                }
            )
            continue
        status = _wait_for_job(client, job_id)
        graph_meta = None
        if status == "SUCCEEDED":
            events = _read_job_events(client, job_id, after_seq=0)
            graph_meta = _extract_graph_meta(events)
        applied = bool((graph_meta or {}).get("applied"))
        if applied:
            applied_count += 1
        probes.append(
            {
                "probe_idx": idx,
                "query": query,
                "filters": filters,
                "job_id": job_id,
                "status": status,
                "applied": applied,
                "graph": graph_meta,
            }
        )
        if applied and not args.no_stop_on_first_applied:
            break

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"graphrag_probe_{stamp}.json"
    out_md = out_dir / f"graphrag_probe_{stamp}.md"

    summary = _summarize_probe_context(
        initial_filters_count=initial_filters_count,
        final_filters_count=len(filters_list),
        bootstrap=bootstrap,
        probe_count=len(probes),
        applied_count=applied_count,
        require_applied=bool(args.require_applied),
    )
    result = {
        "ok": applied_count > 0,
        "checked_at": now_ts(),
        "base_url": args.base_url,
        "db_path": str(db_path),
        "project_id": project_id,
        "bootstrap": bootstrap,
        "counts": {"before": initial_counts, "after": final_counts},
        "summary": summary,
        "probes": probes,
    }
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# GraphRAG Probe Summary ({stamp})",
        "",
        f"- project_id: `{project_id}`",
        f"- probe_count: `{len(probes)}`",
        f"- applied_count: `{applied_count}`",
        f"- require_applied: `{bool(args.require_applied)}`",
        f"- validation_mode: `{summary['validation_mode']}`",
        f"- normal_path_ready: `{summary['normal_path_ready']}`",
        f"- normal_path_filter_count: `{summary['normal_path_filter_count']}`",
        f"- final_filter_count: `{summary['final_filter_count']}`",
        f"- bootstrap_used: `{summary['bootstrap_used']}`",
        f"- bootstrap_status: `{summary['bootstrap_status']}`",
        f"- counts(before): `{initial_counts}`",
        f"- counts(after): `{final_counts}`",
        f"- bootstrap: `{bootstrap}`",
        f"- result: `{'PASS' if applied_count > 0 else 'FAIL'}`",
        "",
        "## Probes",
    ]
    for row in probes:
        lines.append(
            f"- probe#{row['probe_idx']}: status=`{row['status']}` applied=`{row['applied']}` query=`{row['query']}` filters=`{row['filters']}`"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"ok": applied_count > 0, "output": str(out_json), "summary": str(out_md)}, ensure_ascii=False))
    if args.require_applied and applied_count <= 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
