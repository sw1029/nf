from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from modules.nf_consistency.engine_parts.slot_logic import _compare_slot
from modules.nf_consistency.extractors.pipeline import ExtractionPipeline
from modules.nf_model_gateway.local.nli_model import infer_nli_distribution
from modules.nf_model_gateway.remote.provider import (
    remote_provider_credentials_configured,
    selected_remote_model_id,
)
from modules.nf_shared.config import Settings, load_config
from modules.nf_shared.protocol.dtos import Verdict
from dev_judge_backends import remote_nli_distribution

SOURCE_POLICY_JUDGE_PROMPT_VERSION = "source-policy-judge-v1"
INJECT_QUALITY_JUDGE_PROMPT_VERSION = "inject-quality-judge-v1"

_NliFn = Callable[..., dict[str, Any]]
_INJECT_SLOT_BY_KIND = {
    "age": "age",
    "job": "job",
    "talent": "talent",
    "time": "time",
    "affiliation": "affiliation",
    "relation": "relation",
    "death": "death",
    "place": "place",
}
_SUBJECT_BOUND_INJECT_SLOTS = {"age", "job", "talent", "affiliation", "relation", "death"}
_SLOT_HINTS = {
    "age": ("나이", "세", "살"),
    "job": ("직업", "클래스", "마법사", "기사", "시녀"),
    "talent": ("재능", "천재"),
    "time": ("시간", "시점", "날짜", "년", "월", "일", ":"),
    "affiliation": ("소속", "기사단", "제국", "길드", "연맹", "문파"),
    "relation": ("관계", "아들", "딸", "동생", "형제", "원수"),
    "death": ("사망", "죽", "생존", "살아"),
    "place": ("장소", "위치", "성", "궁", "도시", "마을"),
}
_AFFILIATION_ENTITY_SUFFIXES = (
    "제국",
    "왕국",
    "황궁",
    "길드",
    "협회",
    "연맹",
    "문파",
    "기사단",
    "경비대",
    "사단",
    "여단",
    "세가",
    "상단",
    "학교",
    "학원",
    "연구회",
    "교",
    "단",
    "문",
    "련",
    "회",
    "파",
    "궁",
    "관",
    "당",
    "각",
)
_AFFILIATION_GENERIC_TOKENS = {
    "제국",
    "왕국",
    "황궁",
    "길드",
    "협회",
    "연맹",
    "문파",
    "기사단",
    "경비대",
    "사단",
    "여단",
    "상단",
    "학교",
    "학원",
    "연구회",
}
_AFFILIATION_NOISE_PREFIXES = {
    "그렇게",
    "적당하게",
    "모두",
    "갑자기",
    "다시",
    "현재",
}
_KOREAN_PARTICLE_SUFFIXES = ("은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로", "으로")


def _local_enabled(settings: Settings) -> bool:
    return bool(settings.enable_test_judge_local_nli)


def _requested_backend(settings: Settings) -> str:
    if bool(settings.enable_test_judge_local_nli):
        return "local_nli"
    if bool(settings.enable_test_judge_remote_api):
        return "remote_api"
    return "disabled"


def _model_id_for_backend(settings: Settings, requested_backend: str) -> str:
    if requested_backend == "local_nli":
        return str(settings.test_judge_local_nli_model_id or "")
    if requested_backend == "remote_api":
        return selected_remote_model_id()
    return ""


