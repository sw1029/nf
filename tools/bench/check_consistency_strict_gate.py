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


def evaluate_strict_gate(
    *,
    baseline_payload: dict[str, Any],
    control_payload: dict[str, Any],
    inject_payload: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    baseline_ok, baseline_errors = _status_success(baseline_payload)
    control_ok, control_errors = _status_success(control_payload)
    inject_ok, inject_errors = _status_success(inject_payload)
    checks.append(
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
    checks.append(
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
    checks.append(
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
    checks.append(
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

    control_runtime = control_payload.get("consistency_runtime") or {}
    inject_runtime = inject_payload.get("consistency_runtime") or {}
    control_rounds = max(1, _as_int(control_runtime.get("verification_loop_rounds_total"), 0))
    inject_rounds = max(1, _as_int(inject_runtime.get("verification_loop_rounds_total"), 0))
    control_timeout_rate = _as_int(control_runtime.get("verification_loop_timeout_count"), 0) / float(control_rounds)
    inject_timeout_rate = _as_int(inject_runtime.get("verification_loop_timeout_count"), 0) / float(inject_rounds)
    checks.append(
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
    checks.append(
        {
            "name": "inject_conflict_signal_present",
            "passed": inject_conflicting >= 1 or inject_violate_total >= 1,
            "details": {
                "inject_conflicting_evidence_unknown_count": inject_conflicting,
                "inject_violate_count_total": inject_violate_total,
            },
        }
    )

    passed = all(bool(item.get("passed")) for item in checks)
    return {
        "generated_at_utc": _now_ts(),
        "passed": passed,
        "checks": checks,
    }


def _render_markdown(result: dict[str, Any], *, baseline_path: Path, control_path: Path, inject_path: Path) -> str:
    lines: list[str] = [
        "# Consistency Strict Gate",
        "",
        f"- generated_at_utc: `{result.get('generated_at_utc')}`",
        f"- baseline_artifact: `{baseline_path}`",
        f"- control_artifact: `{control_path}`",
        f"- inject_artifact: `{inject_path}`",
        f"- passed: `{bool(result.get('passed'))}`",
        "",
        "## Checks",
    ]
    for check in result.get("checks") or []:
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
