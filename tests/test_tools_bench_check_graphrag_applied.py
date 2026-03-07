from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("check_graphrag_applied")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


@pytest.mark.unit
def test_probe_summary_marks_normal_path_when_filters_exist_before_bootstrap() -> None:
    mod = _import_module()
    summary = mod._summarize_probe_context(
        initial_filters_count=2,
        final_filters_count=2,
        bootstrap=None,
        probe_count=1,
        applied_count=1,
        require_applied=True,
    )

    assert summary["validation_mode"] == "normal_path"
    assert summary["normal_path_ready"] is True
    assert summary["bootstrap_used"] is False
    assert summary["normal_path_filter_count"] == 2


@pytest.mark.unit
def test_probe_summary_marks_bootstrap_assisted_when_filters_only_appear_after_bootstrap() -> None:
    mod = _import_module()
    summary = mod._summarize_probe_context(
        initial_filters_count=0,
        final_filters_count=3,
        bootstrap={"status": "SUCCEEDED"},
        probe_count=1,
        applied_count=1,
        require_applied=True,
    )

    assert summary["validation_mode"] == "bootstrap_assisted"
    assert summary["normal_path_ready"] is False
    assert summary["bootstrap_used"] is True
    assert summary["bootstrap_succeeded"] is True


@pytest.mark.unit
def test_probe_summary_marks_no_grouping_when_bootstrap_does_not_produce_filters() -> None:
    mod = _import_module()
    summary = mod._summarize_probe_context(
        initial_filters_count=0,
        final_filters_count=0,
        bootstrap={"status": "SUCCEEDED"},
        probe_count=0,
        applied_count=0,
        require_applied=False,
    )

    assert summary["validation_mode"] == "no_grouping"
    assert summary["normal_path_ready"] is False
    assert summary["bootstrap_used"] is True
