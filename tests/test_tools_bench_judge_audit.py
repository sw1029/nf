from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from modules.nf_shared.config import Settings


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("judge_audit")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


def _import_backends_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("dev_judge_backends")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


@pytest.mark.unit
def test_source_policy_judge_selects_episode_hwa_family_with_mocked_nli() -> None:
    mod = _import_module()

    def fake_nli(premise, hypothesis, **kwargs):  # noqa: ANN001
        if "episode_hwa family" in hypothesis:
            return {"entail": 0.95, "fallback_used": False}
        return {"entail": 0.10, "fallback_used": False}

    result = mod.judge_source_policy(
        source_id="SRC-aaaa",
        content_sha256="a" * 64,
        candidate_boundary_counts={"episode_hwa": 10, "standalone_number": 20},
        content_length_stats={"text_chars": 1000},
        candidate_line_samples=[{"header": "1화", "pattern_name": "episode_hwa"}],
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
        nli_fn=fake_nli,
    )

    assert result["judge_backend"] == "local_nli"
    assert result["judge_requested_backend"] == "local_nli"
    assert result["judge_effective_backend"] == "local_nli_model"
    assert result["judge_model_id"] == "nli-lite-v1"
    assert result["judge_fallback_used"] is False
    assert result["judge_input_hash"]
    assert result["segmentation_policy"] == "source_override_pattern"
    assert result["accepted_pattern_family"] == ["episode_hwa", "angle_episode_hwa", "title_number_hwa"]
    assert result["manual_review_required"] is False


@pytest.mark.unit
def test_source_policy_judge_falls_back_to_manual_review_below_threshold() -> None:
    mod = _import_module()

    def fake_nli(premise, hypothesis, **kwargs):  # noqa: ANN001
        return {"entail": 0.20, "fallback_used": True}

    result = mod.judge_source_policy(
        source_id="SRC-bbbb",
        content_sha256="b" * 64,
        candidate_boundary_counts={"standalone_number": 20},
        content_length_stats={"text_chars": 1000},
        candidate_line_samples=[{"header": "1", "pattern_name": "standalone_number"}],
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
        nli_fn=fake_nli,
    )

    assert result["segmentation_policy"] == "manual_review"
    assert result["accepted_pattern_family"] == []
    assert result["judge_effective_backend"] == "local_nli_fallback"
    assert result["judge_fallback_used"] is True
    assert result["manual_review_required"] is True


@pytest.mark.unit
def test_inject_quality_judge_selects_clear_conflict_with_mocked_nli() -> None:
    mod = _import_module()

    def fake_nli(premise, hypothesis, **kwargs):  # noqa: ANN001
        if "명확한 충돌" in hypothesis:
            return {"entail": 0.93, "fallback_used": False}
        return {"entail": 0.05, "fallback_used": False}

    result = mod.judge_inject_quality(
        original_excerpt="원문",
        injected_statement="주인공의 나이는 50세였다.",
        injected_kind="age",
        source_metadata={"source_id": "SRC-cccc"},
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
        nli_fn=fake_nli,
    )

    assert result["inject_quality_label"] == "clear_conflict"
    assert result["judge_backend"] == "local_nli"
    assert result["judge_requested_backend"] == "local_nli"
    assert result["judge_effective_backend"] == "local_nli_model"
    assert result["judge_input_hash"]


@pytest.mark.unit
def test_inject_quality_judge_marks_remote_api_as_unsupported() -> None:
    mod = _import_module()

    result = mod.judge_inject_quality(
        original_excerpt="원문",
        injected_statement="주인공의 나이는 50세였다.",
        injected_kind="age",
        source_metadata={"source_id": "SRC-dddd"},
        settings=Settings(enable_test_judge_remote_api=True, test_judge_min_confidence=0.8),
    )

    assert result["judge_backend"] == "remote_api"
    assert result["judge_requested_backend"] == "remote_api"
    assert result["judge_effective_backend"] == "unsupported"
    assert result["inject_quality_label"] == "contextless_append"
    assert result["judge_reason"] == "test_judge_remote_api_unsupported"


