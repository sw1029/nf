from __future__ import annotations

from contextlib import contextmanager

import pytest

from modules.nf_retrieval import router


@pytest.mark.unit
def test_run_retrieval_job_defaults_to_fts(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = [{"mode": "fts"}]
    called: dict[str, object] = {}

    @contextmanager
    def dummy_connect(_db_path=None):  # noqa: ANN001
        yield object()

    def fake_fts(_conn, req):  # noqa: ANN001
        called["fts"] = req
        return sentinel

    def fail_vector(_req):  # noqa: ANN001
        raise AssertionError("vector_search should not be called for default mode")

    monkeypatch.setattr(router.db, "connect", dummy_connect)
    monkeypatch.setattr(router, "fts_search", fake_fts)
    monkeypatch.setattr(router, "vector_search", fail_vector)

    result = router.run_retrieval_job("project-1", "hello")

    assert result == sentinel
    assert "fts" in called


@pytest.mark.unit
def test_run_retrieval_job_uses_vector_when_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = [{"mode": "vector"}]
    called: dict[str, object] = {}

    def fail_connect(_db_path=None):  # noqa: ANN001
        raise AssertionError("db.connect should not be called for vector mode")

    def fail_fts(_conn, _req):  # noqa: ANN001
        raise AssertionError("fts_search should not be called for vector mode")

    def fake_vector(req):  # noqa: ANN001
        called["vector"] = req
        return sentinel

    monkeypatch.setattr(router.db, "connect", fail_connect)
    monkeypatch.setattr(router, "fts_search", fail_fts)
    monkeypatch.setattr(router, "vector_search", fake_vector)

    result = router.run_retrieval_job("project-1", "hello", mode="vector")

    assert result == sentinel
    assert "vector" in called

