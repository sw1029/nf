from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

ADAPTER_VERSION = "nf-external-kg-v1"
MAX_PREVIEW_CHARS = 240
MAX_LIST_ITEMS = 80


def _safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _short_text(value: Any, limit: int = MAX_PREVIEW_CHARS) -> str:
    text = _safe_text(value)
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."


def _stable_hash(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        raw = str(value)
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def namespace_node_ref(source_id: str, native_id: Any) -> str:
    return f"ext:{source_id}:{_safe_text(native_id, _stable_hash(native_id))}"


def namespace_edge_ref(source_id: str, native_id: Any) -> str:
    return f"extedge:{source_id}:{_safe_text(native_id, _stable_hash(native_id))}"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _extract_refs(record: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("evidence_ids", "evidence_id", "source_span_refs", "source_span_ref", "evidence_refs"):
        for item in _as_list(record.get(key)):
            text = _safe_text(item)
            if text and text not in refs:
                refs.append(text)
    return refs


def _sanitize_payload(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return _short_text(value, 160)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(token in lowered for token in ("secret", "api_key", "token", "password")):
                out[key_text] = "[redacted]"
            elif lowered in {"quote", "text", "source_text", "content", "chunk", "prompt", "raw_text"}:
                out[key_text] = _short_text(item)
                if len(_safe_text(item)) > MAX_PREVIEW_CHARS:
                    out[f"{key_text}_truncated"] = True
            else:
                out[key_text] = _sanitize_payload(item, depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize_payload(item, depth + 1) for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, str):
        return _short_text(value, 800)
    return value


def _node_type_from_record(record: Mapping[str, Any]) -> str:
    raw = _safe_text(
        record.get("type")
        or record.get("node_type")
        or record.get("profile_type")
        or record.get("kind")
        or record.get("category")
    )
    value = raw.strip().lower()
    if value in {"char", "character", "person"}:
        return "Character"
    if value in {"loc", "place", "location"}:
        return "Place"
    if value in {"faction", "organization", "org"}:
        return "Faction"
    if value in {"object", "item"}:
        return "Object"
    if value in {"worldconcept", "world_concept", "rule", "setting"}:
        return "Setting"
    if value in {"event", "timeline_event", "episode", "snapshot"}:
        return "Event"
    if value in {"timecue", "time_cue", "time", "time_anchor"}:
        return "TimeCue"
    if value in {"textunit", "text_unit", "document", "chunk"}:
        return "TextUnit"
    if value in {"narrativecue", "narrative_cue", "foreshadowingsignal", "foreshadowing_signal"}:
        return "NarrativeCue"
    if value in {"contradictioncandidate", "contradiction_candidate", "contradiction"}:
        return "ContradictionCandidate"
    return "Fact"


def _internal_node_type_to_public(node: Mapping[str, Any]) -> str:
    node_type = _safe_text(node.get("node_type")).lower()
    payload = node.get("payload") if isinstance(node.get("payload"), Mapping) else {}
    if node_type == "entity":
        return _node_type_from_record({"kind": payload.get("kind")})
    if node_type == "timeline_event":
        return "Event"
    if node_type == "time_anchor":
        return "TimeCue"
    if node_type in {"document", "text_unit", "chunk"}:
        return "TextUnit"
    if node_type == "evidence":
        return "Evidence"
    if node_type == "schema_fact":
        return "Fact"
    return _node_type_from_record({"node_type": node_type})


def _first_value(record: Mapping[str, Any], keys: Iterable[str], fallback: Any = "") -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and _safe_text(value):
            return value
    return fallback


def _node_native_id(record: Mapping[str, Any], index: int) -> str:
    value = _first_value(
        record,
        (
            "id",
            "node_id",
            "canonical_id",
            "entity_id",
            "event_id",
            "timeline_event_id",
            "cue_id",
            "text_unit_id",
            "fact_id",
            "profile_id",
        ),
    )
    return _safe_text(value, f"node-{index}-{_stable_hash(record)}")


def _edge_native_id(record: Mapping[str, Any], index: int) -> str:
    value = _first_value(record, ("id", "edge_id", "relation_id", "mapping_id"))
    if _safe_text(value):
        return _safe_text(value)
    return f"edge-{index}-{_stable_hash(record)}"


def _node_label(record: Mapping[str, Any], native_id: str) -> str:
    return _short_text(
        _first_value(
            record,
            (
                "label",
                "display_name",
                "canonical_name",
                "name",
                "title",
                "surface_text",
                "summary",
                "value",
            ),
            native_id,
        ),
        80,
    )


def _node_aliases(record: Mapping[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in ("aliases", "surface_mentions", "mentions", "coreferences"):
        for item in _as_list(record.get(key)):
            if isinstance(item, Mapping):
                text = _safe_text(item.get("text") or item.get("surface") or item.get("alias"))
            else:
                text = _safe_text(item)
            if text and text not in aliases:
                aliases.append(_short_text(text, 80))
    return aliases[:MAX_LIST_ITEMS]


def _status(record: Mapping[str, Any]) -> str:
    return _safe_text(record.get("status") or record.get("review_status"), "ACTIVE")


def _confidence(record: Mapping[str, Any]) -> float:
    try:
        value = float(record.get("confidence", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, value))


def _parse_json_or_jsonl(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("records", "items", "nodes", "edges", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [value]
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        return _parse_json_or_jsonl(parsed)
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records


def _records_for_role(artifacts: Mapping[str, Any], *names: str) -> list[dict[str, Any]]:
    normalized = {str(key).lower().replace("\\", "/").rsplit("/", 1)[-1]: value for key, value in artifacts.items()}
    records: list[dict[str, Any]] = []
    for name in names:
        name_lower = name.lower()
        for key, value in normalized.items():
            stem = key.rsplit(".", 1)[0]
            if key == name_lower or stem == name_lower:
                records.extend(_parse_json_or_jsonl(value))
    return records


def _make_node(source_id: str, record: Mapping[str, Any], index: int, *, forced_type: str | None = None) -> dict[str, Any]:
    native_id = _node_native_id(record, index)
    return {
        "node_ref": namespace_node_ref(source_id, native_id),
        "native_id": native_id,
        "node_type": forced_type or _node_type_from_record(record),
        "label": _node_label(record, native_id),
        "aliases": _node_aliases(record),
        "payload": _sanitize_payload(dict(record)),
        "evidence_refs": _extract_refs(record),
        "status": _status(record),
        "confidence": _confidence(record),
    }


def _edge_end(record: Mapping[str, Any], keys: Iterable[str]) -> str:
    return _safe_text(_first_value(record, keys))


def _make_edge(
    source_id: str,
    record: Mapping[str, Any],
    index: int,
    *,
    src_native: str | None = None,
    dst_native: str | None = None,
    forced_type: str | None = None,
) -> dict[str, Any] | None:
    source_native = src_native or _edge_end(record, ("source_id", "src_node_id", "source", "from", "subject_id"))
    target_native = dst_native or _edge_end(record, ("target_id", "dst_node_id", "target", "to", "object_id"))
    if not source_native or not target_native or source_native == target_native:
        return None
    native_id = _edge_native_id(record, index)
    edge_type = _safe_text(
        forced_type or record.get("edge_type") or record.get("relation_type") or record.get("type"),
        "RELATED",
    )
    return {
        "edge_ref": namespace_edge_ref(source_id, native_id),
        "native_id": native_id,
        "src_node_ref": namespace_node_ref(source_id, source_native),
        "dst_node_ref": namespace_node_ref(source_id, target_native),
        "edge_type": edge_type,
        "label": _short_text(record.get("label") or edge_type, 80),
        "payload": _sanitize_payload(dict(record)),
        "evidence_refs": _extract_refs(record),
        "status": _status(record),
        "confidence": _confidence(record),
    }


def _bundle(
    *,
    source_id: str,
    source_label: str,
    source_kind: str,
    schema_version: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_label": source_label,
        "source_kind": source_kind,
        "schema_version": schema_version or "unknown",
        "adapter_version": ADAPTER_VERSION,
        "nodes": nodes,
        "edges": edges,
        "warnings": warnings or [],
        "metadata": metadata or {},
    }


def bundle_from_project_kg(
    *,
    source_id: str,
    source_label: str,
    linked_project_id: str,
    kg: dict[str, Any] | None,
) -> dict[str, Any]:
    kg = kg or {}
    raw_nodes = kg.get("nodes") if isinstance(kg.get("nodes"), list) else []
    raw_edges = kg.get("edges") if isinstance(kg.get("edges"), list) else []
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, Mapping):
            continue
        native_id = _safe_text(raw.get("node_id"), f"node-{index}")
        payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else {}
        record = {
            **dict(payload),
            "id": native_id,
            "node_type": _internal_node_type_to_public(raw),
            "label": raw.get("label"),
            "status": raw.get("status"),
            "confidence": raw.get("confidence"),
        }
        node = _make_node(source_id, record, index, forced_type=_internal_node_type_to_public(raw))
        nodes.append(node)
        node_ids.add(native_id)

    edges: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_edges):
        if not isinstance(raw, Mapping):
            continue
        src = _safe_text(raw.get("src_node_id"))
        dst = _safe_text(raw.get("dst_node_id"))
        if src not in node_ids or dst not in node_ids:
            continue
        payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else {}
        record = {
            **dict(payload),
            "id": raw.get("edge_id"),
            "edge_type": raw.get("edge_type"),
            "label": raw.get("edge_type"),
            "status": raw.get("status"),
            "confidence": raw.get("confidence"),
        }
        edge = _make_edge(source_id, record, index, src_native=src, dst_native=dst)
        if edge:
            edges.append(edge)

    warnings = [] if nodes else ["선택한 프로젝트에서 가져올 관계도 요소를 찾지 못했습니다."]
    return _bundle(
        source_id=source_id,
        source_label=source_label,
        source_kind="nf_project",
        schema_version=_safe_text((kg.get("build") or {}).get("build_id"), "nf-project-kg"),
        nodes=nodes,
        edges=edges,
        warnings=warnings,
        metadata={"linked_project_id": linked_project_id},
    )


def bundle_from_external_bundle(
    *,
    source_id: str,
    payload: Mapping[str, Any],
    fallback_label: str = "가져온 작품",
) -> dict[str, Any]:
    raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    raw_edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    nodes = []
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, Mapping):
            continue
        native_id = _safe_text(raw.get("native_id") or raw.get("id") or raw.get("node_ref"), f"node-{index}")
        record = {**dict(raw), "id": native_id}
        nodes.append(_make_node(source_id, record, index, forced_type=_safe_text(raw.get("node_type") or raw.get("type"), "Fact")))

    edges = []
    for index, raw in enumerate(raw_edges):
        if not isinstance(raw, Mapping):
            continue
        src = _safe_text(raw.get("source") or raw.get("src_node_ref") or raw.get("source_id"))
        dst = _safe_text(raw.get("target") or raw.get("dst_node_ref") or raw.get("target_id"))
        if src.startswith("ext:"):
            src = src.rsplit(":", 1)[-1]
        if dst.startswith("ext:"):
            dst = dst.rsplit(":", 1)[-1]
        edge = _make_edge(source_id, raw, index, src_native=src, dst_native=dst)
        if edge:
            edges.append(edge)

    return _bundle(
        source_id=source_id,
        source_label=_safe_text(payload.get("source_label"), fallback_label),
        source_kind=_safe_text(payload.get("source_kind"), "dataset_artifact_set"),
        schema_version=_safe_text(payload.get("schema_version"), "unknown"),
        nodes=nodes,
        edges=edges,
        warnings=list(payload.get("warnings") or []),
        metadata=_sanitize_payload(payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}),
    )


def bundle_from_artifacts(
    *,
    source_id: str,
    source_label: str,
    artifacts: Mapping[str, Any],
    schema_version: str | None = None,
) -> dict[str, Any]:
    if isinstance(artifacts.get("bundle"), Mapping):
        return bundle_from_external_bundle(source_id=source_id, payload=artifacts["bundle"], fallback_label=source_label)

    node_records = _records_for_role(artifacts, "kg_nodes", "nodes", "entity_dict")
    edge_records = _records_for_role(artifacts, "kg_edges", "edges")
    mention_records = _records_for_role(artifacts, "mention_mapping", "mentions")
    timeline_records = _records_for_role(artifacts, "timeline", "timeline_events")
    cue_records = _records_for_role(artifacts, "narrative_cues", "foreshadowing_signals")

    nodes_by_native_id: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(node_records):
        node = _make_node(source_id, record, index)
        nodes_by_native_id[node["native_id"]] = node

    offset = len(nodes_by_native_id)
    for index, record in enumerate(timeline_records):
        if not isinstance(record, Mapping):
            continue
        native_id = _node_native_id(record, offset + index)
        if native_id in nodes_by_native_id:
            continue
        node = _make_node(source_id, record, offset + index, forced_type="Event")
        nodes_by_native_id[node["native_id"]] = node

    offset += len(timeline_records)
    for index, record in enumerate(cue_records):
        native_id = _node_native_id(record, offset + index)
        if native_id in nodes_by_native_id:
            continue
        node = _make_node(source_id, record, offset + index, forced_type="NarrativeCue")
        nodes_by_native_id[node["native_id"]] = node

    edges: list[dict[str, Any]] = []
    for index, record in enumerate(edge_records):
        edge = _make_edge(source_id, record, index)
        if edge:
            edges.append(edge)

    for index, record in enumerate(mention_records):
        text_unit_id = _safe_text(record.get("text_unit_id") or record.get("source_text_unit_id"))
        target_id = _safe_text(record.get("target_id") or record.get("node_id") or record.get("entity_id"))
        if not text_unit_id or not target_id:
            continue
        if text_unit_id not in nodes_by_native_id:
            nodes_by_native_id[text_unit_id] = _make_node(
                source_id,
                {"id": text_unit_id, "type": "TextUnit", "label": text_unit_id, **dict(record)},
                offset + index,
                forced_type="TextUnit",
            )
        edge = _make_edge(
            source_id,
            {**dict(record), "edge_type": "MENTION_MAPPING", "label": "원문 언급"},
            len(edges) + index,
            src_native=target_id,
            dst_native=text_unit_id,
        )
        if edge:
            edges.append(edge)

    warnings: list[str] = []
    if not nodes_by_native_id:
        warnings.append("가져온 파일에서 관계도 요소를 찾지 못했습니다.")
    if edge_records and not edges:
        warnings.append("관계 정보는 있었지만 연결할 수 있는 시작/대상 요소를 찾지 못했습니다.")

    return _bundle(
        source_id=source_id or str(uuid.uuid4()),
        source_label=source_label,
        source_kind="dataset_artifact_set",
        schema_version=schema_version or "story-package-compatible",
        nodes=list(nodes_by_native_id.values()),
        edges=edges,
        warnings=warnings,
        metadata={"artifact_names": sorted(str(key) for key in artifacts.keys())},
    )
