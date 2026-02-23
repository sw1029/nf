from __future__ import annotations

import pytest

from modules.nf_model_gateway.local.reranker_model import rerank_results, rerank_snippets


@pytest.mark.unit
def test_rerank_snippets_scores_related_text_higher() -> None:
    query = "hero age 14"
    snippets = [
        "weather forecast and rain",
        "the hero was age 14 in this chapter",
    ]
    scores, fallback_used = rerank_snippets(query, snippets, enabled=False)
    assert len(scores) == 2
    assert scores[1] >= scores[0]
    assert fallback_used is False


@pytest.mark.unit
def test_rerank_results_reports_fallback_when_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("modules.nf_model_gateway.local.reranker_model.ensure_model", lambda _model_id: None)
    rows = [
        {"evidence": {"snippet_text": "alpha beta"}},
        {"evidence": {"snippet_text": "hero age 14"}},
    ]
    ranked, fallback_used = rerank_results("hero age 14", rows, enabled=True, model_id="missing-reranker")
    assert len(ranked) == 2
    assert fallback_used is True
    assert ranked[0][1] >= ranked[1][1]
