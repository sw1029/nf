from __future__ import annotations

import pytest

from modules.nf_model_gateway.gateway import select_model
from modules.nf_model_gateway.local.nli_model import infer_nli_distribution


@pytest.mark.unit
def test_consistency_gateway_blocks_suggestion_methods() -> None:
    gateway = select_model("consistency")
    with pytest.raises(RuntimeError):
        gateway.suggest_local_rule({"claim_text": "x", "evidence": [{"snippet_text": "x"}]})


@pytest.mark.unit
def test_consistency_gateway_nli_score_uses_overlap_signal() -> None:
    gateway = select_model("consistency")
    score_low = gateway.nli_score({"claim_text": "totally different sentence", "evidence": [{"snippet_text": "unrelated words"}]})
    score_high = gateway.nli_score({"claim_text": "shiro is 14 years old", "evidence": [{"snippet_text": "shiro was 14 years old"}]})
    assert 0.0 <= score_low <= 1.0
    assert 0.0 <= score_high <= 1.0
    assert score_high >= score_low


@pytest.mark.unit
def test_consistency_gateway_nli_distribution_reports_fallback_when_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("modules.nf_model_gateway.local.text_pair_classifier.ensure_model", lambda _model_id: None)
    scores = infer_nli_distribution("premise text", "hypothesis text", enabled=True, model_id="missing-model")
    assert set(scores.keys()) >= {"entail", "contradict", "neutral", "fallback_used"}
    assert scores["fallback_used"] is True


@pytest.mark.unit
def test_remote_gateway_blocks_local_gen_method() -> None:
    gateway = select_model("remote_api")
    with pytest.raises(RuntimeError):
        gateway.suggest_local_gen({"claim_text": "x", "evidence": [{"snippet_text": "x"}]})
