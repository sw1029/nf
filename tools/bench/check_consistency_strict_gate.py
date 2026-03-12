from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"artifact not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"artifact is not JSON object: {path}")
    return payload


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _status_success(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    status = payload.get("status") or {}
    if not isinstance(status, dict):
        return False, ["status missing or invalid"]
    if str(status.get("index_fts") or "") != "SUCCEEDED":
        errors.append("index_fts not SUCCEEDED")
    if str(status.get("index_vec") or "") != "SUCCEEDED":
        errors.append("index_vec not SUCCEEDED")
    for key in ("ingest_failures", "consistency_failures", "retrieve_vec_failures"):
        if _as_int(status.get(key), 0) != 0:
            errors.append(f"{key} != 0")
    return len(errors) == 0, errors


def _required_runtime_keys_present(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    runtime = payload.get("consistency_runtime") or {}
    if not isinstance(runtime, dict):
        return False, ["consistency_runtime missing or invalid"]
    required_keys = (
        "unknown_reason_counts",
        "verification_loop_trigger_count",
        "verification_loop_rounds_total",
        "verification_loop_timeout_count",
        "verification_loop_stagnation_break_count",
        "self_evidence_filtered_count",
        "vid_count_total",
        "violate_count_total",
        "unknown_count_total",
    )
    missing = [key for key in required_keys if key not in runtime]
    return len(missing) == 0, [f"missing_runtime_key:{key}" for key in missing]


def _strict_level(payload: dict[str, Any]) -> str:
    parallel = payload.get("parallel") or {}
    if not isinstance(parallel, dict):
        return ""
    return str(parallel.get("consistency_level") or "").strip().lower()


def _timings(payload: dict[str, Any]) -> tuple[float, float]:
    timings = payload.get("timings_ms") or {}
    if not isinstance(timings, dict):
        return 0.0, 0.0
    return _as_float(timings.get("consistency_p95"), 0.0), _as_float(timings.get("retrieval_fts_p95"), 0.0)


def _runtime_dict(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = payload.get("consistency_runtime") or {}
    return runtime if isinstance(runtime, dict) else {}


def _has_layer3_signal(runtime: dict[str, Any]) -> bool:
    signal_keys = (
        "layer3_model_enabled_jobs",
        "layer3_local_nli_enabled_jobs",
        "layer3_remote_api_enabled_jobs",
        "layer3_local_reranker_enabled_jobs",
        "layer3_nli_capable_jobs",
        "layer3_reranker_capable_jobs",
        "layer3_effective_capable_jobs",
        "layer3_rerank_applied_count",
        "layer3_promoted_ok_count",
    )
    return any(_as_int(runtime.get(key), 0) > 0 for key in signal_keys)


def _layer3_enabled_sources(runtime: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    if _as_int(runtime.get("layer3_local_nli_enabled_jobs"), 0) > 0:
        sources.append("local_nli")
    if _as_int(runtime.get("layer3_remote_api_enabled_jobs"), 0) > 0:
        sources.append("remote_api")
    if _as_int(runtime.get("layer3_local_reranker_enabled_jobs"), 0) > 0:
        sources.append("local_reranker")
    return sources


def _layer3_source_label(sources: list[str]) -> str:
    return "+".join(sources) if sources else "none"


def _layer3_run_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    jobs_sampled = max(0, _as_int(runtime.get("jobs_sampled"), 0))
    enabled_sources = _layer3_enabled_sources(runtime)
    effective_capable_jobs = _as_int(runtime.get("layer3_effective_capable_jobs"), 0)
    rerank_applied_count = _as_int(runtime.get("layer3_rerank_applied_count"), 0)
    promoted_ok_count = _as_int(runtime.get("layer3_promoted_ok_count"), 0)
    fallback_count = _as_int(runtime.get("layer3_model_fallback_count"), 0)
    model_enabled_jobs = _as_int(runtime.get("layer3_model_enabled_jobs"), 0)
    any_source_enabled = bool(enabled_sources)
    layer3_mode = "on" if model_enabled_jobs > 0 or any_source_enabled else "off"
    effective_state = "active" if effective_capable_jobs > 0 or rerank_applied_count > 0 or promoted_ok_count > 0 else "inactive"
    if layer3_mode == "off":
        effective_state = "off"
    return {
        "jobs_sampled": jobs_sampled,
        "mode": layer3_mode,
        "effective_state": effective_state,
        "active_capability_sources": enabled_sources,
        "active_capability_source": _layer3_source_label(enabled_sources),
        "model_enabled_jobs": model_enabled_jobs,
        "model_enabled_ratio": _as_float(runtime.get("layer3_model_enabled_ratio"), 0.0),
        "local_nli_enabled_jobs": _as_int(runtime.get("layer3_local_nli_enabled_jobs"), 0),
        "local_nli_enabled_ratio": _as_float(runtime.get("layer3_local_nli_enabled_ratio"), 0.0),
        "remote_api_enabled_jobs": _as_int(runtime.get("layer3_remote_api_enabled_jobs"), 0),
        "remote_api_enabled_ratio": _as_float(runtime.get("layer3_remote_api_enabled_ratio"), 0.0),
        "local_reranker_enabled_jobs": _as_int(runtime.get("layer3_local_reranker_enabled_jobs"), 0),
        "local_reranker_enabled_ratio": _as_float(runtime.get("layer3_local_reranker_enabled_ratio"), 0.0),
        "nli_capable_jobs": _as_int(runtime.get("layer3_nli_capable_jobs"), 0),
        "nli_capable_ratio": _as_float(runtime.get("layer3_nli_capable_ratio"), 0.0),
        "reranker_capable_jobs": _as_int(runtime.get("layer3_reranker_capable_jobs"), 0),
        "reranker_capable_ratio": _as_float(runtime.get("layer3_reranker_capable_ratio"), 0.0),
        "effective_capable_jobs": effective_capable_jobs,
        "effective_capable_ratio": _as_float(runtime.get("layer3_effective_capable_ratio"), 0.0),
        "promotion_enabled_jobs": _as_int(runtime.get("layer3_promotion_enabled_jobs"), 0),
        "promotion_enabled_ratio": _as_float(runtime.get("layer3_promotion_enabled_ratio"), 0.0),
        "rerank_applied_count": rerank_applied_count,
        "promoted_ok_count": promoted_ok_count,
        "model_fallback_count": fallback_count,
        "inactive_reason_counts": dict(runtime.get("layer3_inactive_reason_counts") or {}),
    }


def _build_layer3_summary(control_runtime: dict[str, Any], inject_runtime: dict[str, Any]) -> dict[str, Any]:
    control_summary = _layer3_run_summary(control_runtime)
    inject_summary = _layer3_run_summary(inject_runtime)
    union_sources = sorted(
        set(control_summary.get("active_capability_sources") or []).union(
            set(inject_summary.get("active_capability_sources") or [])
        )
    )
    layer3_mode = "on" if control_summary.get("mode") == "on" or inject_summary.get("mode") == "on" else "off"
    effective_active = (
        _as_int(control_summary.get("effective_capable_jobs"), 0) > 0
        or _as_int(inject_summary.get("effective_capable_jobs"), 0) > 0
        or _as_int(control_summary.get("rerank_applied_count"), 0) > 0
        or _as_int(inject_summary.get("rerank_applied_count"), 0) > 0
        or _as_int(control_summary.get("promoted_ok_count"), 0) > 0
        or _as_int(inject_summary.get("promoted_ok_count"), 0) > 0
    )
    if layer3_mode == "off":
        interpretation = (
            "strict_core_gate is the active strict meaning; strict_layer3_gate is skipped because layer3 capability is off"
        )
    elif effective_active:
        interpretation = (
            "strict_core_gate and strict_layer3_gate must be read separately; layer3 capability is active via the configured source path"
        )
    else:
        interpretation = (
            "layer3 source is configured but effective capability is absent; strict_layer3_gate should not be read as covered unless it passes"
        )
    return {
        "mode": layer3_mode,
        "active_capability_sources": union_sources,
        "active_capability_source": _layer3_source_label(union_sources),
        "effective_state": "active" if effective_active else ("off" if layer3_mode == "off" else "inactive"),
        "interpretation": interpretation,
        "control": control_summary,
        "inject": inject_summary,
    }


def evaluate_strict_gate(
    *,
    baseline_payload: dict[str, Any],
    control_payload: dict[str, Any],
    inject_payload: dict[str, Any],
) -> dict[str, Any]:
    core_checks: list[dict[str, Any]] = []

    baseline_ok, baseline_errors = _status_success(baseline_payload)
    control_ok, control_errors = _status_success(control_payload)
    inject_ok, inject_errors = _status_success(inject_payload)
    core_checks.append(
        {
            "name": "status_success_all",
            "passed": baseline_ok and control_ok and inject_ok,
            "details": {
                "baseline_errors": baseline_errors,
                "control_errors": control_errors,
                "inject_errors": inject_errors,
            },
        }
    )

    control_level = _strict_level(control_payload)
    inject_level = _strict_level(inject_payload)
    core_checks.append(
        {
            "name": "strict_level_set",
            "passed": control_level == "strict" and inject_level == "strict",
            "details": {
                "control_level": control_level,
                "inject_level": inject_level,
            },
        }
    )

    control_runtime_ok, control_runtime_missing = _required_runtime_keys_present(control_payload)
    inject_runtime_ok, inject_runtime_missing = _required_runtime_keys_present(inject_payload)
    core_checks.append(
        {
            "name": "required_runtime_keys_present",
            "passed": control_runtime_ok and inject_runtime_ok,
            "details": {
                "control_missing": control_runtime_missing,
                "inject_missing": inject_runtime_missing,
            },
        }
    )

    baseline_consistency, baseline_retrieval = _timings(baseline_payload)
    control_consistency, control_retrieval = _timings(control_payload)
    inject_consistency, inject_retrieval = _timings(inject_payload)
    consistency_limit = baseline_consistency * 1.8
    retrieval_limit = baseline_retrieval * 1.5
    core_checks.append(
        {
            "name": "strict_perf_ratio_within_limit",
            "passed": (
                baseline_consistency > 0.0
                and baseline_retrieval > 0.0
                and control_consistency <= consistency_limit
                and inject_consistency <= consistency_limit
                and control_retrieval <= retrieval_limit
                and inject_retrieval <= retrieval_limit
            ),
            "details": {
                "baseline_consistency_p95": baseline_consistency,
                "baseline_retrieval_fts_p95": baseline_retrieval,
                "consistency_limit": consistency_limit,
                "retrieval_limit": retrieval_limit,
                "control_consistency_p95": control_consistency,
                "inject_consistency_p95": inject_consistency,
                "control_retrieval_fts_p95": control_retrieval,
                "inject_retrieval_fts_p95": inject_retrieval,
            },
        }
    )

    control_runtime = _runtime_dict(control_payload)
    inject_runtime = _runtime_dict(inject_payload)
    layer3_summary = _build_layer3_summary(control_runtime, inject_runtime)
    control_rounds = max(1, _as_int(control_runtime.get("verification_loop_rounds_total"), 0))
    inject_rounds = max(1, _as_int(inject_runtime.get("verification_loop_rounds_total"), 0))
    control_timeout_rate = _as_int(control_runtime.get("verification_loop_timeout_count"), 0) / float(control_rounds)
    inject_timeout_rate = _as_int(inject_runtime.get("verification_loop_timeout_count"), 0) / float(inject_rounds)
    core_checks.append(
        {
            "name": "loop_timeout_rate_le_20pct",
            "passed": control_timeout_rate <= 0.20 and inject_timeout_rate <= 0.20,
            "details": {
                "control_timeout_rate": control_timeout_rate,
                "inject_timeout_rate": inject_timeout_rate,
            },
        }
    )

    inject_reason_counts = inject_runtime.get("unknown_reason_counts") or {}
    if not isinstance(inject_reason_counts, dict):
        inject_reason_counts = {}
    inject_conflicting = _as_int(inject_reason_counts.get("CONFLICTING_EVIDENCE"), 0)
    inject_violate_total = _as_int(inject_runtime.get("violate_count_total"), 0)
    core_checks.append(
        {
            "name": "inject_conflict_signal_present",
            "passed": inject_conflicting >= 1 or inject_violate_total >= 1,
            "details": {
                "inject_conflicting_evidence_unknown_count": inject_conflicting,
                "inject_violate_count_total": inject_violate_total,
            },
        }
    )

    layer3_applicable = _has_layer3_signal(control_runtime) or _has_layer3_signal(inject_runtime)
    layer3_checks: list[dict[str, Any]] = []
    if layer3_applicable:
        control_model_enabled = _as_int(control_runtime.get("layer3_model_enabled_jobs"), 0)
        inject_model_enabled = _as_int(inject_runtime.get("layer3_model_enabled_jobs"), 0)
        control_sources = _layer3_enabled_sources(control_runtime)
        inject_sources = _layer3_enabled_sources(inject_runtime)
        control_effective = _as_int(control_runtime.get("layer3_effective_capable_jobs"), 0)
        inject_effective = _as_int(inject_runtime.get("layer3_effective_capable_jobs"), 0)
        layer3_checks.append(
            {
                "name": "layer3_capability_source_present",
                "passed": bool(control_sources or inject_sources or control_model_enabled > 0 or inject_model_enabled > 0),
                "details": {
                    "control_layer3_model_enabled_jobs": control_model_enabled,
                    "inject_layer3_model_enabled_jobs": inject_model_enabled,
                    "control_active_capability_source": _layer3_source_label(control_sources),
                    "inject_active_capability_source": _layer3_source_label(inject_sources),
                },
            }
        )
        layer3_checks.append(
            {
                "name": "layer3_effective_capability_present",
                "passed": control_effective > 0 or inject_effective > 0,
                "details": {
                    "control_layer3_effective_capable_jobs": control_effective,
                    "inject_layer3_effective_capable_jobs": inject_effective,
                },
            }
        )
        layer3_passed = all(bool(item.get("passed")) for item in layer3_checks)
        layer3_status = "PASS" if layer3_passed else "FAIL"
        layer3_reason = "layer3_signal_present"
    else:
        layer3_passed = True
        layer3_status = "SKIPPED"
        layer3_reason = "layer3_capability_off"

    core_passed = all(bool(item.get("passed")) for item in core_checks)
    passed = core_passed and layer3_passed
    return {
        "generated_at_utc": _now_ts(),
        "passed": passed,
        "checks": core_checks,
        "layer3_summary": layer3_summary,
        "strict_core_gate": {
            "status": "PASS" if core_passed else "FAIL",
            "passed": core_passed,
            "meaning": "verification loop, triage, inject signal, and timeout-rate checks",
            "checks": core_checks,
        },
        "strict_layer3_gate": {
            "status": layer3_status,
            "reason": layer3_reason,
            "applicable": layer3_applicable,
            "passed": None if not layer3_applicable else layer3_passed,
            "meaning": "layer3 capability source, effective capability, rerank/promote/fallback path",
            "checks": layer3_checks,
        },
    }


def _render_markdown(result: dict[str, Any], *, baseline_path: Path, control_path: Path, inject_path: Path) -> str:
    core_gate = result.get("strict_core_gate") or {}
    layer3_gate = result.get("strict_layer3_gate") or {}
    layer3_summary = result.get("layer3_summary") or {}
    control_summary = layer3_summary.get("control") or {}
    inject_summary = layer3_summary.get("inject") or {}
    lines: list[str] = [
        "# Consistency Strict Gate",
        "",
        f"- generated_at_utc: `{result.get('generated_at_utc')}`",
        f"- baseline_artifact: `{baseline_path}`",
        f"- control_artifact: `{control_path}`",
        f"- inject_artifact: `{inject_path}`",
        f"- passed: `{bool(result.get('passed'))}`",
        f"- strict_core_gate_status: `{core_gate.get('status')}`",
        f"- strict_layer3_gate_status: `{layer3_gate.get('status')}`",
        f"- layer3_mode: `{layer3_summary.get('mode')}`",
        f"- active_capability_source: `{layer3_summary.get('active_capability_source')}`",
        f"- interpretation: `{layer3_summary.get('interpretation')}`",
        "",
        "## Strict Meaning",
        f"- strict_core_gate: `{core_gate.get('meaning')}`",
        f"- strict_layer3_gate: `{layer3_gate.get('meaning')}`",
        "",
        "## Core Checks",
    ]
    for check in core_gate.get("checks") or result.get("checks") or []:
        name = str(check.get("name") or "")
        passed = bool(check.get("passed"))
        details = check.get("details")
        lines.append(f"- {name}: `{'PASS' if passed else 'FAIL'}`")
        lines.append(f"  - details: `{details}`")
    lines.append("")
    lines.append("## Layer3 Summary")
    lines.append(f"- mode: `{layer3_summary.get('mode')}`")
    lines.append(f"- effective_state: `{layer3_summary.get('effective_state')}`")
    lines.append(f"- active_capability_source: `{layer3_summary.get('active_capability_source')}`")
    lines.append(f"- control_active_capability_source: `{control_summary.get('active_capability_source')}`")
    lines.append(f"- inject_active_capability_source: `{inject_summary.get('active_capability_source')}`")
    lines.append(f"- control_effective_capable_jobs: `{control_summary.get('effective_capable_jobs')}`")
    lines.append(f"- inject_effective_capable_jobs: `{inject_summary.get('effective_capable_jobs')}`")
    lines.append(f"- control_model_fallback_count: `{control_summary.get('model_fallback_count')}`")
    lines.append(f"- inject_model_fallback_count: `{inject_summary.get('model_fallback_count')}`")
    lines.append(f"- interpretation: `{layer3_summary.get('interpretation')}`")
    lines.append("")
    lines.append("## Layer3 Checks")
    lines.append(f"- status: `{layer3_gate.get('status')}`")
    lines.append(f"- reason: `{layer3_gate.get('reason')}`")
    for check in layer3_gate.get("checks") or []:
        name = str(check.get("name") or "")
        passed = bool(check.get("passed"))
        details = check.get("details")
        lines.append(f"- {name}: `{'PASS' if passed else 'FAIL'}`")
        lines.append(f"  - details: `{details}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard-fail strict consistency gate evaluator.")
    parser.add_argument("--baseline-artifact", type=Path, required=True)
    parser.add_argument("--control-artifact", type=Path, required=True)
    parser.add_argument("--inject-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline_payload = _read_json(args.baseline_artifact)
    control_payload = _read_json(args.control_artifact)
    inject_payload = _read_json(args.inject_artifact)
    result = evaluate_strict_gate(
        baseline_payload=baseline_payload,
        control_payload=control_payload,
        inject_payload=inject_payload,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = args.output.with_suffix(".md")
    md_path.write_text(
        _render_markdown(
            result,
            baseline_path=args.baseline_artifact,
            control_path=args.control_artifact,
            inject_path=args.inject_artifact,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": bool(result.get("passed")),
                "output": str(args.output),
                "summary": str(md_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(result.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
