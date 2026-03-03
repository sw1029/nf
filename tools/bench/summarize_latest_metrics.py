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


def _dataset_summary(dataset_key: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: item["event_time"], reverse=True)
    latest = ordered[0] if ordered else None
    previous = ordered[1] if len(ordered) > 1 else None

    if latest is None:
        return {
            "dataset": dataset_key,
            "status": "MISSING",
            "latest_run_utc": None,
            "latest_file": None,
            "latest_metrics": {metric: None for metric in TARGET_METRICS},
            "previous_run_utc": None,
            "previous_file": None,
            "delta_pct": {metric: None for metric in TARGET_METRICS},
            "metric_status": {metric: "N/A" for metric in TARGET_METRICS},
            "improved_or_same_metric_count": 0,
        }

    latest_metrics = latest["metrics"]
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

    return {
        "dataset": dataset_key,
        "status": status,
        "latest_run_utc": latest["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_file": latest["path"].name,
        "latest_metrics": latest_metrics,
        "previous_run_utc": None if previous is None else previous["event_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous_file": None if previous is None else previous["path"].name,
        "delta_pct": delta_pct,
        "metric_status": metric_status,
        "improved_or_same_metric_count": improved_or_same,
    }


def summarize_benchmarks(bench_dir: Path, *, datasets: tuple[str, ...] = DEFAULT_DATASETS) -> dict[str, Any]:
    rows_by_dataset: dict[str, list[dict[str, Any]]] = {dataset: [] for dataset in datasets}
    for path in sorted(bench_dir.glob("*.json")):
        if path.name.startswith(("soak_", "graphrag_probe_", "latest_metrics_summary", "consistency_strict_gate")):
            continue
        payload = _read_json(path)
        if payload is None:
            continue
        if not isinstance(payload.get("timings_ms"), dict):
            continue
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

    return {
        "generated_at_utc": now_ts(),
        "bench_dir": str(bench_dir),
        "dataset_order": list(datasets),
        "datasets": dataset_summaries,
        "rule_evaluation": {
            "hard_fail": hard_fail,
            "soft_warning": soft_warning,
            "no_baseline": no_baseline,
            "all_datasets_have_improved_or_same_metric": all_have_improve_or_same,
        },
        "overall_status": overall_status,
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
        f"- overall_status: `{summary.get('overall_status')}`",
        "",
        "| dataset | latest_run_utc | consistency_p95(ms) | retrieval_fts_p95(ms) | delta_consistency | delta_retrieval_fts | status |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    datasets = summary.get("datasets") or {}
    dataset_order = summary.get("dataset_order") or list(DEFAULT_DATASETS)
    for dataset_key in dataset_order:
        row = datasets.get(dataset_key) or {}
        latest_metrics = row.get("latest_metrics") or {}
        delta_pct = row.get("delta_pct") or {}
        lines.append(
            "| {dataset} | {run} | {cons} | {retr} | {d_cons} | {d_retr} | {status} |".format(
                dataset=dataset_key,
                run=row.get("latest_run_utc") or "-",
                cons=_format_metric(_as_float(latest_metrics.get("consistency_p95"))),
                retr=_format_metric(_as_float(latest_metrics.get("retrieval_fts_p95"))),
                d_cons=_format_delta(_as_float(delta_pct.get("consistency_p95"))),
                d_retr=_format_delta(_as_float(delta_pct.get("retrieval_fts_p95"))),
                status=row.get("status") or "MISSING",
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize latest benchmark metrics by dataset.")
    parser.add_argument("--bench-dir", type=Path, default=Path("verify/benchmarks"))
    parser.add_argument("--output-json", type=Path, default=Path("verify/benchmarks/latest_metrics_summary.json"))
    parser.add_argument("--output-md", type=Path, default=Path("verify/benchmarks/latest_metrics_summary.md"))
    parser.add_argument("--datasets", type=str, default="")
    args = parser.parse_args()

    summary = summarize_benchmarks(args.bench_dir, datasets=_parse_dataset_arg(args.datasets))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"ok": True, "output_json": str(args.output_json), "output_md": str(args.output_md)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
