from __future__ import annotations

import pytest

from modules.nf_orchestrator.main import _build_openapi_spec


@pytest.mark.unit
def test_openapi_includes_retry_and_segment_rules_paths() -> None:
    spec = _build_openapi_spec()
    paths = spec.get("paths") if isinstance(spec, dict) else {}
    assert isinstance(paths, dict)
    assert "/jobs/{job_id}/retry" in paths
    assert "/query/segment-rules" in paths
    retry_ops = paths["/jobs/{job_id}/retry"]
    seg_ops = paths["/query/segment-rules"]
    assert isinstance(retry_ops, dict) and "post" in retry_ops
    assert isinstance(seg_ops, dict) and "get" in seg_ops