def _judge_input_hash(
    *,
    premise: str,
    hypotheses: dict[str, str],
    prompt_version: str,
    requested_backend: str,
    model_id: str,
) -> str:
    payload = {
        "premise": premise,
        "hypotheses": hypotheses,
        "prompt_version": prompt_version,
        "requested_backend": requested_backend,
        "model_id": model_id,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _score_effective_backend(requested_backend: str, scores: dict[str, Any]) -> str:
    explicit = str(scores.get("effective_backend") or scores.get("judge_effective_backend") or "").strip()
    if explicit:
        return explicit
    fallback_used = bool(scores.get("fallback_used"))
    if requested_backend == "local_nli":
        return "local_nli_fallback" if fallback_used else "local_nli_model"
    if requested_backend == "remote_api":
        return "remote_api"
    return "disabled"


def _score_hypotheses(
    premise: str,
    hypotheses: dict[str, str],
    *,
    prompt_version: str,
    settings: Settings,
    nli_fn: _NliFn | None = None,
) -> tuple[str, float, dict[str, Any]]:
    requested_backend = _requested_backend(settings)
    model_id = _model_id_for_backend(settings, requested_backend)
    judge_input_hash = _judge_input_hash(
        premise=premise,
        hypotheses=hypotheses,
        prompt_version=prompt_version,
        requested_backend=requested_backend,
        model_id=model_id,
    )
    if requested_backend == "disabled":
        return (
            "",
            0.0,
            {
                "judge_requested_backend": requested_backend,
                "judge_effective_backend": "disabled",
                "judge_model_id": model_id,
                "judge_prompt_version": prompt_version,
                "judge_fallback_used": False,
                "judge_input_hash": judge_input_hash,
            },
        )
    if requested_backend == "remote_api" and nli_fn is None and not remote_provider_credentials_configured():
        return (
            "",
            0.0,
            {
                "judge_requested_backend": requested_backend,
                "judge_effective_backend": "unsupported",
                "judge_model_id": model_id,
                "judge_prompt_version": prompt_version,
                "judge_fallback_used": False,
                "judge_input_hash": judge_input_hash,
            },
        )
    judge_fn = nli_fn or (remote_nli_distribution if requested_backend == "remote_api" else infer_nli_distribution)
    best_label = ""
    best_score = 0.0
    fallback_used = False
    effective_backend = ""
    for label, hypothesis in hypotheses.items():
        if requested_backend == "remote_api":
            scores = judge_fn(
                premise,
                hypothesis,
                timeout_ms=int(settings.test_judge_timeout_ms),
            )
        else:
            scores = judge_fn(
                premise,
                hypothesis,
                enabled=_local_enabled(settings),
                model_id=model_id,
            )
        try:
            entail = float(scores.get("entail", 0.0))
        except (TypeError, ValueError):
            entail = 0.0
        fallback_used = fallback_used or bool(scores.get("fallback_used"))
        score_backend = _score_effective_backend(requested_backend, scores)
        if not effective_backend:
            effective_backend = score_backend
        elif effective_backend != score_backend:
            if "local_nli_fallback" in {effective_backend, score_backend}:
                effective_backend = "local_nli_fallback"
            elif "heuristic" in {effective_backend, score_backend}:
                effective_backend = "heuristic"
        if entail > best_score:
            best_label = label
            best_score = entail
    return (
        best_label,
        best_score,
        {
            "judge_requested_backend": requested_backend,
            "judge_effective_backend": effective_backend,
            "judge_model_id": model_id,
            "judge_prompt_version": prompt_version,
            "judge_fallback_used": fallback_used,
            "judge_input_hash": judge_input_hash,
        },
    )


def _typed_pipeline() -> ExtractionPipeline:
    return ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)


def _iter_nonempty_lines(text: str) -> list[str]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if lines:
        return lines
    fallback = str(text or "").strip()
    return [fallback] if fallback else []


def _split_phrase_tokens(text: object) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = re.split(r"[\s,./;:()\[\]{}<>|\"'“”‘’]+", raw)
    return [re.sub(r"[^0-9A-Za-z가-힣]+", "", item) for item in parts if re.sub(r"[^0-9A-Za-z가-힣]+", "", item)]


def _is_affiliation_entity_value(value: object) -> bool:
    tokens = _split_phrase_tokens(value)
    if not tokens:
        return False
    last = tokens[-1]
    return any(last.endswith(suffix) for suffix in _AFFILIATION_ENTITY_SUFFIXES)


def _is_noise_prefix_token(token: str) -> bool:
    if not token:
        return True
    if token in _AFFILIATION_NOISE_PREFIXES:
        return True
    return any(token.endswith(suffix) for suffix in _KOREAN_PARTICLE_SUFFIXES)


