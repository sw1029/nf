from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("check_stack_ready")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


@pytest.mark.unit
def test_probe_stack_ready_completes_job_roundtrip_and_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()
    calls: list[tuple[str, str]] = []

    class FakeClient:
        base_url = "http://127.0.0.1:8086"

        def get(self, path: str):
            calls.append(("get", path))
            assert path == "/health"
            return {"status": "ok"}

        def post(self, path: str, body):
            calls.append(("post", path))
            assert path == "/projects"
            assert body["settings"]["mode"] == "bench-ready-probe"
            return {"project": {"project_id": "project-1"}}

        def delete(self, path: str):
            calls.append(("delete", path))
            assert path.endswith("/project-1")
            return {"deleted": True}

    monkeypatch.setattr(
        mod,
        "submit_and_wait",
        lambda client, **kwargs: SimpleNamespace(job_id="job-1", status="SUCCEEDED", elapsed_ms=12.5),
    )

    result = mod.probe_stack_ready(FakeClient(), probe_label="probe", timeout_sec=5.0)

    assert bool(result["ok"]) is True
    assert result["stage"] == "completed"
    assert result["project_id"] == "project-1"
    assert result["job_id"] == "job-1"
    assert ("get", "/health") in calls
    assert ("post", "/projects") in calls
    assert ("delete", "/projects/project-1") in calls
