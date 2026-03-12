from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import build_novel_dataset as dataset_builder  # noqa: E402
from check_consistency_strict_gate import evaluate_strict_gate  # noqa: E402
from common import build_run_manifest, hash_file, now_ts  # noqa: E402
from judge_audit import judge_inject_quality, judge_source_policy  # noqa: E402
from modules.nf_model_gateway.local.model_store import describe_model  # noqa: E402
from modules.nf_model_gateway.remote.provider import (  # noqa: E402
    remote_provider_credentials_configured,
    selected_remote_model_id,
    selected_remote_provider_name,
)
from modules.nf_shared.config import load_config  # noqa: E402
from render_dev_judge_report import render_dev_judge_report  # noqa: E402


_TYPED_VARIANT_DATASETS = {
    "DS-INJECT-C-TYPED": ("DS-INJECT-C-STRUCTURED.jsonl", "DS-INJECT-C.jsonl"),
    "DS-DIVERSE-INJECT-C-TYPED": ("DS-DIVERSE-INJECT-C-STRUCTURED.jsonl", "DS-DIVERSE-INJECT-C.jsonl"),
}
_TYPED_VARIANT_FALLBACK_BASESETS = {
    "DS-INJECT-C-TYPED": ("DS-GROWTH-200.jsonl",),
    "DS-DIVERSE-INJECT-C-TYPED": ("DS-DIVERSE-200.jsonl", "DS-GROWTH-200.jsonl"),
}
_TYPED_INJECT_KINDS = ("age", "job", "talent", "time", "affiliation", "relation", "death", "place")
_FRONT_MATTER_TOKENS = ("all rights", "produced in korea", "머리말", "프롤로그", "prologue", "차례")
_SUBJECT_STOPWORDS = {
    "주인공",
    "직업",
    "관계",
    "소속",
    "재능",
    "장소",
    "위치",
    "사건",
    "인물",
    "그",
    "그녀",
}
_SHADOW_MIN_EPISODES = 3
_SHADOW_MIN_MEDIAN_CHARS = 80
_SHADOW_SHORT_SEGMENT_CHARS = 40
_SHADOW_MAX_SHORT_SEGMENT_SHARE = 0.35
_SHADOW_OVERSIZED_SEGMENT_CHARS = 20000
_SHADOW_MAX_OVERSIZED_SEGMENT_SHARE = 0.10
_SHADOW_DOMINANT_PATTERN_MIN_COUNT = 3
_SHADOW_DOMINANT_PATTERN_MIN_SHARE = 0.85
_SHADOW_DOMINANT_PATTERN_ALLOWLIST = {
    "episode_hwa",
    "angle_episode_hwa",
    "title_number_hwa",
    "ep_prefix",
    "bracketed_numbered_title",
    "section_jo",
    "numbered_title",
    "angle_title_paren",
    "plain_title_paren",
    "standalone_number",
}
_STRICT_ARTIFACT_LABELS = {
    "baseline": ("operational-main:DS-200",),
    "control": ("operational-strict-main:DS-CONTROL-D",),
    "inject": ("operational-strict-main:DS-INJECT-C",),
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return payload


def _judge_backend_availability() -> dict[str, Any]:
    settings = load_config()
    local_model_id = str(settings.test_judge_local_nli_model_id or "")
    local_model_status = describe_model(local_model_id) if local_model_id else {
        "path": None,
        "present": False,
        "manifest_backend": "",
        "runtime_ready": False,
        "reason": "missing",
    }
    local_model_path = local_model_status.get("path")
    remote_provider = selected_remote_provider_name()
    remote_model_id = selected_remote_model_id()
    local_enabled = bool(settings.enable_test_judge_local_nli)
    remote_enabled = bool(settings.enable_test_judge_remote_api)
    if local_enabled and bool(local_model_status.get("runtime_ready")):
        expected_mode = "local_model_ready"
    elif remote_enabled and remote_provider_credentials_configured():
        expected_mode = "remote_api_ready"
    elif local_enabled and bool(local_model_status.get("present")):
        expected_mode = "heuristic_only_local_model_unusable"
    elif local_enabled:
        expected_mode = "heuristic_only_local_model_missing"
    elif remote_enabled:
        expected_mode = "remote_api_requested_but_credentials_missing"
    else:
        expected_mode = "disabled"
    return {
        "requested_backend": (
            "local_nli"
            if local_enabled
            else ("remote_api" if remote_enabled else "disabled")
        ),
        "local_test_judge_enabled": local_enabled,
        "local_model_id": local_model_id,
        "local_model_present": bool(local_model_status.get("present")),
        "local_model_path": str(local_model_path) if local_model_path is not None else "",
        "local_model_runtime_ready": bool(local_model_status.get("runtime_ready")),
        "local_model_manifest_backend": str(local_model_status.get("manifest_backend") or ""),
        "local_model_status_reason": str(local_model_status.get("reason") or ""),
        "remote_test_judge_enabled": remote_enabled,
        "remote_provider": remote_provider,
        "remote_model_id": remote_model_id,
        "remote_credentials_configured": remote_provider_credentials_configured(),
        "expected_execution_mode": expected_mode,
    }


def _apply_judge_backend_overrides(
    *,
    judge_backend: str,
    judge_local_model_id: str,
) -> dict[str, Any]:
    backend = str(judge_backend or "config").strip().lower()
    if backend not in {"config", "disabled", "local_nli", "remote_api"}:
        raise SystemExit(f"unsupported judge backend override: {judge_backend}")
    if backend == "disabled":
        os.environ["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "false"
        os.environ["NF_ENABLE_TEST_JUDGE_REMOTE_API"] = "false"
    elif backend == "local_nli":
        os.environ["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "true"
        os.environ["NF_ENABLE_TEST_JUDGE_REMOTE_API"] = "false"
    elif backend == "remote_api":
        os.environ["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "false"
        os.environ["NF_ENABLE_TEST_JUDGE_REMOTE_API"] = "true"
    if str(judge_local_model_id or "").strip():
        os.environ["NF_TEST_JUDGE_LOCAL_NLI_MODEL_ID"] = str(judge_local_model_id).strip()
    return {
        "judge_backend": backend,
        "judge_local_model_id": str(judge_local_model_id or "").strip(),
    }


def _guard_real_judge_backend_required(*, required: bool, availability: dict[str, Any]) -> None:
    if not required:
        return
    expected_mode = str(availability.get("expected_execution_mode") or "")
    if expected_mode in {"local_model_ready", "remote_api_ready"}:
        return
    raise SystemExit(
        "real judge backend is required but unavailable: "
        f"expected_execution_mode={expected_mode}"
    )


def _guard_developer_mode(enabled: bool) -> None:
    if not enabled:
        raise SystemExit("--developer-mode is required for judged dataset pipeline")


def _guard_output_root(output_root: Path) -> None:
    canonical_dir = (Path("verify") / "datasets").resolve()
    resolved = output_root.resolve()
    if resolved == canonical_dir or resolved.is_relative_to(canonical_dir):
        raise SystemExit("developer-only pipeline must not write under verify/datasets")


def _build_baseline_snapshot(
    *,
    input_dir: Path,
    baseline_snapshot_dir: Path,
    inject_sample_size: int,
    seed: int,
    diversity_profile: str,
) -> dict[str, Any]:
    baseline_snapshot_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "false"
    env["NF_ENABLE_TEST_JUDGE_REMOTE_API"] = "false"
    proc = subprocess.run(
        [
            sys.executable,
            str(_THIS_DIR / "build_novel_dataset.py"),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(baseline_snapshot_dir),
            "--inject-sample-size",
            str(inject_sample_size),
            "--seed",
            str(seed),
            "--diversity-profile",
            diversity_profile,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    if not isinstance(payload, dict) or not bool(payload.get("ok")):
        raise SystemExit("baseline snapshot build failed")
    return payload


def _copy_baseline_snapshot(source_dir: Path, baseline_snapshot_dir: Path) -> None:
    shutil.copytree(source_dir, baseline_snapshot_dir, dirs_exist_ok=True)


def _artifact_bench_label(path: Path) -> str:
    try:
        payload = _read_json(path)
    except Exception:  # noqa: BLE001
        return ""
    return str(payload.get("bench_label") or "")


def _artifact_consistency_runtime(path: Path) -> dict[str, Any]:
    try:
        payload = _read_json(path)
    except Exception:  # noqa: BLE001
        return {}
    runtime = payload.get("consistency_runtime")
    if isinstance(runtime, dict):
        return runtime
    throughput = ((payload.get("runs") or {}).get("throughput") or {})
    runtime = throughput.get("consistency_runtime")
    return runtime if isinstance(runtime, dict) else {}


def _artifact_has_layer3_effective_capability(path: Path) -> bool:
    runtime = _artifact_consistency_runtime(path)
    try:
        effective_jobs = int(runtime.get("layer3_effective_capable_jobs", 0) or 0)
    except (TypeError, ValueError):
        effective_jobs = 0
    return effective_jobs > 0


def _discover_latest_bench_artifact(
    bench_dir: Path,
    labels: tuple[str, ...],
    *,
    require_layer3_effective: bool = False,
) -> Path | None:
    for path in sorted(bench_dir.glob("*.json"), reverse=True):
        if _artifact_bench_label(path) in labels:
            if require_layer3_effective and not _artifact_has_layer3_effective_capability(path):
                continue
            return path
    return None


def _resolve_strict_artifacts(
    *,
    baseline_artifact: Path | None,
    control_artifact: Path | None,
    inject_artifact: Path | None,
    strict_artifact_dir: Path | None,
) -> tuple[Path | None, Path | None, Path | None, dict[str, Any]]:
    explicit = [item for item in (baseline_artifact, control_artifact, inject_artifact) if item is not None]
    if explicit and len(explicit) != 3:
        raise SystemExit("strict layer3 audit requires baseline/control/inject artifacts together")
    if len(explicit) == 3:
        return baseline_artifact, control_artifact, inject_artifact, {
            "mode": "explicit",
            "status": "complete",
            "artifact_dir": "",
            "missing": [],
            "artifacts": {
                "baseline_artifact": str(baseline_artifact),
                "control_artifact": str(control_artifact),
                "inject_artifact": str(inject_artifact),
            },
        }
    if strict_artifact_dir is None:
        return None, None, None, {
            "mode": "disabled",
            "status": "not_requested",
            "artifact_dir": "",
            "missing": ["baseline", "control", "inject"],
            "artifacts": {},
        }
    if not strict_artifact_dir.exists():
        raise SystemExit(f"missing strict artifact dir: {strict_artifact_dir}")

    resolved_baseline = _discover_latest_bench_artifact(strict_artifact_dir, _STRICT_ARTIFACT_LABELS["baseline"])
    resolved_control = _discover_latest_bench_artifact(
        strict_artifact_dir,
        _STRICT_ARTIFACT_LABELS["control"],
        require_layer3_effective=True,
    ) or _discover_latest_bench_artifact(strict_artifact_dir, _STRICT_ARTIFACT_LABELS["control"])
    resolved_inject = _discover_latest_bench_artifact(
        strict_artifact_dir,
        _STRICT_ARTIFACT_LABELS["inject"],
        require_layer3_effective=True,
    ) or _discover_latest_bench_artifact(strict_artifact_dir, _STRICT_ARTIFACT_LABELS["inject"])
    missing = [
        name
        for name, value in (
            ("baseline", resolved_baseline),
            ("control", resolved_control),
            ("inject", resolved_inject),
        )
        if value is None
    ]
    if missing:
        return None, None, None, {
            "mode": "auto_discovery",
            "status": "incomplete",
            "artifact_dir": str(strict_artifact_dir),
            "missing": missing,
            "artifacts": {
                "baseline_artifact": str(resolved_baseline) if resolved_baseline is not None else "",
                "control_artifact": str(resolved_control) if resolved_control is not None else "",
                "inject_artifact": str(resolved_inject) if resolved_inject is not None else "",
            },
        }
    return resolved_baseline, resolved_control, resolved_inject, {
        "mode": "auto_discovery",
        "status": "complete",
        "artifact_dir": str(strict_artifact_dir),
        "missing": [],
        "artifacts": {
            "baseline_artifact": str(resolved_baseline),
            "control_artifact": str(resolved_control),
            "inject_artifact": str(resolved_inject),
        },
    }


def _collect_candidate_features(text: str) -> tuple[list[tuple[int, int, str, str]], dict[str, int], list[dict[str, Any]], dict[str, Any]]:
    lines = text.splitlines(keepends=True)
    candidate_boundaries: list[tuple[int, int, str, str]] = []
    candidate_boundary_counts = {name: 0 for name in dataset_builder._PATTERN_NAMES}
    offset = 0
    previous_blank = True
    blank_lines = 0
    nonempty_lines: list[str] = []
    for line in lines:
        line_text = line.rstrip("\r\n")
        if not line_text.strip():
            blank_lines += 1
        else:
            nonempty_lines.append(line_text.strip())
        matched = dataset_builder._match_episode_header(
            line_text,
            allow_title_patterns=previous_blank or offset == 0,
        )
        if matched is not None:
            episode_no, pattern_name = matched
            candidate_boundaries.append((offset, episode_no, line_text, pattern_name))
            candidate_boundary_counts[pattern_name] += 1
        offset += len(line)
        previous_blank = not bool(line_text.strip())
    samples = dataset_builder._candidate_line_samples(candidate_boundaries)
    head_lines = [line.lower() for line in nonempty_lines[:60]]
    front_matter_hits = sum(1 for line in head_lines if any(token in line for token in _FRONT_MATTER_TOKENS))
    feature_bundle = {
        "text_chars": len(text),
        "line_count": len(lines),
        "nonempty_line_count": len(nonempty_lines),
        "blank_line_ratio": (float(blank_lines) / float(len(lines))) if lines else 0.0,
        "boundary_density_per_1k_chars": (
            float(sum(candidate_boundary_counts.values())) * 1000.0 / float(max(1, len(text)))
        ),
        "front_matter_hits": front_matter_hits,
        "head_nonempty_lines": len(head_lines),
    }
    return candidate_boundaries, candidate_boundary_counts, samples, feature_bundle


def _summarize_source_policy_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    effective_backend_counts = Counter(str(row.get("judge_effective_backend") or "") for row in rows if row.get("judge_effective_backend"))
    segmentation_policy_counts = Counter(str(row.get("segmentation_policy") or "") for row in rows if row.get("segmentation_policy"))
    judged_rows = sum(1 for row in rows if str(row.get("audit_status") or "") == "judged")
    shadow_apply_status_counts = Counter(str(row.get("shadow_apply_status") or "") for row in rows if row.get("shadow_apply_status"))
    return {
        "rows_total": len(rows),
        "judged_rows": judged_rows,
        "skipped_rows": len(rows) - judged_rows,
        "effective_backend_counts": dict(effective_backend_counts),
        "fallback_used_count": sum(1 for row in rows if bool(row.get("judge_fallback_used"))),
        "segmentation_policy_counts": dict(segmentation_policy_counts),
        "shadow_apply_status_counts": dict(shadow_apply_status_counts),
    }


def _summarize_inject_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    effective_backend_counts = Counter(str(row.get("judge_effective_backend") or "") for row in rows if row.get("judge_effective_backend"))
    label_counts = Counter(str(row.get("inject_quality_label") or "") for row in rows if row.get("inject_quality_label"))
    judged_rows = sum(1 for row in rows if str(row.get("audit_status") or "") == "judged")
    dataset_counts = Counter(str(row.get("dataset") or "") for row in rows if row.get("dataset"))
    return {
        "rows_total": len(rows),
        "judged_rows": judged_rows,
        "skipped_rows": len(rows) - judged_rows,
        "effective_backend_counts": dict(effective_backend_counts),
        "fallback_used_count": sum(1 for row in rows if bool(row.get("judge_fallback_used"))),
        "label_counts": dict(label_counts),
        "dataset_counts": dict(dataset_counts),
    }


def _compare_snapshot_with_canonical(snapshot_dir: Path, canonical_dir: Path) -> dict[str, Any]:
    compared_files = 0
    identical_files = 0
    changed_files = 0
    missing_in_canonical = 0
    file_diffs: list[dict[str, Any]] = []
    for path in sorted(snapshot_dir.glob("*")):
        if path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        compared_files += 1
        candidate = canonical_dir / path.name
        row = {"file_name": path.name, "snapshot_sha256": hash_file(path)}
        if not candidate.exists():
            missing_in_canonical += 1
            row["status"] = "missing_in_canonical"
            file_diffs.append(row)
            continue
        row["canonical_sha256"] = hash_file(candidate)
        if row["snapshot_sha256"] == row["canonical_sha256"]:
            identical_files += 1
            row["status"] = "identical"
        else:
            changed_files += 1
            row["status"] = "changed"
        file_diffs.append(row)
    return {
        "snapshot_dir": str(snapshot_dir),
        "canonical_dir": str(canonical_dir),
        "compared_files": compared_files,
        "identical_files": identical_files,
        "changed_files": changed_files,
        "missing_in_canonical": missing_in_canonical,
        "file_diffs": file_diffs,
    }


def _source_policy_shadow_trigger_reasons(*, stats: dict[str, Any], threshold: float) -> list[str]:
    reasons: list[str] = []
    policy_decision_source = str(stats.get("policy_decision_source") or "")
    current_policy = str(stats.get("source_segmentation_policy") or "")
    confidence = float(stats.get("policy_confidence") or 0.0)
    content_length_stats = dict(stats.get("content_length_stats") or {})
    min_chars = int(content_length_stats.get("min_chars") or 0)
    max_chars = int(content_length_stats.get("max_chars") or 0)

    if policy_decision_source != "profile_auto":
        return reasons
    if confidence < threshold:
        reasons.append("profile_auto_below_confidence_threshold")
    if current_policy == "manual_review":
        reasons.append("profile_auto_manual_review")
    if min_chars > 0 and min_chars < dataset_builder._WARN_MIN_SEGMENT_CHARS:
        reasons.append("undersized_segments_present")
    if max_chars > dataset_builder._WARN_MAX_SEGMENT_CHARS:
        reasons.append("oversized_segments_present")
    return reasons


def _source_policy_judgments(*, input_dir: Path) -> list[dict[str, Any]]:
    settings = load_config()
    threshold = float(settings.test_judge_min_confidence)
    registry, _ = dataset_builder._load_source_policy_registry()
    rows: list[dict[str, Any]] = []
    for src in sorted(input_dir.glob("*.txt")):
        text, _ = dataset_builder.read_text_auto(src)
        content_sha256 = dataset_builder._sha256_file(src)
        source_id = dataset_builder.make_source_id(content_sha256)
        source_policy = dataset_builder._source_policy_from_registry(registry.get(content_sha256))
        _candidate_boundaries, candidate_boundary_counts, candidate_line_samples, feature_bundle = _collect_candidate_features(text)
        _episodes, stats = dataset_builder.split_episodes_with_stats(
            text,
            source_file=src.name,
            source_id=source_id,
            source_content_sha256=content_sha256,
            source_policy=source_policy,
        )
        row: dict[str, Any] = {
            "source_id": source_id,
            "content_sha256": content_sha256,
            "source_file": src.name,
            "current_segmentation_policy": stats.get("source_segmentation_policy"),
            "current_policy_decision_source": stats.get("policy_decision_source"),
            "current_policy_confidence": stats.get("policy_confidence"),
            "current_segment_quality_flags": {
                "undersized": bool(
                    int((stats.get("content_length_stats") or {}).get("min_chars", 0) or 0)
                    < dataset_builder._WARN_MIN_SEGMENT_CHARS
                    and int((stats.get("content_length_stats") or {}).get("min_chars", 0) or 0) > 0
                ),
                "oversized": bool(
                    int((stats.get("content_length_stats") or {}).get("max_chars", 0) or 0)
                    > dataset_builder._WARN_MAX_SEGMENT_CHARS
                ),
            },
            "candidate_boundary_counts": candidate_boundary_counts,
            "candidate_line_samples": candidate_line_samples,
            "content_length_stats": {
                **dict(stats.get("content_length_stats") or {}),
                **feature_bundle,
            },
        }
        audit_trigger_reasons = _source_policy_shadow_trigger_reasons(stats=stats, threshold=threshold)
        row["audit_trigger_reasons"] = list(audit_trigger_reasons)
        should_judge = bool(audit_trigger_reasons)
        if should_judge:
            judged = judge_source_policy(
                source_id=source_id,
                content_sha256=content_sha256,
                candidate_boundary_counts=candidate_boundary_counts,
                content_length_stats={
                    **dict(stats.get("content_length_stats") or {}),
                    **feature_bundle,
                },
                candidate_line_samples=candidate_line_samples,
                settings=settings,
            )
            row.update(judged)
            row["audit_status"] = "judged"
        else:
            row["audit_status"] = "skipped_not_shadow_candidate"
        rows.append(row)
    return rows


def _validate_source_policy_shadow_apply(
    *,
    source_id: str,
    source_file: str,
    text: str,
    content_sha256: str,
    judged_row: dict[str, Any],
) -> tuple[bool, dict[str, Any], list[dataset_builder.Episode]]:
    candidate_boundary_counts = {
        str(key): int(value)
        for key, value in dict(judged_row.get("candidate_boundary_counts") or {}).items()
        if key != "total"
    }
    accepted_pattern_family = [
        str(item) for item in (judged_row.get("accepted_pattern_family") or []) if isinstance(item, str)
    ]
    accepted_pattern_family_source = "judge_output"
    if not accepted_pattern_family:
        reason = str(judged_row.get("reason") or "")
        current_policy = str(judged_row.get("current_segmentation_policy") or "")
        current_decision_source = str(judged_row.get("current_policy_decision_source") or "")
        ranked_patterns = sorted(
            (
                (name, int(count))
                for name, count in candidate_boundary_counts.items()
                if name in _SHADOW_DOMINANT_PATTERN_ALLOWLIST and int(count) > 0
            ),
            key=lambda item: (-item[1], item[0]),
        )
        if (
            reason == "judge_confidence_below_threshold"
            and current_policy == "auto"
            and current_decision_source == "profile_auto"
            and ranked_patterns
        ):
            total = max(1, sum(count for _name, count in ranked_patterns))
            top_name, top_count = ranked_patterns[0]
            top_share = float(top_count) / float(total)
            if top_count >= _SHADOW_DOMINANT_PATTERN_MIN_COUNT and top_share >= _SHADOW_DOMINANT_PATTERN_MIN_SHARE:
                accepted_pattern_family = [top_name]
                accepted_pattern_family_source = "dominant_pattern_fallback"
    feature_bundle = dict(judged_row.get("content_length_stats") or {})
    candidate_count_exists = bool(accepted_pattern_family) and any(
        int(candidate_boundary_counts.get(name, 0)) > 0 for name in accepted_pattern_family
    )
    override_policy = {
        "segmentation_policy": str(judged_row.get("segmentation_policy") or "manual_review"),
        "allowed_patterns": accepted_pattern_family,
        "policy_decision_source": "judge_shadow_apply",
        "policy_confidence": float(judged_row.get("confidence") or 0.0),
        "reason": str(judged_row.get("reason") or ""),
        "judge_backend": str(judged_row.get("judge_backend") or ""),
        "judge_requested_backend": str(judged_row.get("judge_requested_backend") or ""),
        "judge_effective_backend": str(judged_row.get("judge_effective_backend") or ""),
        "judge_model_id": str(judged_row.get("judge_model_id") or ""),
        "judge_prompt_version": str(judged_row.get("judge_prompt_version") or ""),
        "judge_fallback_used": bool(judged_row.get("judge_fallback_used", False)),
        "judge_input_hash": str(judged_row.get("judge_input_hash") or ""),
    }
    episodes, stats = dataset_builder.split_episodes_with_stats(
        text,
        source_file=source_file,
        source_id=source_id,
        source_content_sha256=content_sha256,
        source_policy=override_policy,
    )
    lengths = [len(episode.content) for episode in episodes if str(episode.content or "").strip()]
    episode_count = len(lengths)
    median_chars = int(stats.get("content_length_stats", {}).get("median_chars") or 0)
    short_segment_share = (
        float(sum(1 for length in lengths if length < _SHADOW_SHORT_SEGMENT_CHARS)) / float(episode_count)
        if episode_count
        else 1.0
    )
    oversized_share = (
        float(sum(1 for length in lengths if length > _SHADOW_OVERSIZED_SEGMENT_CHARS)) / float(episode_count)
        if episode_count
        else 1.0
    )
    head_nonempty_lines = int(feature_bundle.get("head_nonempty_lines") or 0)
    front_matter_hits = int(feature_bundle.get("front_matter_hits") or 0)
    front_matter_dominant = (
        front_matter_hits >= 2 and head_nonempty_lines > 0 and (float(front_matter_hits) / float(head_nonempty_lines)) >= 0.30
    )
    passed = (
        candidate_count_exists
        and str(stats.get("split_strategy") or "") == "header_boundary"
        and episode_count >= _SHADOW_MIN_EPISODES
        and median_chars >= _SHADOW_MIN_MEDIAN_CHARS
        and short_segment_share <= _SHADOW_MAX_SHORT_SEGMENT_SHARE
        and oversized_share <= _SHADOW_MAX_OVERSIZED_SEGMENT_SHARE
        and not front_matter_dominant
    )
    details = {
        "candidate_count_exists": candidate_count_exists,
        "accepted_pattern_family": accepted_pattern_family,
        "accepted_pattern_family_source": accepted_pattern_family_source,
        "split_strategy": str(stats.get("split_strategy") or ""),
        "episode_count": episode_count,
        "median_chars": median_chars,
        "short_segment_share": short_segment_share,
        "oversized_share": oversized_share,
        "front_matter_dominant": front_matter_dominant,
    }
    return passed, details, episodes


def _build_source_policy_shadow_apply(
    *,
    input_dir: Path,
    source_rows: list[dict[str, Any]],
    derived_datasets_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    shadow_dir = derived_datasets_dir / "source_policy_applied"
    shadow_dir.mkdir(parents=True, exist_ok=True)
    generated_files: list[str] = []
    applied_rows = 0
    validation_failed_rows = 0
    considered_rows = 0
    updated_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for row in source_rows:
        next_row = dict(row)
        if str(next_row.get("audit_status") or "") != "judged":
            updated_rows.append(next_row)
            continue
        considered_rows += 1
        source_file = str(next_row.get("source_file") or "")
        source_path = input_dir / source_file
        if not source_file or not source_path.exists():
            next_row["shadow_apply_status"] = "skipped_missing_source_file"
            updated_rows.append(next_row)
            summary_rows.append(
                {
                    "source_id": str(next_row.get("source_id") or ""),
                    "source_file": source_file,
                    "status": str(next_row["shadow_apply_status"]),
                }
            )
            continue
        text, _encoding = dataset_builder.read_text_auto(source_path)
        passed, validation_details, episodes = _validate_source_policy_shadow_apply(
            source_id=str(next_row.get("source_id") or ""),
            source_file=source_file,
            text=text,
            content_sha256=str(next_row.get("content_sha256") or ""),
            judged_row=next_row,
        )
        next_row["shadow_apply_validation"] = validation_details
        if not passed:
            validation_failed_rows += 1
            next_row["shadow_apply_status"] = "skipped_validation_failed"
            updated_rows.append(next_row)
            summary_rows.append(
                {
                    "source_id": str(next_row.get("source_id") or ""),
                    "source_file": source_file,
                    "status": str(next_row["shadow_apply_status"]),
                    "validation": validation_details,
                }
            )
            continue
        records = [
            dataset_builder.to_record(
                f"SOURCE-POLICY-APPLIED:{str(next_row.get('source_id') or '')}",
                episode,
                content=episode.content,
            )
            for episode in episodes
        ]
        out_path = shadow_dir / f"{str(next_row.get('source_id') or 'unknown')}.jsonl"
        _write_jsonl(out_path, records)
        generated_files.append(str(out_path))
        applied_rows += 1
        next_row["shadow_apply_status"] = "applied"
        next_row["shadow_apply_output_path"] = str(out_path)
        updated_rows.append(next_row)
        summary_rows.append(
            {
                "source_id": str(next_row.get("source_id") or ""),
                "source_file": source_file,
                "status": str(next_row["shadow_apply_status"]),
                "output_path": str(out_path),
                "validation": validation_details,
            }
        )
    summary_path = shadow_dir / "summary.json"
    generated_with_summary = [*generated_files, str(summary_path)]
    summary_payload = {
        "considered_rows": considered_rows,
        "applied_rows": applied_rows,
        "validation_failed_rows": validation_failed_rows,
        "generated_files": generated_with_summary,
        "sources": summary_rows,
    }
    _write_json(summary_path, summary_payload)
    return updated_rows, summary_payload, generated_with_summary


def _inject_quality_judgments(*, baseline_snapshot_dir: Path) -> list[dict[str, Any]]:
    settings = load_config()
    rows: list[dict[str, Any]] = []
    for dataset_name in (
        "DS-INJECT-C.jsonl",
        "DS-DIVERSE-INJECT-C.jsonl",
        "DS-INJECT-C-STRUCTURED.jsonl",
        "DS-DIVERSE-INJECT-C-STRUCTURED.jsonl",
    ):
        dataset_path = baseline_snapshot_dir / dataset_name
        if not dataset_path.exists():
            continue
        for item in _read_jsonl(dataset_path):
            content = str(item.get("content") or "")
            if "[INJECT]\n" not in content:
                rows.append(
                    {
                        "dataset": str(item.get("dataset") or ""),
                        "source_id": str(item.get("source_id") or ""),
                        "inject_case_id": str(item.get("inject_case_id") or ""),
                        "audit_status": "skipped_no_inject_marker",
                    }
                )
                continue
            original_excerpt, injected_statement = content.split("[INJECT]\n", 1)
            judged = judge_inject_quality(
                original_excerpt=original_excerpt.rstrip(),
                injected_statement=injected_statement.strip(),
                injected_kind=str(item.get("injected_kind") or ""),
                source_metadata={
                    "source_id": str(item.get("source_id") or ""),
                    "source_boundary_pattern": str(item.get("source_boundary_pattern") or ""),
                },
                settings=settings,
            )
            rows.append(
                {
                    "dataset": str(item.get("dataset") or ""),
                    "source_id": str(item.get("source_id") or ""),
                    "inject_case_id": str(item.get("inject_case_id") or ""),
                    "injected_kind": str(item.get("injected_kind") or ""),
                    "inject_target_scope": str(item.get("inject_target_scope") or ""),
                    "baseline_inject_quality_label": str(item.get("inject_quality_label") or ""),
                    "audit_status": "judged",
                    **judged,
                }
            )
    return rows


def _has_final_consonant(text: str) -> bool:
    if not text:
        return False
    last = text[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:
        return ((code - 0xAC00) % 28) != 0
    return False


def _topic_particle(subject: str) -> str:
    return "은" if _has_final_consonant(subject) else "는"


def _with_particle(subject: str, consonant_form: str, vowel_form: str) -> str:
    return subject + (consonant_form if _has_final_consonant(subject) else vowel_form)


def _extract_subject_alias(original_excerpt: str, fallback: str) -> str:
    text = str(original_excerpt or "")
    counts: Counter[str] = Counter()
    first_pos: dict[str, int] = {}
    for match in re.finditer(r"([가-힣A-Za-z]{2,12})(?:은|는|이|가|을|를|와|과)", text):
        token = str(match.group(1) or "").strip()
        if not token or token in _SUBJECT_STOPWORDS:
            continue
        counts[token] += 1
        first_pos.setdefault(token, int(match.start(1)))
    if counts:
        return min(counts, key=lambda item: (-counts[item], first_pos[item], item))
    fallback_text = str(fallback or "").strip()
    return fallback_text or "주인공"


def _typed_inject_statement(kind: str, subject_alias: str) -> str:
    subject = subject_alias or "주인공"
    topic_subject = _with_particle(subject, "은", "는")
    templates = {
        "age": f"{topic_subject} 50세였다.",
        "job": "직업: 9서클 마법사",
        "talent": "재능: 천재",
        "time": "날짜: 1999년 1월 1일",
        "affiliation": "소속: 황실 기사단",
        "relation": "관계: 원수",
        "death": f"{topic_subject} 이미 사망했다.",
        "place": "장소: 북부 성채",
    }
    return templates.get(kind, "")


def _typed_inject_usability(label: str) -> dict[str, bool]:
    normalized = str(label or "")
    if normalized == "clear_conflict":
        return {"usable_for_core": True, "usable_for_strict": True, "usable_for_layer3_audit": True}
    if normalized in {"ambiguous_subject", "no_conflict"}:
        return {"usable_for_core": False, "usable_for_strict": False, "usable_for_layer3_audit": True}
    return {"usable_for_core": False, "usable_for_strict": False, "usable_for_layer3_audit": False}


def _build_typed_inject_variants(
    *,
    baseline_snapshot_dir: Path,
    derived_datasets_dir: Path,
) -> tuple[list[str], dict[str, Any]]:
    settings = load_config()
    generated_files: list[str] = []
    sidecar_rows: list[dict[str, Any]] = []
    typed_summary: dict[str, Any] = {}
    for typed_dataset, source_files in _TYPED_VARIANT_DATASETS.items():
        typed_rows: list[dict[str, Any]] = []
        label_counts: Counter[str] = Counter()
        usability_counts: Counter[str] = Counter()
        skipped_reason_counts: Counter[str] = Counter()
        seen_case_ids: set[str] = set()
        clear_conflict_kinds: set[str] = set()

        def _append_typed_row(
            item: dict[str, Any],
            *,
            kind: str,
            original_excerpt: str,
            source_dataset_name: str,
            allowed_labels: set[str] | None = None,
        ) -> bool:
            inject_case_id = str(item.get("inject_case_id") or "")
            dedupe_key = inject_case_id or f"{str(item.get('source_id') or '')}:{str(item.get('episode_no') or '')}:{kind}"
            if dedupe_key in seen_case_ids:
                return False
            subject_alias = _extract_subject_alias(original_excerpt, str(item.get("inject_subject_text") or ""))
            typed_statement = _typed_inject_statement(kind, subject_alias)
            judged = judge_inject_quality(
                original_excerpt=original_excerpt,
                injected_statement=typed_statement,
                injected_kind=kind,
                source_metadata={
                    "source_id": str(item.get("source_id") or ""),
                    "source_boundary_pattern": str(item.get("source_boundary_pattern") or ""),
                    "typed_variant": True,
                    "typed_subject_alias": subject_alias,
                },
                settings=settings,
            )
            label = str(judged.get("inject_quality_label") or "")
            if judged.get("typed_original_value") is None:
                skipped_reason_counts[str(judged.get("judge_reason") or "missing_original_slot")] += 1
                return False
            if allowed_labels is not None and label not in allowed_labels:
                return False
            seen_case_ids.add(dedupe_key)
            typed_content = original_excerpt + "\n\n[INJECT]\n" + typed_statement + "\n"
            typed_row = dict(item)
            typed_row["dataset"] = typed_dataset
            typed_row["content"] = typed_content
            typed_row["inject_case_id"] = inject_case_id or f"TYPED-{str(item.get('source_id') or '')}-{str(item.get('episode_no') or '')}-{kind}"
            typed_row["injected_kind"] = kind
            typed_row["inject_strategy"] = "typed_subject_alias_template"
            typed_row["inject_subject_text"] = subject_alias
            typed_row["inject_quality_label"] = None
            typed_row["inject_judge_confidence"] = None
            typed_row["inject_judge_backend"] = None
            typed_row["judge_requested_backend"] = ""
            typed_row["judge_effective_backend"] = ""
            typed_row["judge_model_id"] = ""
            typed_row["judge_prompt_version"] = ""
            typed_row["judge_fallback_used"] = None
            typed_row["judge_input_hash"] = ""
            typed_rows.append(typed_row)

            if label == "clear_conflict":
                clear_conflict_kinds.add(kind)
            label_counts[label] += 1
            usability = _typed_inject_usability(label)
            for key, enabled in usability.items():
                if enabled:
                    usability_counts[key] += 1
            sidecar_rows.append(
                {
                    "dataset": typed_dataset,
                    "source_dataset": source_dataset_name,
                    "source_id": str(item.get("source_id") or ""),
                    "inject_case_id": str(typed_row.get("inject_case_id") or ""),
                    "injected_kind": kind,
                    "typed_subject_alias": subject_alias,
                    "typed_statement": typed_statement,
                    "inject_quality_label": label,
                    "judge_confidence": float(judged.get("judge_confidence") or 0.0),
                    "judge_reason": str(judged.get("judge_reason") or ""),
                    "judge_requested_backend": str(judged.get("judge_requested_backend") or ""),
                    "judge_effective_backend": str(judged.get("judge_effective_backend") or ""),
                    "judge_prompt_version": str(judged.get("judge_prompt_version") or ""),
                    "typed_slot_key": str(judged.get("typed_slot_key") or ""),
                    "typed_original_value": judged.get("typed_original_value"),
                    "typed_injected_value": judged.get("typed_injected_value"),
                        **usability,
                    }
                )
            return True

        for source_file in source_files:
            dataset_path = baseline_snapshot_dir / source_file
            if not dataset_path.exists():
                continue
            for item in _read_jsonl(dataset_path):
                kind = str(item.get("injected_kind") or "")
                content = str(item.get("content") or "")
                if not kind or "[INJECT]\n" not in content:
                    continue
                original_excerpt, _ = content.split("[INJECT]\n", 1)
                _append_typed_row(
                    item,
                    kind=kind,
                    original_excerpt=original_excerpt.rstrip(),
                    source_dataset_name=str(item.get("dataset") or ""),
                )

        fallback_source_files = _TYPED_VARIANT_FALLBACK_BASESETS.get(typed_dataset, ())
        for source_file in fallback_source_files:
            if len(clear_conflict_kinds) >= len(_TYPED_INJECT_KINDS):
                break
            dataset_path = baseline_snapshot_dir / source_file
            if not dataset_path.exists():
                continue
            for item in _read_jsonl(dataset_path):
                original_excerpt = str(item.get("content") or "").rstrip()
                if not original_excerpt:
                    continue
                for kind in _TYPED_INJECT_KINDS:
                    if kind in clear_conflict_kinds:
                        continue
                    kept = _append_typed_row(
                        item,
                        kind=kind,
                        original_excerpt=original_excerpt,
                        source_dataset_name=str(item.get("dataset") or source_file.replace(".jsonl", "")),
                        allowed_labels={"clear_conflict"},
                    )
                    if kept:
                        break
        out_path = derived_datasets_dir / f"{typed_dataset}.jsonl"
        _write_jsonl(out_path, typed_rows)
        generated_files.append(str(out_path))
        typed_summary[typed_dataset] = {
            "rows_total": len(typed_rows),
            "label_counts": dict(label_counts),
            "usable_counts": dict(usability_counts),
            "skipped_reason_counts": dict(skipped_reason_counts),
        }
    sidecar_path = derived_datasets_dir / "typed_inject_usability.jsonl"
    _write_jsonl(sidecar_path, sidecar_rows)
    generated_files.append(str(sidecar_path))
    typed_summary["typed_inject_usability"] = {"rows_total": len(sidecar_rows)}
    return generated_files, typed_summary


def _strict_signal_summary(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = payload.get("consistency_runtime") or {}
    if not isinstance(runtime, dict):
        runtime = {}
    unknown_reason_counts = runtime.get("unknown_reason_counts") or {}
    if not isinstance(unknown_reason_counts, dict):
        unknown_reason_counts = {}
    vid_total = int(runtime.get("vid_count_total") or 0)
    unknown_total = int(runtime.get("unknown_count_total") or 0)
    violate_total = int(runtime.get("violate_count_total") or 0)
    conflict_unknown = int(unknown_reason_counts.get("CONFLICTING_EVIDENCE") or 0)
    signal_total = conflict_unknown + violate_total
    return {
        "vid_total": vid_total,
        "unknown_total": unknown_total,
        "violate_total": violate_total,
        "conflicting_unknown_total": conflict_unknown,
        "signal_total": signal_total,
        "signal_rate": float(signal_total) / float(max(1, vid_total)),
        "unknown_rate": float(unknown_total) / float(max(1, vid_total)),
        "violate_rate": float(violate_total) / float(max(1, vid_total)),
        "layer3_model_enabled_jobs": int(runtime.get("layer3_model_enabled_jobs") or 0),
        "layer3_effective_capable_jobs": int(runtime.get("layer3_effective_capable_jobs") or 0),
        "layer3_promoted_ok_count": int(runtime.get("layer3_promoted_ok_count") or 0),
    }


def _confidence_band(rows: list[dict[str, Any]]) -> dict[str, float]:
    values = sorted(float(row.get("judge_confidence") or 0.0) for row in rows)
    if not values:
        return {"min": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0}
    p90_index = min(len(values) - 1, max(0, int(round((len(values) - 1) * 0.9))))
    return {
        "min": float(values[0]),
        "median": float(median(values)),
        "p90": float(values[p90_index]),
        "max": float(values[-1]),
    }


def _build_strict_layer3_audit(
    *,
    comparison_dir: Path,
    typed_usability_path: Path,
    baseline_artifact: Path | None,
    control_artifact: Path | None,
    inject_artifact: Path | None,
) -> tuple[dict[str, Any], str]:
    typed_rows = _read_jsonl(typed_usability_path) if typed_usability_path.exists() else []
    disagreement_rows = [
        row
        for row in typed_rows
        if str(row.get("inject_quality_label") or "") not in {"clear_conflict", "no_conflict"}
    ]
    clear_conflict_rows = [
        row for row in typed_rows if str(row.get("inject_quality_label") or "") == "clear_conflict"
    ]
    no_conflict_rows = [
        row for row in typed_rows if str(row.get("inject_quality_label") or "") == "no_conflict"
    ]
    usable_for_strict_rows = [row for row in typed_rows if bool(row.get("usable_for_strict"))]
    usable_for_layer3_rows = [row for row in typed_rows if bool(row.get("usable_for_layer3_audit"))]
    disagreement_samples = [
        {
            "dataset": str(row.get("dataset") or ""),
            "source_id": str(row.get("source_id") or ""),
            "inject_case_id": str(row.get("inject_case_id") or ""),
            "injected_kind": str(row.get("injected_kind") or ""),
            "inject_quality_label": str(row.get("inject_quality_label") or ""),
            "judge_confidence": float(row.get("judge_confidence") or 0.0),
            "judge_reason": str(row.get("judge_reason") or ""),
            "typed_slot_key": str(row.get("typed_slot_key") or ""),
            "typed_original_value": row.get("typed_original_value"),
            "typed_injected_value": row.get("typed_injected_value"),
            "usable_for_strict": bool(row.get("usable_for_strict")),
            "usable_for_layer3_audit": bool(row.get("usable_for_layer3_audit")),
        }
        for row in disagreement_rows[:8]
    ]
    typed_summary = {
        "rows_total": len(typed_rows),
        "clear_conflict_rows": len(clear_conflict_rows),
        "no_conflict_rows": len(no_conflict_rows),
        "disagreement_rows": len(disagreement_rows),
        "usable_for_strict_rows": len(usable_for_strict_rows),
        "usable_for_layer3_audit_rows": len(usable_for_layer3_rows),
        "confidence_band": _confidence_band(typed_rows),
        "disagreement_samples": disagreement_samples,
    }

    provided = [item for item in (baseline_artifact, control_artifact, inject_artifact) if item is not None]
    if provided and len(provided) != 3:
        raise SystemExit("strict layer3 audit requires baseline/control/inject artifacts together")

    if len(provided) != 3:
        payload = {
            "status": "no_strict_artifacts",
            "typed_inject_disagreement": typed_summary,
        }
        return payload, "strict artifacts not provided"

    baseline_payload = _read_json(baseline_artifact)
    control_payload = _read_json(control_artifact)
    inject_payload = _read_json(inject_artifact)
    strict_gate = evaluate_strict_gate(
        baseline_payload=baseline_payload,
        control_payload=control_payload,
        inject_payload=inject_payload,
    )
    control_summary = _strict_signal_summary(control_payload)
    inject_summary = _strict_signal_summary(inject_payload)
    drift = {
        "control_signal_rate": control_summary["signal_rate"],
        "inject_signal_rate": inject_summary["signal_rate"],
        "signal_rate_gap": inject_summary["signal_rate"] - control_summary["signal_rate"],
        "control_unknown_rate": control_summary["unknown_rate"],
        "inject_unknown_rate": inject_summary["unknown_rate"],
        "control_violate_rate": control_summary["violate_rate"],
        "inject_violate_rate": inject_summary["violate_rate"],
    }
    payload = {
        "status": "evaluated",
        "artifacts": {
            "baseline_artifact": str(baseline_artifact),
            "control_artifact": str(control_artifact),
            "inject_artifact": str(inject_artifact),
        },
        "strict_core_gate": strict_gate.get("strict_core_gate") or {},
        "strict_layer3_gate": strict_gate.get("strict_layer3_gate") or {},
        "control_signal_summary": control_summary,
        "inject_signal_summary": inject_summary,
        "false_positive_drift": drift,
        "typed_inject_disagreement": typed_summary,
    }
    summary_path = comparison_dir / "strict_layer3_audit_summary.json"
    return payload, str(summary_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run developer-only judged dataset audit pipeline.")
    parser.add_argument("--developer-mode", action="store_true", help="Required safety flag for this pipeline.")
    parser.add_argument("--input-dir", default="test_files")
    parser.add_argument("--output-root", default="verify/judge_runs")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--baseline-snapshot-dir", default="")
    parser.add_argument("--inject-sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--diversity-profile", choices=("basic", "max"), default="max")
    parser.add_argument("--strict-baseline-artifact", default="")
    parser.add_argument("--strict-control-artifact", default="")
    parser.add_argument("--strict-inject-artifact", default="")
    parser.add_argument("--strict-artifact-dir", default="")
    parser.add_argument(
        "--judge-backend",
        choices=("config", "disabled", "local_nli", "remote_api"),
        default="config",
        help="Developer-only override for judge backend selection.",
    )
    parser.add_argument(
        "--judge-local-model-id",
        default="",
        help="Optional developer-only override for NF_TEST_JUDGE_LOCAL_NLI_MODEL_ID.",
    )
    parser.add_argument(
        "--require-real-judge-backend",
        action="store_true",
        help="Fail fast unless the effective developer-only judge backend is backed by a real local model or remote API credentials.",
    )
    args = parser.parse_args()

    _guard_developer_mode(bool(args.developer_mode))
    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        raise SystemExit(f"missing input dir: {input_dir}")

    output_root = Path(args.output_root)
    _guard_output_root(output_root)
    judge_backend_overrides = _apply_judge_backend_overrides(
        judge_backend=str(args.judge_backend),
        judge_local_model_id=str(args.judge_local_model_id),
    )
    backend_availability = _judge_backend_availability()
    _guard_real_judge_backend_required(
        required=bool(args.require_real_judge_backend),
        availability=backend_availability,
    )
    run_id = args.run_id.strip() or now_ts().replace(":", "").replace("-", "")
    run_root = output_root / run_id
    baseline_snapshot_dir = run_root / "baseline_snapshot"
    derived_datasets_dir = run_root / "derived_datasets"
    comparison_dir = run_root / "comparison"
    run_root.mkdir(parents=True, exist_ok=True)
    derived_datasets_dir.mkdir(parents=True, exist_ok=True)
    comparison_dir.mkdir(parents=True, exist_ok=True)

    if args.baseline_snapshot_dir.strip():
        _copy_baseline_snapshot(Path(args.baseline_snapshot_dir), baseline_snapshot_dir)
        baseline_build = {"copied_from": str(args.baseline_snapshot_dir)}
    else:
        baseline_build = _build_baseline_snapshot(
            input_dir=input_dir,
            baseline_snapshot_dir=baseline_snapshot_dir,
            inject_sample_size=int(args.inject_sample_size),
            seed=int(args.seed),
            diversity_profile=str(args.diversity_profile),
        )

    source_rows = _source_policy_judgments(input_dir=input_dir)
    source_rows, source_policy_shadow_summary, source_policy_generated_files = _build_source_policy_shadow_apply(
        input_dir=input_dir,
        source_rows=source_rows,
        derived_datasets_dir=derived_datasets_dir,
    )
    inject_rows = _inject_quality_judgments(baseline_snapshot_dir=baseline_snapshot_dir)
    generated_files, typed_summary = _build_typed_inject_variants(
        baseline_snapshot_dir=baseline_snapshot_dir,
        derived_datasets_dir=derived_datasets_dir,
    )
    resolved_strict_baseline, resolved_strict_control, resolved_strict_inject, strict_artifact_resolution = _resolve_strict_artifacts(
        baseline_artifact=Path(args.strict_baseline_artifact) if args.strict_baseline_artifact.strip() else None,
        control_artifact=Path(args.strict_control_artifact) if args.strict_control_artifact.strip() else None,
        inject_artifact=Path(args.strict_inject_artifact) if args.strict_inject_artifact.strip() else None,
        strict_artifact_dir=Path(args.strict_artifact_dir) if args.strict_artifact_dir.strip() else None,
    )
    strict_audit_summary, strict_audit_summary_path = _build_strict_layer3_audit(
        comparison_dir=comparison_dir,
        typed_usability_path=derived_datasets_dir / "typed_inject_usability.jsonl",
        baseline_artifact=resolved_strict_baseline,
        control_artifact=resolved_strict_control,
        inject_artifact=resolved_strict_inject,
    )
    strict_audit_summary["artifact_resolution"] = strict_artifact_resolution
    if strict_audit_summary.get("status") == "evaluated":
        _write_json(comparison_dir / "strict_layer3_audit_summary.json", strict_audit_summary)

    source_path = run_root / "source_policy_judgments.jsonl"
    inject_path = run_root / "inject_quality_judgments.jsonl"
    _write_jsonl(source_path, source_rows)
    _write_jsonl(inject_path, inject_rows)

    dataset_diff_summary = _compare_snapshot_with_canonical(baseline_snapshot_dir, Path("verify/datasets").resolve())
    dataset_diff_path = comparison_dir / "dataset_diff_summary.json"
    _write_json(dataset_diff_path, dataset_diff_summary)

    bench_candidate_summary = {
        "source_policy": _summarize_source_policy_rows(source_rows),
        "source_policy_shadow_apply": source_policy_shadow_summary,
        "inject_quality": _summarize_inject_rows(inject_rows),
        "typed_inject": typed_summary,
        "strict_layer3_audit": strict_audit_summary,
        "derived_datasets": {"generated_files": [*source_policy_generated_files, *generated_files]},
    }
    bench_candidate_path = comparison_dir / "bench_candidate_summary.json"
    _write_json(bench_candidate_path, bench_candidate_summary)
    manifest = build_run_manifest(
        dataset_hash=hash_file(baseline_snapshot_dir / "dataset_manifest.json"),
        extra={
            "run_id": run_id,
            "created_at": now_ts(),
            "developer_mode": True,
            "input_dir": str(input_dir),
            "output_root": str(run_root),
            "baseline_snapshot_path": str(baseline_snapshot_dir),
            "canonical_outputs_modified": False,
            "baseline_build": baseline_build,
            "source_policy_judgments_path": str(source_path),
            "inject_quality_judgments_path": str(inject_path),
            "dataset_diff_summary_path": str(dataset_diff_path),
            "bench_candidate_summary_path": str(bench_candidate_path),
            "strict_layer3_audit_summary_path": strict_audit_summary_path,
            "strict_artifact_resolution": strict_artifact_resolution,
            "judge_backend_overrides": judge_backend_overrides,
            "judge_backend_availability": backend_availability,
        },
    )
    manifest_path = run_root / "judge_run_manifest.json"
    _write_json(manifest_path, manifest)

    report_text = render_dev_judge_report(
        manifest=manifest,
        source_policy_summary=bench_candidate_summary["source_policy"],
        source_policy_shadow_summary=bench_candidate_summary["source_policy_shadow_apply"],
        inject_quality_summary=bench_candidate_summary["inject_quality"],
        strict_layer3_audit_summary=bench_candidate_summary["strict_layer3_audit"],
        dataset_diff_summary=dataset_diff_summary,
        judge_backend_availability=backend_availability,
    )
    report_path = run_root / "report.md"
    report_path.write_text(report_text, encoding="utf-8")

    print(json.dumps({"ok": True, "run_root": str(run_root), "manifest_path": str(manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