def _normalize_affiliation_entity_value(value: object) -> object:
    tokens = _split_phrase_tokens(value)
    if not tokens:
        return value
    last_suffix_idx = -1
    for idx, token in enumerate(tokens):
        if any(token.endswith(suffix) for suffix in _AFFILIATION_ENTITY_SUFFIXES):
            last_suffix_idx = idx
    if last_suffix_idx < 0:
        return value
    start_idx = last_suffix_idx
    while start_idx > 0 and (last_suffix_idx - start_idx) < 2:
        prev = tokens[start_idx - 1]
        if _is_noise_prefix_token(prev):
            break
        start_idx -= 1
    normalized_tokens = tokens[start_idx : last_suffix_idx + 1]
    if len(normalized_tokens) == 1 and normalized_tokens[0] in _AFFILIATION_GENERIC_TOKENS:
        return value
    return " ".join(normalized_tokens)


def _has_fuzzy_phrase_token_overlap(left: object, right: object) -> bool:
    left_tokens = _split_phrase_tokens(left)
    right_tokens = _split_phrase_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    for left_token in left_tokens:
        for right_token in right_tokens:
            if left_token == right_token:
                return True
            if left_token in right_token or right_token in left_token:
                return True
    return False


def _has_disjoint_typed_phrase_conflict(slot_key: str, original_value: object, injected_value: object) -> bool:
    if slot_key not in {"affiliation", "job"}:
        return False
    original_tokens = _split_phrase_tokens(original_value)
    injected_tokens = _split_phrase_tokens(injected_value)
    if not original_tokens or not injected_tokens:
        return False
    if _has_fuzzy_phrase_token_overlap(original_value, injected_value):
        return False
    if len(original_tokens) > 4 or len(injected_tokens) > 4:
        return False
    if slot_key == "affiliation":
        return (
            _is_affiliation_entity_value(original_value)
            or _is_affiliation_entity_value(injected_value)
            or len(original_tokens) >= 2
            or len(injected_tokens) >= 2
        )
    return True


def _line_slot_hint_score(line: str, slot_key: str, *, subject_alias: str) -> float:
    score = 0.0
    if subject_alias and subject_alias in line:
        score += 2.0
    if any(token in line for token in _SLOT_HINTS.get(slot_key, ())):
        score += 1.0
    return score


def _extract_slot_value(
    text: str,
    slot_key: str,
    *,
    subject_alias: str,
) -> tuple[object | None, dict[str, Any]]:
    pipeline = _typed_pipeline()
    subject_alias_present_in_excerpt = bool(subject_alias and subject_alias in str(text or ""))
    best_value: object | None = None
    best_meta: dict[str, Any] = {
        "line": "",
        "line_has_hint": False,
        "subject_alias_present": subject_alias_present_in_excerpt,
        "subject_alias_present_in_line": False,
        "subject_alias_present_in_excerpt": subject_alias_present_in_excerpt,
    }
    best_score = float("-inf")
    for line in _iter_nonempty_lines(text):
        result = pipeline.extract(line)
        if slot_key not in result.slots:
            continue
        confidence = max(
            (
                float(candidate.confidence)
                for candidate in result.candidates
                if str(candidate.slot_key or "") == slot_key
            ),
            default=0.0,
        )
        hint_score = _line_slot_hint_score(line, slot_key, subject_alias=subject_alias)
        score = hint_score + confidence - min(len(line) / 1000.0, 0.5)
        if score <= best_score:
            continue
        best_score = score
        best_value = result.slots.get(slot_key)
        if slot_key == "affiliation" and best_value is not None:
            best_value = _normalize_affiliation_entity_value(best_value)
        best_meta = {
            "line": line,
            "line_has_hint": hint_score > 0.0,
            "subject_alias_present": bool(subject_alias and subject_alias in line),
            "subject_alias_present_in_line": bool(subject_alias and subject_alias in line),
            "subject_alias_present_in_excerpt": subject_alias_present_in_excerpt,
        }
    return best_value, best_meta


