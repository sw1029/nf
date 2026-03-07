from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import now_ts

DEFAULT_DATASETS = ("DS-200", "DS-400", "DS-800")
TARGET_METRICS = ("consistency_p95", "retrieval_fts_p95")
_ABSOLUTE_CONSISTENCY_TARGET_MS = 2500.0
_LABEL_MODE_OPERATIONAL = "operational"
_LABEL_MODE_CUSTOM = "custom"
_LABEL_MODE_ALL = "all_artifacts"
_LABEL_FILTER_PRESETS: dict[str, dict[str, Any]] = {
    _LABEL_MODE_OPERATIONAL: {
        "prefixes": ("operational-main:", "operational-diversity-main:"),
        "strict_label_filter": True,
        "description": "Only operational mainline/diversity-main artifacts are eligible for trend baselines.",
    }
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _infer_dataset_key(payload: dict[str, Any]) -> str | None:
    dataset_path = str(payload.get("dataset_path") or "")
    if dataset_path:
        diverse_match = re.search(r"(?:DS[-_]?DIVERSE[-_]?)(\d+)", dataset_path, re.IGNORECASE)
        if diverse_match:
            count = int(diverse_match.group(1))
            if count in (200, 400, 800):
                return f"DS-DIVERSE-{count}"
            return None

        growth_match = re.search(r"(?:DS[-_]?GROWTH[-_]?)(\d+)", dataset_path, re.IGNORECASE)
        if growth_match:
            count = int(growth_match.group(1))
            if count in (200, 400, 800):
                return f"DS-{count}"
            return None
        return None

    try:
        doc_count = int(payload.get("doc_count"))
    except (TypeError, ValueError):
        return None
    if doc_count in (200, 400, 800):
        return f"DS-{doc_count}"
    return None


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_time(payload: dict[str, Any], path: Path) -> datetime:
    for key in ("finished_at", "started_at"):
        parsed = _parse_utc(payload.get(key))
        if parsed is not None:
            return parsed
    name_match = re.search(r"(\d{8}T\d{6}Z)", path.name)
    if name_match:
        return datetime.strptime(name_match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _metric_status(delta_pct: float | None) -> str:
    if delta_pct is None:
        return "N/A"
    if delta_pct > 20.0:
        return "HARD_FAIL"
    if delta_pct > 5.0:
        return "SOFT_WARNING"
    return "PASS"


def _absolute_thresholds(doc_count: int | None) -> dict[str, float]:
    normalized_doc_count = int(doc_count or 0)
    retrieval_fts_target = 300.0 if normalized_doc_count <= 200 else 450.0
    return {
        "consistency_p95": _ABSOLUTE_CONSISTENCY_TARGET_MS,
        "retrieval_fts_p95": retrieval_fts_target,
    }


def _absolute_metric_status(metric: str, value: float | None, *, doc_count: int | None) -> str:
    if value is None:
        return "N/A"
    threshold = _absolute_thresholds(doc_count).get(metric)
    if threshold is None:
        return "N/A"
    return "PASS" if value <= threshold else "FAIL"


def _absolute_dataset_status(metric_status: dict[str, str]) -> str:
    if not metric_status:
        return "WARN"
    values = list(metric_status.values())
    if any(value == "FAIL" for value in values):
        return "FAIL"
    if all(value == "PASS" for value in values):
        return "PASS"
    return "WARN"


def _parse_label_prefixes(text: str | None) -> tuple[str, ...]:
    if text is None or not text.strip():
        return ()
    out: list[str] = []
    for token in text.split(","):
        label = token.strip()
        if label and label not in out:
            out.append(label)
    return tuple(out)


def _label_matches(bench_label: str, label_prefixes: tuple[str, ...]) -> bool:
    if not label_prefixes:
        return True
    for prefix in label_prefixes:
        if bench_label.startswith(prefix):
            return True
    return False


def _artifact_execution_failed(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    if not isinstance(status, dict):
        return False
    index_fts = str(status.get("index_fts") or "").strip().upper()
    if index_fts and index_fts != "SUCCEEDED":
        return True
    index_vec = str(status.get("index_vec") or "").strip().upper()
    if index_vec and index_vec != "SUCCEEDED":
        return True
    for key in ("ingest_failures", "consistency_failures", "retrieve_vec_failures"):
        if key not in status:
            continue
        try:
            if int(status.get(key) or 0) != 0:
                return True
        except (TypeError, ValueError):
            return True
    return False


def _resolve_label_filter(
    *,
    label_mode: str | None,
    label_prefixes: tuple[str, ...],
    strict_label_filter: bool,
) -> dict[str, Any]:
    normalized_mode = str(label_mode or "").strip().lower()
    preset = _LABEL_FILTER_PRESETS.get(normalized_mode)
    resolved_prefixes = label_prefixes
    resolved_strict = bool(strict_label_filter)
    mode = _LABEL_MODE_CUSTOM if (resolved_prefixes or resolved_strict) else _LABEL_MODE_ALL
    note = "Includes all benchmark artifacts matching the dataset selection."
    if preset is not None:
        if not resolved_prefixes:
            resolved_prefixes = tuple(str(item) for item in preset.get("prefixes") or ())
        resolved_strict = bool(resolved_strict or preset.get("strict_label_filter", False))
        mode = normalized_mode
        note = str(preset.get("description") or note)
    elif mode == _LABEL_MODE_CUSTOM:
        note = "Uses caller-specified label prefixes and/or strict unlabeled exclusion."
    return {
        "mode": mode,
        "note": note,
        "prefixes": resolved_prefixes,
        "strict_label_filter": resolved_strict,
    }


def _dataset_summary(dataset_key: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: item["event_time"], reverse=True)
    latest = ordered[0] if ordered else None
    previous = ordered[1] if len(ordered) > 1 else None

    if latest is None:
        return {
            "dataset": dataset_key,
            "status": "MISSING",
            "absolute_status": "MISSING",
            "latest_run_utc": None,
            "latest_file": None,
            "latest_doc_count": None,
            "latest_metrics": {metric: None for metric in TARGET_METRICS},
            "previous_run_utc": None,
            "previous_file": None,
            "delta_pct": {metric: None for metric in TARGET_METRICS},
            "metric_status": {metric: "N/A" for metric in TARGET_METRICS},
            "absolute_metric_status": {metric: "N/A" for metric in TARGET_METRICS},
            "absolute_thresholds": {metric: None for metric in TARGET_METRICS},
            "improved_or_same_metric_count": 0,
        }

    latest_metrics = latest["metrics"]
    latest_doc_count = latest.get("doc_count")
    previous_metrics = previous["metrics"] if previous is not None else {}
    delta_pct: dict[str, float | None] = {}
    metric_status: dict[str, str] = {}
    improved_or_same = 0
    for metric in TARGET_METRICS:
        current = latest_metrics.get(metric)
        baseline = previous_metrics.get(metric)
        if current is None or baseline is None or baseline <= 0:
            delta = None
        else:
            delta = ((current - baseline) / baseline) * 100.0
        delta_pct[metric] = delta
        metric_status[metric] = _metric_status(delta)
        if delta is not None and delta <= 0.0:
            improved_or_same += 1

    status = "PASS"
    if any(state == "HARD_FAIL" for state in metric_status.values()):
        status = "FAIL"
    elif any(state == "SOFT_WARNING" for state in metric_status.values()):
        status = "WARN"
    elif previous is None:
        status = "NO_BASELINE"

    absolute_thresholds = _absolute_thresholds(latest_doc_count)
    absolute_metric_status = {
        metric: _absolute_metric_status(metric, latest_metrics.get(metric), doc_count=latest_doc_count)
        for metric in TARGET_METRICS
    }
    absolute_status = _absolute_dataset_status(absolute_metric_status)

    return {
        "dataset": dataset_key,
        "status": status,
        "absolute_status": absolute_status,
        "latest_run_utc": latest["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_file": latest["path"].name,
        "latest_bench_label": str(latest.get("bench_label") or ""),
        "latest_doc_count": latest_doc_count,
        "latest_metrics": latest_metrics,
        "previous_run_utc": None if previous is None else previous["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous_file": None if previous is None else previous["path"].name,
        "previous_bench_label": None if previous is None else str(previous.get("bench_label") or ""),
        "delta_pct": delta_pct,
        "metric_status": metric_status,
        "absolute_metric_status": absolute_metric_status,
        "absolute_thresholds": absolute_thresholds,
        "improved_or_same_metric_count": improved_or_same,
    }


def summarize_benchmarks(
    bench_dir: Path,
    *,
    datasets: tuple[str, ...] = DEFAULT_DATASETS,
    label_mode: str | None = None,
    label_prefixes: tuple[str, ...] = (),
    strict_label_filter: bool = False,
) -> dict[str, Any]:
    resolved_label_filter = _resolve_label_filter(
        label_mode=label_mode,
        label_prefixes=label_prefixes,
        strict_label_filter=strict_label_filter,
    )
    resolved_prefixes = tuple(str(item) for item in resolved_label_filter["prefixes"])
    resolved_strict = bool(resolved_label_filter["strict_label_filter"])
    rows_by_dataset: dict[str, list[dict[str, Any]]] = {dataset: [] for dataset in datasets}
    scanned_count = 0
    considered_count = 0
    excluded_unlabeled = 0
    excluded_prefix_mismatch = 0
    excluded_unsuccessful_status = 0
    for path in sorted(bench_dir.glob("*.json")):
        if path.name.startswith(("soak_", "graphrag_probe_", "latest_metrics_summary", "consistency_strict_gate")):
            continue
        payload = _read_json(path)
        if payload is None:
            continue
        scanned_count += 1
        if not isinstance(payload.get("timings_ms"), dict):
            continue
        bench_label = str(payload.get("bench_label") or "").strip()
        if resolved_strict and not bench_label:
            excluded_unlabeled += 1
            continue
        if not _label_matches(bench_label, resolved_prefixes):
            excluded_prefix_mismatch += 1
            continue
        if _artifact_execution_failed(payload):
            excluded_unsuccessful_status += 1
            continue
        considered_count += 1
        dataset_key = _infer_dataset_key(payload)
        if dataset_key not in rows_by_dataset:
            continue
        timings = payload.get("timings_ms") or {}
        metrics = {
            "consistency_p95": _as_float(timings.get("consistency_p95")),
            "retrieval_fts_p95": _as_float(timings.get("retrieval_fts_p95")),
        }
        rows_by_dataset[dataset_key].append(
            {
                "path": path,
                "payload": payload,
                "event_time": _event_time(payload, path),
                "metrics": metrics,
                "doc_count": int(payload.get("doc_count") or 0),
                "bench_label": bench_label,
            }
        )

    dataset_summaries = {
        dataset: _dataset_summary(dataset, rows_by_dataset.get(dataset, []))
        for dataset in datasets
    }

    hard_fail = any(summary["status"] == "FAIL" for summary in dataset_summaries.values())
    soft_warning = any(summary["status"] == "WARN" for summary in dataset_summaries.values())
    no_baseline = any(summary["status"] == "NO_BASELINE" for summary in dataset_summaries.values())

    all_have_improve_or_same = True
    for summary in dataset_summaries.values():
        if summary["status"] in {"MISSING", "NO_BASELINE"}:
            all_have_improve_or_same = False
            continue
        if int(summary.get("improved_or_same_metric_count", 0)) <= 0:
            all_have_improve_or_same = False

    overall_status = "PASS"
    if hard_fail:
        overall_status = "FAIL"
    elif soft_warning or no_baseline or not all_have_improve_or_same:
        overall_status = "WARN"

    absolute_fail = any(summary.get("absolute_status") == "FAIL" for summary in dataset_summaries.values())
    absolute_missing = any(summary.get("absolute_status") == "MISSING" for summary in dataset_summaries.values())
    absolute_warn = any(summary.get("absolute_status") == "WARN" for summary in dataset_summaries.values())
    absolute_goal_status = "PASS"
    if absolute_fail:
        absolute_goal_status = "FAIL"
    elif absolute_warn or absolute_missing:
        absolute_goal_status = "WARN"

    return {
        "generated_at_utc": now_ts(),
        "bench_dir": str(bench_dir),
        "dataset_order": list(datasets),
        "datasets": dataset_summaries,
        "status_semantics": {
            "overall_status": "trend_relative",
            "overall_status_note": "Compares latest artifact against the previous artifact for the same dataset selection.",
            "absolute_goal_status": "absolute_thresholds",
            "absolute_goal_status_note": "Informational absolute goal view only. Release gating still comes from final gate report artifacts.",
        },
        "label_filter": {
            "mode": str(resolved_label_filter["mode"]),
            "note": str(resolved_label_filter["note"]),
            "prefixes": list(resolved_prefixes),
            "strict_label_filter": bool(resolved_strict),
            "scanned_artifacts": scanned_count,
            "considered_artifacts": considered_count,
            "excluded_unlabeled": excluded_unlabeled,
            "excluded_prefix_mismatch": excluded_prefix_mismatch,
            "excluded_unsuccessful_status": excluded_unsuccessful_status,
        },
        "rule_evaluation": {
            "hard_fail": hard_fail,
            "soft_warning": soft_warning,
            "no_baseline": no_baseline,
            "all_datasets_have_improved_or_same_metric": all_have_improve_or_same,
        },
        "overall_status": overall_status,
        "absolute_goal_status": absolute_goal_status,
    }


def _format_metric(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _format_delta(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%"


def _parse_dataset_arg(text: str | None) -> tuple[str, ...]:
    if text is None or not text.strip():
        return DEFAULT_DATASETS
    out: list[str] = []
    for token in text.split(","):
        key = token.strip()
        if key and key not in out:
            out.append(key)
    return tuple(out) if out else DEFAULT_DATASETS


def render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Latest Metrics Summary",
        "",
        f"- generated_at_utc: `{summary.get('generated_at_utc')}`",
        f"- overall_status (trend_relative): `{summary.get('overall_status')}`",
        f"- absolute_goal_status: `{summary.get('absolute_goal_status')}`",
        f"- status_semantics: `{summary.get('status_semantics')}`",
        f"- label_filter: `{summary.get('label_filter')}`",
        "",
        "| dataset | latest_run_utc | consistency_p95(ms) | retrieval_fts_p95(ms) | delta_consistency | delta_retrieval_fts | trend_status | absolute_status |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    datasets = summary.get("datasets") or {}
    dataset_order = summary.get("dataset_order") or list(DEFAULT_DATASETS)
    for dataset_key in dataset_order:
        row = datasets.get(dataset_key) or {}
        latest_metrics = row.get("latest_metrics") or {}
        delta_pct = row.get("delta_pct") or {}
        lines.append(
            "| {dataset} | {run} | {cons} | {retr} | {d_cons} | {d_retr} | {trend_status} | {absolute_status} |".format(
                dataset=dataset_key,
                run=row.get("latest_run_utc") or "-",
                cons=_format_metric(_as_float(latest_metrics.get("consistency_p95"))),
                retr=_format_metric(_as_float(latest_metrics.get("retrieval_fts_p95"))),
                d_cons=_format_delta(_as_float(delta_pct.get("consistency_p95"))),
                d_retr=_format_delta(_as_float(delta_pct.get("retrieval_fts_p95"))),
                trend_status=row.get("status") or "MISSING",
                absolute_status=row.get("absolute_status") or "MISSING",
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize latest benchmark metrics by dataset.")
    parser.add_argument("--bench-dir", type=Path, default=Path("verify/benchmarks"))
    parser.add_argument("--output-json", type=Path, default=Path("verify/benchmarks/latest_metrics_summary.json"))
    parser.add_argument("--output-md", type=Path, default=Path("verify/benchmarks/latest_metrics_summary.md"))
    parser.add_argument("--datasets", type=str, default="")
    parser.add_argument("--label-mode", type=str, default="")
    parser.add_argument("--label-prefixes", type=str, default="")
    parser.add_argument("--strict-label-filter", action="store_true")
    args = parser.parse_args()

    summary = summarize_benchmarks(
        args.bench_dir,
        datasets=_parse_dataset_arg(args.datasets),
        label_mode=args.label_mode,
        label_prefixes=_parse_label_prefixes(args.label_prefixes),
        strict_label_filter=bool(args.strict_label_filter),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"ok": True, "output_json": str(args.output_json), "output_md": str(args.output_md)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