@pytest.mark.unit
def test_remote_nli_distribution_uses_provider_timeout_and_parses_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_backends_module()
    monkeypatch.setenv("NF_REMOTE_PROVIDER", "openai")
    monkeypatch.setenv("NF_OPENAI_API_KEY", "test-key")
    captured: dict[str, object] = {}

    class FakeProvider:
        def complete(self, prompt: str, *, timeout_sec: float = 30.0) -> str:
            captured["prompt"] = prompt
            captured["timeout_sec"] = timeout_sec
            return '{"entail":0.7,"contradict":0.2,"neutral":0.1}'

    monkeypatch.setattr(mod, "select_remote_provider", lambda _name=None: FakeProvider())

    scores = mod.remote_nli_distribution("premise text", "hypothesis text", timeout_ms=1500)

    assert scores["effective_backend"] == "remote_api"
    assert scores["fallback_used"] is False
    assert scores["entail"] == pytest.approx(0.7)
    assert scores["contradict"] == pytest.approx(0.2)
    assert scores["neutral"] == pytest.approx(0.1)
    assert captured["timeout_sec"] == pytest.approx(1.5)
    assert "<BEGIN_INPUT_JSON>" in str(captured["prompt"])


@pytest.mark.unit
def test_inject_quality_judge_uses_remote_api_backend_with_mocked_nli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_module()
    monkeypatch.setenv("NF_REMOTE_PROVIDER", "openai")
    monkeypatch.setenv("NF_OPENAI_MODEL", "judge-gpt-mini")
    captured: dict[str, object] = {}

    def fake_remote_nli(premise, hypothesis, **kwargs):  # noqa: ANN001
        captured["premise"] = premise
        captured["hypothesis"] = hypothesis
        captured["kwargs"] = dict(kwargs)
        if "명확한 충돌" in hypothesis:
            return {
                "entail": 0.92,
                "contradict": 0.04,
                "neutral": 0.04,
                "effective_backend": "remote_api",
                "fallback_used": False,
            }
        return {
            "entail": 0.03,
            "contradict": 0.07,
            "neutral": 0.90,
            "effective_backend": "remote_api",
            "fallback_used": False,
        }

    result = mod.judge_inject_quality(
        original_excerpt="원문",
        injected_statement="주인공의 나이는 50세였다.",
        injected_kind="age",
        source_metadata={"source_id": "SRC-remote"},
        settings=Settings(enable_test_judge_remote_api=True, test_judge_timeout_ms=1500, test_judge_min_confidence=0.8),
        nli_fn=fake_remote_nli,
    )

    assert result["inject_quality_label"] == "clear_conflict"
    assert result["judge_backend"] == "remote_api"
    assert result["judge_requested_backend"] == "remote_api"
    assert result["judge_effective_backend"] == "remote_api"
    assert result["judge_model_id"] == "openai:judge-gpt-mini"
    assert result["judge_fallback_used"] is False
    assert result["judge_input_hash"]
    assert captured["kwargs"] == {"timeout_ms": 1500}


@pytest.mark.unit
def test_inject_quality_judge_reports_heuristic_backend_for_real_local_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_module()
    monkeypatch.setattr("modules.nf_model_gateway.local.text_pair_classifier.ensure_model", lambda _model_id: None)

    result = mod.judge_inject_quality(
        original_excerpt="주인공의 나이는 14세였다.",
        injected_statement="주인공의 나이는 50세였다.",
        injected_kind="age",
        source_metadata={"source_id": "SRC-heuristic"},
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
    )

    assert result["judge_backend"] == "local_nli"
    assert result["judge_requested_backend"] == "local_nli"
    assert result["judge_effective_backend"] == "heuristic"
    assert result["judge_fallback_used"] is True


@pytest.mark.unit
def test_typed_inject_quality_judge_uses_slot_compare_to_mark_clear_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_module()
    monkeypatch.setattr("modules.nf_model_gateway.local.text_pair_classifier.ensure_model", lambda _model_id: None)

    result = mod.judge_inject_quality(
        original_excerpt="나이: 14세\n직업: 검사",
        injected_statement="나이: 50세",
        injected_kind="age",
        source_metadata={
            "source_id": "SRC-typed",
            "typed_variant": True,
            "typed_subject_alias": "주인공",
        },
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
    )

    assert result["inject_quality_label"] == "clear_conflict"
    assert result["judge_effective_backend"] == "heuristic"
    assert result["judge_reason"] == "typed_slot_conflict"
    assert result["typed_slot_key"] == "age"
    assert result["typed_original_value"] == 14
    assert result["typed_injected_value"] == 50