def _typed_inject_assessment(
    *,
    original_excerpt: str,
    injected_statement: str,
    injected_kind: str,
    source_metadata: dict[str, Any],
) -> dict[str, Any] | None:
    if not bool(source_metadata.get("typed_variant")):
        return None
    slot_key = str(_INJECT_SLOT_BY_KIND.get(str(injected_kind or "").strip(), "") or "")
    if not slot_key:
        return {
            "inject_quality_label": "malformed_template",
            "judge_confidence": 0.0,
            "judge_reason": "typed_variant_unknown_slot",
            "typed_slot_key": "",
            "typed_original_value": None,
            "typed_injected_value": None,
        }
    subject_alias = str(source_metadata.get("typed_subject_alias") or "").strip()
    injected_value, _injected_meta = _extract_slot_value(
        injected_statement,
        slot_key,
        subject_alias=subject_alias,
    )
    if injected_value is None:
        return {
            "inject_quality_label": "malformed_template",
            "judge_confidence": 0.0,
            "judge_reason": "typed_variant_slot_not_extracted",
            "typed_slot_key": slot_key,
            "typed_original_value": None,
            "typed_injected_value": None,
        }

    original_value, original_meta = _extract_slot_value(
        original_excerpt,
        slot_key,
        subject_alias=subject_alias,
    )
    if original_value is None:
        label = "contextless_append"
        reason = "typed_variant_missing_original_slot"
        if (
            slot_key in _SUBJECT_BOUND_INJECT_SLOTS
            and subject_alias
            and not bool(original_meta.get("subject_alias_present"))
            and not bool(original_meta.get("subject_alias_present_in_excerpt"))
            and not bool(original_meta.get("line_has_hint"))
        ):
            label = "ambiguous_subject"
            reason = "typed_variant_subject_not_grounded"
        return {
            "inject_quality_label": label,
            "judge_confidence": 0.72 if label == "contextless_append" else 0.76,
            "judge_reason": reason,
            "typed_slot_key": slot_key,
            "typed_original_value": None,
            "typed_injected_value": injected_value,
        }

    verdict = _compare_slot(slot_key, injected_value, original_value)
    if verdict is Verdict.VIOLATE:
        return {
            "inject_quality_label": "clear_conflict",
            "judge_confidence": 0.95,
            "judge_reason": "typed_slot_conflict",
            "typed_slot_key": slot_key,
            "typed_original_value": original_value,
            "typed_injected_value": injected_value,
        }
    if verdict is Verdict.OK:
        return {
            "inject_quality_label": "no_conflict",
            "judge_confidence": 0.93,
            "judge_reason": "typed_slot_matches_original",
            "typed_slot_key": slot_key,
            "typed_original_value": original_value,
            "typed_injected_value": injected_value,
        }
    if (
        verdict is None
        and slot_key == "affiliation"
        and _is_affiliation_entity_value(original_value)
        and _is_affiliation_entity_value(injected_value)
    ):
        original_tokens = set(_split_phrase_tokens(original_value))
        injected_tokens = set(_split_phrase_tokens(injected_value))
        if original_tokens and injected_tokens and not original_tokens.intersection(injected_tokens):
            return {
                "inject_quality_label": "clear_conflict",
                "judge_confidence": 0.91,
                "judge_reason": "typed_affiliation_entity_conflict",
                "typed_slot_key": slot_key,
                "typed_original_value": original_value,
                "typed_injected_value": injected_value,
            }
    if verdict is None and _has_disjoint_typed_phrase_conflict(slot_key, original_value, injected_value):
        return {
            "inject_quality_label": "clear_conflict",
            "judge_confidence": 0.89 if slot_key == "affiliation" else 0.88,
            "judge_reason": f"typed_{slot_key}_phrase_conflict",
            "typed_slot_key": slot_key,
            "typed_original_value": original_value,
            "typed_injected_value": injected_value,
        }
    label = "contextless_append"
    reason = "typed_slot_uncomparable"
    if (
        slot_key in _SUBJECT_BOUND_INJECT_SLOTS
        and subject_alias
        and not bool(original_meta.get("subject_alias_present"))
        and not bool(original_meta.get("subject_alias_present_in_excerpt"))
        and not bool(original_meta.get("line_has_hint"))
    ):
        label = "ambiguous_subject"
        reason = "typed_variant_subject_not_grounded"
    return {
        "inject_quality_label": label,
        "judge_confidence": 0.70 if label == "contextless_append" else 0.74,
        "judge_reason": reason,
        "typed_slot_key": slot_key,
        "typed_original_value": original_value,
        "typed_injected_value": injected_value,
    }


