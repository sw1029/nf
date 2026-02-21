from __future__ import annotations

import pytest

from modules.nf_model_gateway.gateway import select_model


@pytest.mark.unit
def test_consistency_gateway_blocks_suggestion_methods() -> None:
    gateway = select_model("consistency")
    with pytest.raises(RuntimeError):
        gateway.suggest_local_rule({"claim_text": "x", "evidence": [{"snippet_text": "x"}]})


@pytest.mark.unit
def test_consistency_gateway_nli_score_uses_overlap_signal() -> None:
    gateway = select_model("consistency")
    score_low = gateway.nli_score({"claim_text": "완전히 다른 문장", "evidence": [{"snippet_text": "무관한 단어"}]})
    score_high = gateway.nli_score({"claim_text": "시로 14세", "evidence": [{"snippet_text": "시로는 14세였다"}]})
    assert 0.0 <= score_low <= 1.0
    assert 0.0 <= score_high <= 1.0
    assert score_high >= score_low


@pytest.mark.unit
def test_remote_gateway_blocks_local_gen_method() -> None:
    gateway = select_model("remote_api")
    with pytest.raises(RuntimeError):
        gateway.suggest_local_gen({"claim_text": "x", "evidence": [{"snippet_text": "x"}]})