@pytest.mark.unit
def test_typed_inject_quality_judge_marks_affiliation_entity_conflict_as_clear_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_module()
    monkeypatch.setattr("modules.nf_model_gateway.local.text_pair_classifier.ensure_model", lambda _model_id: None)

    result = mod.judge_inject_quality(
        original_excerpt="그렇게 라인시스 제국의 부활이 멀지 않았다며 모두가 기뻐했다.",
        injected_statement="소속: 황실 기사단",
        injected_kind="affiliation",
        source_metadata={
            "source_id": "SRC-typed-aff",
            "typed_variant": True,
            "typed_subject_alias": "장수남",
        },
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
    )

    assert result["inject_quality_label"] == "clear_conflict"
    assert result["judge_reason"] == "typed_affiliation_entity_conflict"
    assert result["typed_original_value"] == "라인시스 제국"
    assert result["typed_injected_value"] == "황실 기사단"


@pytest.mark.unit
def test_typed_inject_quality_judge_marks_explicit_school_affiliation_conflict_as_clear_conflict() -> None:
    mod = _import_module()

    result = mod.judge_inject_quality(
        original_excerpt="시로네는 도시에서 겪었던 일에 대해 함구했다.\n소속: 알페아스 마법학교",
        injected_statement="소속: 황실 기사단",
        injected_kind="affiliation",
        source_metadata={
            "source_id": "SRC-typed-aff-subject",
            "typed_variant": True,
            "typed_subject_alias": "시로네",
        },
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
    )

    assert result["inject_quality_label"] == "clear_conflict"
    assert result["judge_reason"] == "typed_affiliation_entity_conflict"
    assert result["typed_original_value"] == "알페아스 마법학교"
    assert result["typed_injected_value"] == "황실 기사단"


@pytest.mark.unit
def test_typed_inject_quality_judge_marks_non_suffix_affiliation_phrase_conflict_as_clear_conflict() -> None:
    mod = _import_module()

    result = mod.judge_inject_quality(
        original_excerpt="소속: 정무전 제삼대",
        injected_statement="소속: 황실 기사단",
        injected_kind="affiliation",
        source_metadata={
            "source_id": "SRC-typed-aff-phrase",
            "typed_variant": True,
            "typed_subject_alias": "그",
        },
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
    )

    assert result["inject_quality_label"] == "clear_conflict"
    assert result["judge_reason"] == "typed_affiliation_phrase_conflict"
    assert result["typed_original_value"] == "정무전 제삼대"
    assert result["typed_injected_value"] == "황실 기사단"


@pytest.mark.unit
def test_typed_inject_quality_judge_marks_job_phrase_conflict_as_clear_conflict() -> None:
    mod = _import_module()

    result = mod.judge_inject_quality(
        original_excerpt="직업: 이르멜가의 정원사",
        injected_statement="직업: 9서클 마법사",
        injected_kind="job",
        source_metadata={
            "source_id": "SRC-typed-job-phrase",
            "typed_variant": True,
            "typed_subject_alias": "주인공",
        },
        settings=Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8),
    )

    assert result["inject_quality_label"] == "clear_conflict"
    assert result["judge_reason"] == "typed_job_phrase_conflict"
    assert result["typed_original_value"] == "이르멜가의 정원사"
    assert result["typed_injected_value"] == "9서클 마법사"


@pytest.mark.unit
def test_inject_quality_judge_marks_empty_statement_as_malformed_template() -> None:
    mod = _import_module()

    result = mod.judge_inject_quality(
        original_excerpt="원문",
        injected_statement="",
        injected_kind="age",
        source_metadata={"source_id": "SRC-eeee"},
        settings=Settings(enable_test_judge_local_nli=False, enable_test_judge_remote_api=False),
    )

    assert result["inject_quality_label"] == "malformed_template"
    assert result["judge_reason"] == "invalid_or_empty_injected_statement"