def judge_source_policy(
    *,
    source_id: str,
    content_sha256: str,
    candidate_boundary_counts: dict[str, int],
    content_length_stats: dict[str, int],
    candidate_line_samples: list[dict[str, Any]],
    settings: Settings | None = None,
    nli_fn: _NliFn | None = None,
) -> dict[str, Any]:
    resolved_settings = settings or load_config()
    requested_backend = _requested_backend(resolved_settings)
    if requested_backend == "disabled":
        return {
            "judge_backend": requested_backend,
            "judge_requested_backend": requested_backend,
            "judge_effective_backend": "disabled",
            "judge_model_id": "",
            "judge_prompt_version": SOURCE_POLICY_JUDGE_PROMPT_VERSION,
            "judge_fallback_used": False,
            "judge_input_hash": "",
            "segmentation_policy": "manual_review",
            "accepted_pattern_family": [],
            "confidence": 0.0,
            "reason": "test_judge_local_disabled",
            "manual_review_required": True,
        }

    premise = json.dumps(
        {
            "source_id": source_id,
            "content_sha256": content_sha256,
            "candidate_boundary_counts": candidate_boundary_counts,
            "content_length_stats": content_length_stats,
            "candidate_line_samples": candidate_line_samples[:8],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    hypotheses = {
        "episode_hwa_family": "이 source는 episode_hwa family boundary가 신뢰 가능하다.",
        "ep_prefix_family": "이 source는 ep_prefix family boundary가 신뢰 가능하다.",
        "standalone_number_family": "이 source는 standalone_number family boundary가 신뢰 가능하다.",
        "manual_review": "이 source는 manual_review가 필요하다.",
    }
    best_label, best_score, judge_meta = _score_hypotheses(
        premise,
        hypotheses,
        prompt_version=SOURCE_POLICY_JUDGE_PROMPT_VERSION,
        settings=resolved_settings,
        nli_fn=nli_fn,
    )
    if str(judge_meta.get("judge_effective_backend") or "") == "unsupported":
        return {
            "judge_backend": requested_backend,
            **judge_meta,
            "segmentation_policy": "manual_review",
            "accepted_pattern_family": [],
            "confidence": 0.0,
            "reason": "test_judge_remote_api_unsupported",
            "manual_review_required": True,
        }
    label_to_patterns = {
        "episode_hwa_family": ["episode_hwa", "angle_episode_hwa", "title_number_hwa"],
        "ep_prefix_family": ["ep_prefix"],
        "standalone_number_family": ["standalone_number"],
        "manual_review": [],
    }
    segmentation_policy = "manual_review" if best_label == "manual_review" else "source_override_pattern"
    accepted_pattern_family = list(label_to_patterns.get(best_label, []))
    if best_score < float(resolved_settings.test_judge_min_confidence):
        segmentation_policy = "manual_review"
        accepted_pattern_family = []
        reason = "judge_confidence_below_threshold"
    else:
        reason = f"judge_selected:{best_label}"
    return {
        "judge_backend": requested_backend,
        **judge_meta,
        "segmentation_policy": segmentation_policy,
        "accepted_pattern_family": accepted_pattern_family,
        "confidence": best_score,
        "reason": reason,
        "manual_review_required": segmentation_policy == "manual_review",
    }


def judge_inject_quality(
    *,
    original_excerpt: str,
    injected_statement: str,
    injected_kind: str,
    source_metadata: dict[str, Any],
    settings: Settings | None = None,
    nli_fn: _NliFn | None = None,
) -> dict[str, Any]:
    resolved_settings = settings or load_config()
    requested_backend = _requested_backend(resolved_settings)
    if not str(injected_statement or "").strip() or not str(injected_kind or "").strip():
        return {
            "judge_backend": requested_backend,
            "judge_requested_backend": requested_backend,
            "judge_effective_backend": "disabled" if requested_backend == "disabled" else requested_backend,
            "judge_model_id": _model_id_for_backend(resolved_settings, requested_backend),
            "judge_prompt_version": INJECT_QUALITY_JUDGE_PROMPT_VERSION,
            "judge_fallback_used": False,
            "judge_input_hash": "",
            "inject_quality_label": "malformed_template",
            "judge_confidence": 0.0,
            "judge_reason": "invalid_or_empty_injected_statement",
        }
    if requested_backend == "disabled":
        return {
            "judge_backend": requested_backend,
            "judge_requested_backend": requested_backend,
            "judge_effective_backend": "disabled",
            "judge_model_id": "",
            "judge_prompt_version": INJECT_QUALITY_JUDGE_PROMPT_VERSION,
            "judge_fallback_used": False,
            "judge_input_hash": "",
            "inject_quality_label": "contextless_append",
            "judge_confidence": 0.0,
            "judge_reason": "test_judge_local_disabled",
        }

    premise = json.dumps(
        {
            "original_excerpt": original_excerpt[-1200:],
            "injected_statement": injected_statement,
            "injected_kind": injected_kind,
            "source_metadata": source_metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    hypotheses = {
        "clear_conflict": "추가 문장은 동일 주체에 대해 명확한 충돌을 만든다.",
        "ambiguous_subject": "추가 문장은 주체가 애매해서 같은 인물 충돌로 보기 어렵다.",
        "contextless_append": "추가 문장은 문맥과 분리되어 있어 평가용 append 흔적에 가깝다.",
        "no_conflict": "추가 문장은 원문과 충돌하지 않는다.",
        "malformed_template": "추가 문장은 템플릿이 깨졌거나 목표 slot과 문장이 맞지 않는다.",
    }
    best_label, best_score, judge_meta = _score_hypotheses(
        premise,
        hypotheses,
        prompt_version=INJECT_QUALITY_JUDGE_PROMPT_VERSION,
        settings=resolved_settings,
        nli_fn=nli_fn,
    )
    if str(judge_meta.get("judge_effective_backend") or "") == "unsupported":
        return {
            "judge_backend": requested_backend,
            **judge_meta,
            "inject_quality_label": "contextless_append",
            "judge_confidence": 0.0,
            "judge_reason": "test_judge_remote_api_unsupported",
        }
    typed_assessment = _typed_inject_assessment(
        original_excerpt=original_excerpt,
        injected_statement=injected_statement,
        injected_kind=injected_kind,
        source_metadata=source_metadata,
    )
    if typed_assessment is not None:
        return {
            "judge_backend": requested_backend,
            **judge_meta,
            "inject_quality_label": str(typed_assessment.get("inject_quality_label") or "contextless_append"),
            "judge_confidence": float(typed_assessment.get("judge_confidence") or 0.0),
            "judge_reason": str(typed_assessment.get("judge_reason") or "typed_variant_fallback"),
            "typed_slot_key": str(typed_assessment.get("typed_slot_key") or ""),
            "typed_original_value": typed_assessment.get("typed_original_value"),
            "typed_injected_value": typed_assessment.get("typed_injected_value"),
        }
    if best_score < float(resolved_settings.test_judge_min_confidence):
        best_label = "contextless_append"
        reason = "judge_confidence_below_threshold"
    else:
        reason = f"judge_selected:{best_label}"
    return {
        "judge_backend": requested_backend,
        **judge_meta,
        "inject_quality_label": best_label,
        "judge_confidence": best_score,
        "judge_reason": reason,
    }
