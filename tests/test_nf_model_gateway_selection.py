from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_model_gateway.gateway import BasicModelGateway, select_model
from modules.nf_model_gateway.local.model_store import describe_model
from modules.nf_model_gateway.local.nli_model import infer_nli_distribution
from modules.nf_shared.config import Settings


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
    assert set(scores.keys()) >= {"entail", "contradict", "neutral", "fallback_used", "effective_backend"}
    assert scores["fallback_used"] is True
    assert scores["effective_backend"] == "heuristic"


@pytest.mark.unit
def test_consistency_gateway_nli_distribution_reports_heuristic_backend_even_when_model_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("modules.nf_model_gateway.local.text_pair_classifier.ensure_model", lambda _model_id: object())
    scores = infer_nli_distribution("premise text", "hypothesis text", enabled=True, model_id="available-model")
    assert scores["fallback_used"] is False
    assert scores["effective_backend"] == "heuristic"


@pytest.mark.unit
def test_consistency_gateway_nli_distribution_uses_real_local_backend_when_runtime_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "nli-lite-v1"
    model_dir.mkdir()
    (model_dir / "nf_model_manifest.json").write_text(
        '{"backend":"hf_sequence_classification","label_order":["contradiction","neutral","entailment"],"max_length":128}',
        encoding="utf-8",
    )
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_text("stub", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("modules.nf_model_gateway.local.text_pair_classifier.ensure_model", lambda _model_id: model_dir)
    monkeypatch.setattr(
        "modules.nf_model_gateway.local.text_pair_classifier._classify_with_local_model",
        lambda premise_text, hypothesis_text, *, model_path: {
            "entail": 0.7,
            "contradict": 0.2,
            "neutral": 0.1,
            "effective_backend": "local_nli_model",
            "fallback_used": False,
        },
    )

    scores = infer_nli_distribution("premise text", "hypothesis text", enabled=True, model_id="nli-lite-v1")

    assert scores["fallback_used"] is False
    assert scores["effective_backend"] == "local_nli_model"
    assert scores["entail"] == pytest.approx(0.7)


@pytest.mark.unit
def test_model_store_describe_model_reports_runtime_ready_when_manifest_and_assets_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "nli-lite-v1"
    model_dir.mkdir(parents=True)
    (model_dir / "nf_model_manifest.json").write_text('{"backend":"hf_sequence_classification"}', encoding="utf-8")
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_text("stub", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NF_MODEL_STORE", str(tmp_path))

    status = describe_model("nli-lite-v1")

    assert status["present"] is True
    assert status["runtime_ready"] is True
    assert status["manifest_backend"] == "hf_sequence_classification"
    assert status["reason"] == "ok"


@pytest.mark.unit
def test_remote_gateway_blocks_local_gen_method() -> None:
    gateway = select_model("remote_api")
    with pytest.raises(RuntimeError):
        gateway.suggest_local_gen({"claim_text": "x", "evidence": [{"snippet_text": "x"}]})


@pytest.mark.unit
def test_consistency_gateway_local_extract_does_not_emit_bare_genius_token() -> None:
    gateway = BasicModelGateway(settings=Settings(enable_layer3_model=True), purpose="consistency")

    candidates = gateway.extract_slots_local(
        {
            "claim_text": "노력하는 천재.",
            "evidence": [],
            "model_slots": ["talent"],
            "timeout_ms": 500,
        }
    )

    assert candidates == []


@pytest.mark.unit
def test_consistency_gateway_local_extract_keeps_explicit_talent_label() -> None:
    gateway = BasicModelGateway(settings=Settings(enable_layer3_model=True), purpose="consistency")

    candidates = gateway.extract_slots_local(
        {
            "claim_text": "재능: 천재",
            "evidence": [],
            "model_slots": ["talent"],
            "timeout_ms": 500,
        }
    )

    assert any(item["slot_key"] == "talent" and item["value"] == "천재" for item in candidates)
