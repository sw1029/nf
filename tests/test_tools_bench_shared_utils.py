from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.mark.unit
def test_bench_scripts_import_with_shared_utils() -> None:
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        importlib.import_module("run_pipeline_bench")
        importlib.import_module("check_graphrag_applied")
        importlib.import_module("check_consistency_strict_gate")
        importlib.import_module("run_soak")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


@pytest.mark.unit
def test_sse_parser_handles_keepalive_and_events() -> None:
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        sse = importlib.import_module("sse")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))

    raw = """\
: keep-alive
id: 12
event: message
data: {\"foo\": 1}

id: 13
data: {\"bar\": 2}

"""
    events = sse.parse_sse_events(raw)
    assert events == [(12, {"foo": 1}), (13, {"bar": 2})]
