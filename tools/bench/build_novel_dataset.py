from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.nf_shared.config import load_config

from judge_audit import judge_inject_quality, judge_source_policy
from source_policy_profile import summarize_consistency_corroboration_policy

PRIMARY_EP_RE = re.compile(r"^\[(\d{1,5})\]\s*(.*)$")
EPISODE_HWA_RE = re.compile(r"^(?P<number>\d{1,5})\s*화(?:\s*[-.:]?\s*(?P<title>.*))?$")
ANGLE_EPISODE_HWA_RE = re.compile(r"^[<＜]\s*(?P<number>\d{1,5})\s*화\s*[>＞]$")
TITLE_NUMBER_HWA_RE = re.compile(r"^(?P<title>[0-9A-Za-z\uac00-\ud7a3 _-]{2,100}?)\s+(?P<number>\d{1,5})\s*화$")
EP_PREFIX_RE = re.compile(r"^(?:EP|Ep|ep)\.?\s*(?P<number>\d{1,5})(?:\s+|$)")
BRACKETED_NUMBERED_TITLE_RE = re.compile(r"^[\u3010\[]\s*(?P<number>\d{1,5})\.(?!\d)\s*(?P<title>.*?)[\u3011\]]$")
NUMBERED_TITLE_RE = re.compile(r"^(?P<number>\d{1,5})\.(?!\d)\s*(?P<title>.*)$")
ANGLE_TITLE_PAREN_RE = re.compile(r"^[<＜]\s*(?P<title>[^<>]{1,100}?)\((?P<number>\d{1,5})\)\s*[>＞]$")
PLAIN_TITLE_PAREN_RE = re.compile(r"^(?P<title>[^()\d][^()]{0,100}?)\((?P<number>\d{1,5})\)$")
SECTION_JO_RE = re.compile(r"^\uc81c\s*(?P<number>\d{1,5})\s*\uc870[.]?(?:\s*(?P<title>.*))?$")
CHAPTER_JANG_RE = re.compile(r"^\uc81c\s*(?P<number>\d{1,5})\s*\uc7a5[.]?(?:\s*(?P<title>.*))?$")
PROLOGUE_HEADER_RE = re.compile(r"^(?:\ud504\ub864\ub85c\uadf8)$")
STANDALONE_NUMBER_RE = re.compile(r"^(?P<number>\d{1,5})$")
SECONDARY_EP_RE = re.compile(r"^.*?-(\d{1,5})\s*$")
_MAX_HEADER_CHARS = 120
_FALLBACK_CHUNK_SIZE = 12000
_DATASET_GENERATION_VERSION = "20260312-r7"
_SOURCE_POLICY_REGISTRY_VERSION = "20260307-r1"
_SOURCE_POLICY_REGISTRY_PATH = _THIS_DIR / "source_policy_registry.json"
_WARN_MIN_SEGMENT_CHARS = 40
_WARN_MAX_SEGMENT_CHARS = 20000
_PATTERN_NAMES = (
    "bracket",
    "episode_hwa",
    "angle_episode_hwa",
    "title_number_hwa",
    "ep_prefix",
    "bracketed_numbered_title",
    "section_jo",
    "chapter_jang",
    "prologue_header",
    "numbered_title",
    "angle_title_paren",
    "plain_title_paren",
    "standalone_number",
    "trailing_dash",
)
_TITLE_PATTERN_NAMES = {
    "title_number_hwa",
    "bracketed_numbered_title",
    "chapter_jang",
    "numbered_title",
    "angle_title_paren",
    "plain_title_paren",
    "standalone_number",
}
_FRONT_MATTER_TOKENS = (
    "all rights",
    "produced in korea",
    "머리말",
    "프롤로그",
    "prologue",
    "차례",
)
_UNSUPPORTED_HEADER_VARIANT_RES = (
    re.compile(r"^\s*(?:chapter|ch(?:apter)?\.?)\s*\d{1,5}\b", re.IGNORECASE),
    re.compile(r"^\s*제\s*\d{1,5}\s*장(?:\s|$)"),
    re.compile(r"^\s*(?:서장|종장|외전|프롤로그|에필로그)(?:\s|$)"),
)


@dataclass
class Episode:
    source_file: str
    source_id: str
    source_content_sha256: str
    episode_no: int
    header: str
    content: str
    segmentation_mode: str
    boundary_pattern: str | None


def make_source_id(content_sha256: str) -> str:
    return f"SRC-{str(content_sha256 or '').lower()[:12]}"


def _guard_output_dir_for_judge_audit(output_dir: Path, *, enable_judge_audit: bool) -> None:
    if not enable_judge_audit:
        return
    canonical_dir = (_REPO_ROOT / "verify" / "datasets").resolve()
    resolved_output = output_dir.resolve()
    if resolved_output == canonical_dir or resolved_output.is_relative_to(canonical_dir):
        raise SystemExit(
            "judge audit output must not target canonical verify/datasets; use a developer-only run-scoped directory"
        )


def _load_source_policy_registry() -> tuple[dict[str, dict[str, object]], str]:
    if not _SOURCE_POLICY_REGISTRY_PATH.exists():
        return {}, ""
    payload = json.loads(_SOURCE_POLICY_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}, ""
    version = str(payload.get("source_policy_registry_version") or "")
    entries_raw = payload.get("sources")
    if not isinstance(entries_raw, list):
        return {}, version
    registry: dict[str, dict[str, object]] = {}
    for item in entries_raw:
        if not isinstance(item, dict):
            continue
        content_sha256 = str(item.get("content_sha256") or "").lower()
        source_id = str(item.get("source_id") or "")
        if not content_sha256 or not source_id:
            continue
        registry[content_sha256] = dict(item)
    return registry, version


def _source_policy_from_registry(entry: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(entry, dict):
        return {
            "segmentation_policy": "auto",
            "allowed_patterns": [],
            "policy_decision_source": "profile_auto",
            "policy_confidence": 0.0,
            "reason": "no_registry_entry",
        }
    allowed_patterns_raw = entry.get("allowed_patterns")
    allowed_patterns = (
        [str(item) for item in allowed_patterns_raw if isinstance(item, str)]
        if isinstance(allowed_patterns_raw, list)
        else []
    )
    return {
        "segmentation_policy": str(entry.get("segmentation_policy") or "auto"),
        "allowed_patterns": allowed_patterns,
        "policy_decision_source": str(entry.get("policy_decision_source") or "registry_override"),
        "policy_confidence": float(entry.get("policy_confidence") or 1.0),
        "reason": str(entry.get("reason") or ""),
    }


def read_text_auto(path: Path) -> tuple[str, str]:
    for enc in ("utf-8", "utf-8-sig", "utf-16", "cp949", "euc-kr"):
        try:
            return path.read_text(encoding=enc), enc
        except UnicodeError:
            continue
    return path.read_text(errors="ignore"), "unknown"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        while True:
            chunk = file_handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _match_episode_header(
    line_text: str,
    *,
    allow_title_patterns: bool,
) -> tuple[int, str] | None:
    stripped = line_text.strip()
    if not stripped or len(stripped) > _MAX_HEADER_CHARS:
        return None

    primary = PRIMARY_EP_RE.match(stripped)
    if primary:
        return int(primary.group(1)), "bracket"

    episode_hwa = EPISODE_HWA_RE.match(stripped)
    if episode_hwa:
        return int(episode_hwa.group("number")), "episode_hwa"

    angle_episode_hwa = ANGLE_EPISODE_HWA_RE.match(stripped)
    if angle_episode_hwa:
        return int(angle_episode_hwa.group("number")), "angle_episode_hwa"

    title_number_hwa = TITLE_NUMBER_HWA_RE.match(stripped)
    if title_number_hwa:
        return int(title_number_hwa.group("number")), "title_number_hwa"

    ep_prefix = EP_PREFIX_RE.match(stripped)
    if ep_prefix:
        return int(ep_prefix.group("number")), "ep_prefix"

    if allow_title_patterns:
        bracketed_numbered_title = BRACKETED_NUMBERED_TITLE_RE.match(stripped)
        if bracketed_numbered_title:
            return int(bracketed_numbered_title.group("number")), "bracketed_numbered_title"
        section_jo = SECTION_JO_RE.match(stripped)
        if section_jo:
            return int(section_jo.group("number")), "section_jo"
        chapter_jang = CHAPTER_JANG_RE.match(stripped)
        if chapter_jang:
            return int(chapter_jang.group("number")), "chapter_jang"
        prologue_header = PROLOGUE_HEADER_RE.match(stripped)
        if prologue_header:
            return 0, "prologue_header"
        numbered_title = NUMBERED_TITLE_RE.match(stripped)
        if numbered_title:
            return int(numbered_title.group("number")), "numbered_title"
        angle_title_paren = ANGLE_TITLE_PAREN_RE.match(stripped)
        if angle_title_paren:
            return int(angle_title_paren.group("number")), "angle_title_paren"
        plain_title_paren = PLAIN_TITLE_PAREN_RE.match(stripped)
        if plain_title_paren:
            return int(plain_title_paren.group("number")), "plain_title_paren"
        standalone_number = STANDALONE_NUMBER_RE.match(stripped)
        if standalone_number:
            return int(standalone_number.group("number")), "standalone_number"

    secondary = SECONDARY_EP_RE.match(stripped)
    if secondary:
        return int(secondary.group(1)), "trailing_dash"

    return None


def _profile_policy_from_candidate_counts(candidate_counts: dict[str, int]) -> dict[str, object]:
    high_conf_episode_family = {
        "bracket",
        "episode_hwa",
        "angle_episode_hwa",
        "title_number_hwa",
        "ep_prefix",
        "bracketed_numbered_title",
        "section_jo",
        "chapter_jang",
        "prologue_header",
    }
    title_family = {"numbered_title", "angle_title_paren", "plain_title_paren"}

    if any(int(candidate_counts.get(name, 0)) >= 2 for name in high_conf_episode_family):
        allowed_patterns = [name for name in high_conf_episode_family if int(candidate_counts.get(name, 0)) > 0]
        top_count = max(int(candidate_counts.get(name, 0)) for name in allowed_patterns)
        total = max(1, int(sum(int(candidate_counts.get(name, 0)) for name in allowed_patterns)))
        return {
            "segmentation_policy": "auto",
            "allowed_patterns": allowed_patterns,
            "policy_decision_source": "profile_auto",
            "policy_confidence": min(0.99, 0.60 + (float(top_count) / float(total))),
            "reason": "repeated_high_conf_episode_markers",
        }

    if any(int(candidate_counts.get(name, 0)) >= 2 for name in title_family):
        allowed_patterns = [name for name in title_family if int(candidate_counts.get(name, 0)) > 0]
        top_count = max(int(candidate_counts.get(name, 0)) for name in allowed_patterns)
        total = max(1, int(sum(int(candidate_counts.get(name, 0)) for name in allowed_patterns)))
        return {
            "segmentation_policy": "auto",
            "allowed_patterns": allowed_patterns,
            "policy_decision_source": "profile_auto",
            "policy_confidence": min(0.95, 0.50 + (float(top_count) / float(total))),
            "reason": "repeated_title_style_markers",
        }

    if int(candidate_counts.get("standalone_number", 0)) >= 2:
        return {
            "segmentation_policy": "manual_review",
            "allowed_patterns": [],
            "policy_decision_source": "profile_auto",
            "policy_confidence": 0.25,
            "reason": "standalone_number_requires_override_or_judge",
        }

    if int(sum(int(candidate_counts.get(name, 0)) for name in _PATTERN_NAMES)) == 0:
        return {
            "segmentation_policy": "manual_review",
            "allowed_patterns": [],
            "policy_decision_source": "profile_auto",
            "policy_confidence": 0.0,
            "reason": "no_repeated_candidate_markers",
        }

    return {
        "segmentation_policy": "manual_review",
        "allowed_patterns": [],
        "policy_decision_source": "profile_auto",
        "policy_confidence": 0.20,
        "reason": "low_confidence_candidate_distribution",
    }


def _select_boundary_patterns(candidate_counts: dict[str, int]) -> set[str]:
    ranked = sorted(
        ((name, int(candidate_counts.get(name, 0))) for name in _PATTERN_NAMES),
        key=lambda item: item[1],
        reverse=True,
    )
    top_name, top_count = ranked[0]
    second_name, second_count = ranked[1]
    if top_count < 2:
        return set()
    high_conf_episode_family = {
        "bracket",
        "episode_hwa",
        "angle_episode_hwa",
        "title_number_hwa",
        "ep_prefix",
        "bracketed_numbered_title",
        "section_jo",
    }
    title_family = {"numbered_title", "angle_title_paren", "plain_title_paren"}
    if any(int(candidate_counts.get(name, 0)) >= 2 for name in high_conf_episode_family):
        return {name for name in high_conf_episode_family if int(candidate_counts.get(name, 0)) > 0}
    if any(int(candidate_counts.get(name, 0)) >= 2 for name in title_family):
        return {name for name in title_family if int(candidate_counts.get(name, 0)) > 0}
    if (
        top_name in {"episode_hwa", "bracket"}
        and second_name in {"episode_hwa", "bracket"}
        and second_count >= 2
        and top_count < int(second_count * 1.5)
    ):
        return {top_name, second_name}
    if top_count >= max(2, int(second_count * 1.5)):
        return {top_name}
    return {name for name, count in ranked if count >= 2}


def _resolve_effective_source_policy(
    *,
    registry_policy: dict[str, object],
    candidate_boundary_counts: dict[str, int],
) -> dict[str, object]:
    registry_segmentation_policy = str(registry_policy.get("segmentation_policy") or "auto")
    registry_allowed_patterns = [
        str(item) for item in (registry_policy.get("allowed_patterns") or []) if isinstance(item, str)
    ]
    if registry_segmentation_policy != "auto" or registry_allowed_patterns:
        return {
            **registry_policy,
            "segmentation_policy": registry_segmentation_policy,
            "allowed_patterns": registry_allowed_patterns,
        }
    return _profile_policy_from_candidate_counts(candidate_boundary_counts)


def _candidate_line_samples(candidate_boundaries: list[tuple[int, int, str, str]]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for offset, episode_no, header, pattern_name in candidate_boundaries[:12]:
        samples.append(
            {
                "offset": offset,
                "episode_no": episode_no,
                "header": header,
                "pattern_name": pattern_name,
            }
        )
    return samples


def _manual_review_diagnostics(text: str, candidate_boundary_counts: dict[str, int]) -> dict[str, object]:
    total_candidate_boundaries = int(sum(int(candidate_boundary_counts.get(name, 0)) for name in _PATTERN_NAMES))
    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    head = nonempty_lines[:80]
    head_lower = [line.lower() for line in head]
    front_matter_hits = sum(1 for line in head_lower if any(token in line for token in _FRONT_MATTER_TOKENS))
    relaxed_candidate_counts = {name: 0 for name in _PATTERN_NAMES}
    unsupported_header_variant_hits = 0
    unsupported_header_variant_samples: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        relaxed = _match_episode_header(line, allow_title_patterns=True)
        if relaxed is not None:
            _episode_no, pattern_name = relaxed
            relaxed_candidate_counts[pattern_name] += 1
            continue
        if any(regex.search(line) for regex in _UNSUPPORTED_HEADER_VARIANT_RES):
            unsupported_header_variant_hits += 1
            if len(unsupported_header_variant_samples) < 5:
                unsupported_header_variant_samples.append(line[:_MAX_HEADER_CHARS])
    blank_line_gate_filtered_candidates = sum(
        max(0, int(relaxed_candidate_counts.get(name, 0)) - int(candidate_boundary_counts.get(name, 0)))
        for name in _TITLE_PATTERN_NAMES
    )
    diagnostics: dict[str, object] = {
        "total_candidate_boundaries": total_candidate_boundaries,
        "head_nonempty_lines": len(head),
        "front_matter_hits": front_matter_hits,
        "standalone_number_candidates": int(candidate_boundary_counts.get("standalone_number", 0)),
        "title_pattern_candidates": int(sum(int(candidate_boundary_counts.get(name, 0)) for name in _TITLE_PATTERN_NAMES)),
        "relaxed_title_pattern_candidates": int(sum(int(relaxed_candidate_counts.get(name, 0)) for name in _TITLE_PATTERN_NAMES)),
        "blank_line_gate_filtered_candidates": int(blank_line_gate_filtered_candidates),
        "unsupported_header_variant_hits": int(unsupported_header_variant_hits),
        "unsupported_header_variant_samples": unsupported_header_variant_samples,
    }
    if (
        int(candidate_boundary_counts.get("standalone_number", 0)) >= 2
        and total_candidate_boundaries == int(candidate_boundary_counts.get("standalone_number", 0))
    ):
        diagnostics["reason_code"] = "ambiguous_standalone_numbers"
    elif front_matter_hits >= 2 and total_candidate_boundaries == 0:
        diagnostics["reason_code"] = "front_matter_dominant"
    elif blank_line_gate_filtered_candidates >= 2 and total_candidate_boundaries <= 1:
        diagnostics["reason_code"] = "blank_line_gate_filtered_candidates"
    elif unsupported_header_variant_hits >= 2 and total_candidate_boundaries == 0:
        diagnostics["reason_code"] = "unsupported_header_variant"
    elif total_candidate_boundaries == 0:
        diagnostics["reason_code"] = "no_repeated_markers"
    elif total_candidate_boundaries == 1:
        diagnostics["reason_code"] = "single_detected_marker"
    else:
        diagnostics["reason_code"] = "insufficient_repeated_markers"
    return diagnostics


def _manual_review_reason_code(text: str, candidate_boundary_counts: dict[str, int]) -> str:
    diagnostics = _manual_review_diagnostics(text, candidate_boundary_counts)
    return str(diagnostics.get("reason_code") or "manual_review")


def split_episodes(text: str, *, source_file: str) -> list[Episode]:
    source_content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    episodes, _ = split_episodes_with_stats(
        text,
        source_file=source_file,
        source_id=make_source_id(source_content_sha256),
        source_content_sha256=source_content_sha256,
        source_policy=_source_policy_from_registry(None),
        allow_judge_audit=False,
    )
    return episodes


def split_episodes_with_stats(
    text: str,
    *,
    source_file: str,
    source_id: str,
    source_content_sha256: str,
    source_policy: dict[str, object] | None = None,
    allow_judge_audit: bool = False,
) -> tuple[list[Episode], dict[str, object]]:
    lines = text.splitlines(keepends=True)
    candidate_boundaries: list[tuple[int, int, str, str]] = []
    candidate_boundary_counts = {name: 0 for name in _PATTERN_NAMES}
    registry_policy = source_policy if isinstance(source_policy, dict) else _source_policy_from_registry(None)
    offset = 0
    previous_blank = True
    for line in lines:
        line_text = line.rstrip("\r\n")
        matched = _match_episode_header(
            line_text,
            allow_title_patterns=previous_blank or offset == 0,
        )
        if matched is not None:
            episode_no, pattern_name = matched
            candidate_boundaries.append((offset, episode_no, line_text, pattern_name))
            candidate_boundary_counts[pattern_name] += 1
        offset += len(line)
        previous_blank = not bool(line_text.strip())

    policy = _resolve_effective_source_policy(
        registry_policy=registry_policy,
        candidate_boundary_counts=candidate_boundary_counts,
    )
    judge_settings = load_config()
    if (
        allow_judge_audit
        and str(policy.get("policy_decision_source") or "") == "profile_auto"
        and float(policy.get("policy_confidence") or 0.0) < float(judge_settings.test_judge_min_confidence)
        and bool(judge_settings.enable_test_judge_local_nli or judge_settings.enable_test_judge_remote_api)
    ):
        judged = judge_source_policy(
            source_id=source_id,
            content_sha256=source_content_sha256,
            candidate_boundary_counts=candidate_boundary_counts,
            content_length_stats={
                "text_chars": len(text),
            },
            candidate_line_samples=_candidate_line_samples(candidate_boundaries),
            settings=judge_settings,
        )
        judged_patterns = [
            str(item) for item in (judged.get("accepted_pattern_family") or []) if isinstance(item, str)
        ]
        if judged_patterns and any(int(candidate_boundary_counts.get(name, 0)) > 0 for name in judged_patterns):
            policy = {
                "segmentation_policy": str(judged.get("segmentation_policy") or "manual_review"),
                "allowed_patterns": judged_patterns,
                "policy_decision_source": "judge_audit",
                "policy_confidence": float(judged.get("confidence") or 0.0),
                "reason": str(judged.get("reason") or ""),
                "judge_backend": str(judged.get("judge_backend") or ""),
                "judge_requested_backend": str(judged.get("judge_requested_backend") or ""),
                "judge_effective_backend": str(judged.get("judge_effective_backend") or ""),
                "judge_model_id": str(judged.get("judge_model_id") or ""),
                "judge_prompt_version": str(judged.get("judge_prompt_version") or ""),
                "judge_fallback_used": bool(judged.get("judge_fallback_used", False)),
                "judge_input_hash": str(judged.get("judge_input_hash") or ""),
            }
        else:
            policy = {
                "segmentation_policy": "manual_review",
                "allowed_patterns": [],
                "policy_decision_source": "judge_audit",
                "policy_confidence": float(judged.get("confidence") or 0.0),
                "reason": "judge_selected_unsupported_or_empty_family",
                "judge_backend": str(judged.get("judge_backend") or ""),
                "judge_requested_backend": str(judged.get("judge_requested_backend") or ""),
                "judge_effective_backend": str(judged.get("judge_effective_backend") or ""),
                "judge_model_id": str(judged.get("judge_model_id") or ""),
                "judge_prompt_version": str(judged.get("judge_prompt_version") or ""),
                "judge_fallback_used": bool(judged.get("judge_fallback_used", False)),
                "judge_input_hash": str(judged.get("judge_input_hash") or ""),
            }
    allowed_patterns = {
        str(item) for item in (policy.get("allowed_patterns") or []) if isinstance(item, str)
    }
    if not allowed_patterns:
        allowed_patterns = _select_boundary_patterns(candidate_boundary_counts)
    boundaries = [item for item in candidate_boundaries if item[3] in allowed_patterns]
    boundary_counts = {name: 0 for name in _PATTERN_NAMES}
    for _offset, _episode_no, _header, pattern_name in boundaries:
        boundary_counts[pattern_name] += 1

    if len(boundaries) < 2:
        episodes: list[Episode] = []
        start = 0
        idx = 1
        while start < len(text):
            end = min(len(text), start + _FALLBACK_CHUNK_SIZE)
            episodes.append(
                Episode(
                    source_file=source_file,
                    source_id=source_id,
                    source_content_sha256=source_content_sha256,
                    episode_no=idx,
                    header=f"episode-{idx}",
                    content=text[start:end].strip(),
                    segmentation_mode="fallback_chunk",
                    boundary_pattern=None,
                )
            )
            idx += 1
            start = end
        filtered = [ep for ep in episodes if ep.content]
        return filtered, _episode_stats(
            source_id=source_id,
            source_content_sha256=source_content_sha256,
            episodes=filtered,
            boundary_counts=boundary_counts,
            candidate_boundary_counts=candidate_boundary_counts,
            source_policy=policy,
            split_strategy="fallback_chunk",
            fallback_used=True,
        )

    episodes: list[Episode] = []
    for idx, (start, number, header, pattern_name) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(text)
        content = text[start:end].strip()
        if not content:
            continue
        episodes.append(
            Episode(
                source_file=source_file,
                source_id=source_id,
                source_content_sha256=source_content_sha256,
                episode_no=number,
                header=header,
                content=content,
                segmentation_mode="header_boundary",
                boundary_pattern=pattern_name,
            )
        )
    return episodes, _episode_stats(
        source_id=source_id,
        source_content_sha256=source_content_sha256,
        episodes=episodes,
        boundary_counts=boundary_counts,
        candidate_boundary_counts=candidate_boundary_counts,
        source_policy=policy,
        split_strategy="header_boundary",
        fallback_used=False,
    )


def _episode_stats(
    *,
    source_id: str,
    source_content_sha256: str,
    episodes: list[Episode],
    boundary_counts: dict[str, int],
    candidate_boundary_counts: dict[str, int],
    source_policy: dict[str, object],
    split_strategy: str,
    fallback_used: bool,
) -> dict[str, object]:
    lengths = [len(episode.content) for episode in episodes]
    if lengths:
        content_length_stats = {
            "min_chars": min(lengths),
            "median_chars": int(median(lengths)),
            "max_chars": max(lengths),
        }
    else:
        content_length_stats = {
            "min_chars": 0,
            "median_chars": 0,
            "max_chars": 0,
        }
    return {
        "source_id": source_id,
        "source_content_sha256": source_content_sha256,
        "source_segmentation_policy": str(source_policy.get("segmentation_policy") or "auto"),
        "selected_pattern_family": list(source_policy.get("allowed_patterns") or []),
        "policy_decision_source": str(source_policy.get("policy_decision_source") or "profile_auto"),
        "policy_confidence": float(source_policy.get("policy_confidence") or 0.0),
        "policy_reason": str(source_policy.get("reason") or ""),
        "judge_backend": str(source_policy.get("judge_backend") or ""),
        "judge_requested_backend": str(source_policy.get("judge_requested_backend") or ""),
        "judge_effective_backend": str(source_policy.get("judge_effective_backend") or ""),
        "judge_model_id": str(source_policy.get("judge_model_id") or ""),
        "judge_prompt_version": str(source_policy.get("judge_prompt_version") or ""),
        "judge_fallback_used": bool(source_policy.get("judge_fallback_used", False)),
        "judge_input_hash": str(source_policy.get("judge_input_hash") or ""),
        "split_strategy": split_strategy,
        "fallback_used": fallback_used,
        "candidate_boundary_counts": {
            **{name: int(candidate_boundary_counts.get(name, 0)) for name in _PATTERN_NAMES},
            "total": int(sum(int(candidate_boundary_counts.get(name, 0)) for name in _PATTERN_NAMES)),
        },
        "boundary_counts": {
            **{name: int(boundary_counts.get(name, 0)) for name in _PATTERN_NAMES},
            "total": int(sum(int(boundary_counts.get(name, 0)) for name in _PATTERN_NAMES)),
        },
        "content_length_stats": content_length_stats,
    }


def write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handle:
        for item in items:
            file_handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def uniform_sample(items: list[Episode], count: int) -> list[Episode]:
    if not items:
        return []
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    sampled: list[Episode] = []
    for idx in range(count):
        picked = min(len(items) - 1, int(math.floor(idx * step)))
        sampled.append(items[picked])
    return sampled


def shuffled_order(items: list[Episode], *, seed: int) -> list[Episode]:
    ordered = list(items)
    rng = random.Random(seed)
    rng.shuffle(ordered)
    return ordered


def round_robin_sample(items: list[Episode], count: int, *, seed: int) -> list[Episode]:
    if not items:
        return []
    if len(items) <= count:
        return list(items)

    grouped: dict[str, list[Episode]] = {}
    for episode in items:
        grouped.setdefault(episode.source_id, []).append(episode)

    source_order = sorted(grouped.keys())
    if source_order:
        offset = seed % len(source_order)
        source_order = source_order[offset:] + source_order[:offset]

    positions = {source: 0 for source in source_order}
    sampled: list[Episode] = []
    while len(sampled) < count:
        progressed = False
        for source in source_order:
            position = positions[source]
            pool = grouped[source]
            if position >= len(pool):
                continue
            sampled.append(pool[position])
            positions[source] = position + 1
            progressed = True
            if len(sampled) >= count:
                break
        if not progressed:
            break
    return sampled


def inject_conflict_text(base: str, kind: str) -> str:
    templates = {
        "age": "주인공의 나이는 50세였다.",
        "job": "주인공은 9서클 마법사였다.",
        "talent": "주인공은 천재였다.",
        "time": "사건은 1999년 1월 1일에 발생했다.",
        "affiliation": "주인공의 소속은 황실 기사단이었다.",
        "relation": "주인공과 A의 관계는 원수였다.",
        "death": "주인공은 이미 사망했다.",
        "place": "장소: 북부 성채",
    }
    statement = templates.get(kind, templates["age"])
    return base.rstrip() + "\n\n[INJECT]\n" + statement + "\n"


def to_record(
    dataset: str,
    episode: Episode,
    *,
    content: str,
    injected_kind: str | None = None,
    inject_strategy: str | None = None,
    inject_case_id: str | None = None,
    inject_target_scope: str | None = None,
    inject_expected_primary_signal: str | None = None,
    inject_expected_core_verdict: str | None = None,
    inject_quality_label: str | None = None,
    inject_judge_confidence: float | None = None,
    inject_judge_backend: str | None = None,
    judge_requested_backend: str | None = None,
    judge_effective_backend: str | None = None,
    judge_model_id: str | None = None,
    judge_prompt_version: str | None = None,
    judge_fallback_used: bool | None = None,
    judge_input_hash: str | None = None,
) -> dict:
    corroboration_meta = summarize_consistency_corroboration_policy(episode.content)
    return {
        "dataset": dataset,
        "source_id": episode.source_id,
        "source_content_sha256": episode.source_content_sha256,
        "episode_no": episode.episode_no,
        "header": episode.header,
        "source_segmentation_mode": episode.segmentation_mode,
        "source_boundary_header": episode.header if episode.boundary_pattern is not None else None,
        "source_boundary_pattern": episode.boundary_pattern,
        "content": content,
        "injected_kind": injected_kind,
        "inject_strategy": inject_strategy,
        "inject_case_id": inject_case_id,
        "inject_target_scope": inject_target_scope,
        "inject_expected_primary_signal": inject_expected_primary_signal,
        "inject_expected_core_verdict": inject_expected_core_verdict,
        "inject_subject_text": "주인공" if injected_kind is not None else None,
        "inject_expected_signal": "conflict_signal_expected" if injected_kind is not None else "control_no_inject",
        "inject_quality_label": inject_quality_label,
        "inject_judge_confidence": inject_judge_confidence,
        "inject_judge_backend": inject_judge_backend,
        "judge_requested_backend": judge_requested_backend,
        "judge_effective_backend": judge_effective_backend,
        "judge_model_id": judge_model_id,
        "judge_prompt_version": judge_prompt_version,
        "judge_fallback_used": judge_fallback_used,
        "judge_input_hash": judge_input_hash,
        "consistency_corroboration_policy": str(corroboration_meta.get("policy") or "default"),
        "consistency_corroboration_reason": str(corroboration_meta.get("reason") or ""),
        "explicit_profile_block_line_count": int(corroboration_meta.get("explicit_profile_block_line_count") or 0),
        "explicit_profile_distinct_signal_count": int(
            corroboration_meta.get("explicit_profile_distinct_signal_count") or 0
        ),
        "explicit_profile_signal_counts": dict(corroboration_meta.get("explicit_profile_signal_counts") or {}),
    }


def snapshot_hash(input_files: list[dict]) -> str:
    payload = json.dumps(input_files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _distinct_source_order(records: list[dict]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for record in records:
        source_id = str(record.get("source_id") or "")
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        ordered.append(source_id)
    return ordered


def dataset_stats(path: Path, records: list[dict], *, sampling_strategy: str) -> dict:
    source_counter = Counter(str(record.get("source_id") or "") for record in records)
    corroboration_counter = Counter(str(record.get("consistency_corroboration_policy") or "") for record in records)
    top_distribution = [
        {"source_id": source_id, "count": count}
        for source_id, count in source_counter.most_common(10)
    ]
    return {
        "path": str(path),
        "count": len(records),
        "unique_source_files": len(source_counter),
        "top_source_distribution": top_distribution,
        "sampling_strategy": sampling_strategy,
        "source_order": _distinct_source_order(records),
        "dataset_generation_version": _DATASET_GENERATION_VERSION,
        "consistency_corroboration_policy_counts": {
            key: int(value) for key, value in corroboration_counter.items() if key
        },
        "local_profile_only_record_count": int(corroboration_counter.get("local_profile_only", 0)),
        "manual_review_only": bool(records) and all(
            str(record.get("source_segmentation_mode") or "") == "fallback_chunk" for record in records
        ),
    }


def add_dataset(
    summary: dict[str, object],
    dataset_name: str,
    out_path: Path,
    records: list[dict],
    *,
    sampling_strategy: str,
) -> None:
    write_jsonl(out_path, records)
    datasets = summary["datasets"]
    assert isinstance(datasets, dict)
    datasets[dataset_name] = dataset_stats(out_path, records, sampling_strategy=sampling_strategy)


def _maybe_judge_inject_record(
    *,
    episode: Episode,
    original_content: str,
    injected_statement: str,
    injected_kind: str,
) -> dict[str, object] | None:
    settings = load_config()
    if not (settings.enable_test_judge_local_nli or settings.enable_test_judge_remote_api):
        return None
    judged = judge_inject_quality(
        original_excerpt=original_content,
        injected_statement=injected_statement,
        injected_kind=injected_kind,
        source_metadata={
            "source_id": episode.source_id,
            "source_boundary_pattern": episode.boundary_pattern,
        },
        settings=settings,
    )
    return {
        "inject_quality_label": str(judged.get("inject_quality_label") or ""),
        "judge_confidence": float(judged.get("judge_confidence") or 0.0),
        "judge_backend": str(judged.get("judge_backend") or ""),
        "judge_requested_backend": str(judged.get("judge_requested_backend") or ""),
        "judge_effective_backend": str(judged.get("judge_effective_backend") or ""),
        "judge_model_id": str(judged.get("judge_model_id") or ""),
        "judge_prompt_version": str(judged.get("judge_prompt_version") or ""),
        "judge_fallback_used": bool(judged.get("judge_fallback_used", False)),
        "judge_input_hash": str(judged.get("judge_input_hash") or ""),
    }


def _inject_target_scope(kind: str) -> str:
    if kind in {"time", "place"}:
        return "global_slot"
    return "subject_slot"


def _inject_expected_primary_signal(kind: str) -> str:
    if kind in {"time", "place"}:
        return "explicit_slot_conflict"
    return "ambiguous_or_contextless"


def _inject_expected_core_verdict(kind: str) -> str:
    if kind in {"time", "place"}:
        return "UNKNOWN_OR_VIOLATE"
    return "UNSPECIFIED"


def _inject_case_id(episode: Episode, kind: str) -> str:
    raw = f"{episode.source_id}:{episode.episode_no}:{kind}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"INJ-{digest}"


def _is_structured_inject_case(kind: str, original_content: str, injected_statement: str) -> bool:
    if kind not in {"time", "place"}:
        return False
    text = original_content or ""
    if kind == "time":
        return any(token in text for token in ("년", "월", "일", "시간", "시점", "날짜", ":"))
    if kind == "place":
        return any(token in text for token in ("장소", "위치", "도시", "궁", "성", "마을"))
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Build benchmark datasets from long novel text files.")
    parser.add_argument("--input-dir", default="test_files", help="Directory containing source txt files")
    parser.add_argument("--output-dir", default="verify/datasets", help="Output directory")
    parser.add_argument("--inject-sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--diversity-profile", choices=("basic", "max"), default="max")
    parser.add_argument(
        "--enable-judge-audit",
        action="store_true",
        help="Allow test-only judge metadata to be written into generated datasets.",
    )
    parser.add_argument(
        "--max-fallback-episode-share",
        type=float,
        default=None,
        help="Optional fail-fast threshold for fallback_chunk episode share (0.0-1.0).",
    )
    parser.add_argument(
        "--max-manual-review-sources",
        type=int,
        default=None,
        help="Optional fail-fast threshold for manual-review-only source count.",
    )
    parser.add_argument(
        "--max-undersized-sources",
        type=int,
        default=None,
        help="Optional fail-fast threshold for sources with undersized extracted segments.",
    )
    parser.add_argument(
        "--max-oversized-sources",
        type=int,
        default=None,
        help="Optional fail-fast threshold for sources with oversized extracted segments.",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    _guard_output_dir_for_judge_audit(output_dir, enable_judge_audit=bool(args.enable_judge_audit))
    files = sorted(input_dir.glob("*.txt"))
    if len(files) < 1:
        raise SystemExit(f"no txt files in {input_dir}")

    file_snapshot: list[dict] = []
    source_policy_registry, source_policy_registry_version = _load_source_policy_registry()
    for src in files:
        stat = src.stat()
        content_sha256 = _sha256_file(src)
        file_snapshot.append(
            {
                "source_id": make_source_id(content_sha256),
                "size_bytes": int(stat.st_size),
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "content_sha256": content_sha256,
            }
        )

    diversity_cuts = [200] if args.diversity_profile == "basic" else [200, 400, 800]
    summary: dict[str, object] = {
        "input_files": [],
        "dataset_generation_version": _DATASET_GENERATION_VERSION,
        "source_policy_registry_version": source_policy_registry_version or _SOURCE_POLICY_REGISTRY_VERSION,
        "source_snapshot_hash": snapshot_hash(file_snapshot),
        "build_input_hash_policy": "sha256(raw_bytes_per_file)",
        "build_options": {
            "seed": args.seed,
            "inject_sample_size": args.inject_sample_size,
            "diversity_profile": args.diversity_profile,
            "fallback_chunk_size": _FALLBACK_CHUNK_SIZE,
            "max_fallback_episode_share": args.max_fallback_episode_share,
            "max_manual_review_sources": args.max_manual_review_sources,
            "max_undersized_sources": args.max_undersized_sources,
            "max_oversized_sources": args.max_oversized_sources,
        },
        "datasets": {},
        "growth_cuts": [50, 100, 200, 400, 800],
        "diversity_cuts": diversity_cuts,
        "segmentation_summary": {
            "files_total": 0,
            "fallback_files": 0,
            "episodes_total": 0,
            "fallback_episodes": 0,
            "fallback_episode_share": 0.0,
            "fallback_source_files": [],
        },
        "segment_quality_summary": {
            "min_segment_chars_warning": _WARN_MIN_SEGMENT_CHARS,
            "max_segment_chars_warning": _WARN_MAX_SEGMENT_CHARS,
            "undersized_source_count": 0,
            "oversized_source_count": 0,
            "undersized_sources": [],
            "oversized_sources": [],
        },
        "composite_source_policy": "exclude_fallback_sources_unless_empty",
        "composite_source_pool": {
            "eligible_source_ids": [],
            "excluded_source_ids": [],
            "eligible_episode_count": 0,
            "excluded_episode_count": 0,
        },
        "manual_review_sources": [],
        "manual_review_sources_path": "verify/datasets/manual_review_sources.json",
        "source_policy_registry_path": str(_SOURCE_POLICY_REGISTRY_PATH.relative_to(Path.cwd())),
        "source_name_lookup_local_path": "verify/datasets/source_name_lookup.local.json",
        "manual_review_source_count": 0,
        "manual_review_reason_counts": {},
        "judge_audit_enabled": bool(args.enable_judge_audit),
        "judge_audit_policy_count": 0,
        "quality_warnings": [],
    }
    source_name_lookup: dict[str, dict[str, str]] = {}

    all_base_episodes: list[Episode] = []
    for src in files:
        text, enc = read_text_auto(src)
        content_sha256 = _sha256_file(src)
        source_id = make_source_id(content_sha256)
        source_policy = _source_policy_from_registry(source_policy_registry.get(content_sha256))
        episodes, segmentation_stats = split_episodes_with_stats(
            text,
            source_file=src.name,
            source_id=source_id,
            source_content_sha256=content_sha256,
            source_policy=source_policy,
            allow_judge_audit=bool(args.enable_judge_audit),
        )
        manual_review_diagnostics = _manual_review_diagnostics(text, segmentation_stats["candidate_boundary_counts"])
        all_base_episodes.extend(episodes)
        source_name_lookup[source_id] = {"file_name": src.name, "content_sha256": content_sha256}

        records = [to_record(src.stem, ep, content=ep.content) for ep in episodes]
        add_dataset(
            summary,
            src.stem,
            output_dir / f"{src.stem}.jsonl",
            records,
            sampling_strategy="source_full",
        )

        stat = src.stat()
        summary["input_files"].append(
            {
                "source_id": source_id,
                "encoding": enc,
                "size_bytes": int(stat.st_size),
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "content_sha256": content_sha256,
                "episodes": len(episodes),
                "source_segmentation_policy": segmentation_stats["source_segmentation_policy"],
                "selected_pattern_family": segmentation_stats["selected_pattern_family"],
                "policy_decision_source": segmentation_stats["policy_decision_source"],
                "policy_confidence": segmentation_stats["policy_confidence"],
                "policy_reason": segmentation_stats["policy_reason"],
                "judge_backend": segmentation_stats["judge_backend"],
                "judge_requested_backend": segmentation_stats["judge_requested_backend"],
                "judge_effective_backend": segmentation_stats["judge_effective_backend"],
                "judge_model_id": segmentation_stats["judge_model_id"],
                "judge_prompt_version": segmentation_stats["judge_prompt_version"],
                "judge_fallback_used": segmentation_stats["judge_fallback_used"],
                "judge_input_hash": segmentation_stats["judge_input_hash"],
                "split_strategy": segmentation_stats["split_strategy"],
                "fallback_used": segmentation_stats["fallback_used"],
                "manual_review_reason_code": _manual_review_reason_code(text, segmentation_stats["candidate_boundary_counts"])
                if bool(segmentation_stats["fallback_used"])
                else None,
                "manual_review_diagnostics": manual_review_diagnostics,
                "candidate_boundary_counts": segmentation_stats["candidate_boundary_counts"],
                "boundary_counts": segmentation_stats["boundary_counts"],
                "content_length_stats": segmentation_stats["content_length_stats"],
                "segment_quality_flags": {
                    "undersized": bool(
                        int((segmentation_stats.get("content_length_stats") or {}).get("min_chars", 0)) > 0
                        and int((segmentation_stats.get("content_length_stats") or {}).get("min_chars", 0))
                        < _WARN_MIN_SEGMENT_CHARS
                    ),
                    "oversized": bool(
                        int((segmentation_stats.get("content_length_stats") or {}).get("max_chars", 0))
                        > _WARN_MAX_SEGMENT_CHARS
                    ),
                },
            }
        )
        segmentation_summary = summary["segmentation_summary"]
        assert isinstance(segmentation_summary, dict)
        segmentation_summary["files_total"] = int(segmentation_summary.get("files_total", 0)) + 1
        segmentation_summary["episodes_total"] = int(segmentation_summary.get("episodes_total", 0)) + len(episodes)
        if str(segmentation_stats.get("policy_decision_source") or "") == "judge_audit":
            summary["judge_audit_policy_count"] = int(summary.get("judge_audit_policy_count", 0)) + 1
        if bool(segmentation_stats["fallback_used"]):
            segmentation_summary["fallback_files"] = int(segmentation_summary.get("fallback_files", 0)) + 1
            segmentation_summary["fallback_episodes"] = int(segmentation_summary.get("fallback_episodes", 0)) + len(episodes)
            fallback_source_files = segmentation_summary.get("fallback_source_files")
            if isinstance(fallback_source_files, list):
                fallback_source_files.append(source_id)

    if not all_base_episodes:
        raise SystemExit(f"no episodes extracted from files in {input_dir}")

    segmentation_summary = summary["segmentation_summary"]
    assert isinstance(segmentation_summary, dict)
    total_episodes = max(1, int(segmentation_summary.get("episodes_total", 0)))
    fallback_episode_share = float(int(segmentation_summary.get("fallback_episodes", 0))) / float(total_episodes)
    segmentation_summary["fallback_episode_share"] = round(fallback_episode_share, 6)
    quality_warnings = summary["quality_warnings"]
    assert isinstance(quality_warnings, list)
    segment_quality_summary = summary["segment_quality_summary"]
    assert isinstance(segment_quality_summary, dict)
    undersized_sources = segment_quality_summary["undersized_sources"]
    oversized_sources = segment_quality_summary["oversized_sources"]
    assert isinstance(undersized_sources, list)
    assert isinstance(oversized_sources, list)
    for item in summary["input_files"]:
        if not isinstance(item, dict):
            continue
        stats = item.get("content_length_stats")
        if not isinstance(stats, dict):
            continue
        source_summary = {
            "source_id": str(item.get("source_id") or ""),
            "min_chars": int(stats.get("min_chars", 0) or 0),
            "median_chars": int(stats.get("median_chars", 0) or 0),
            "max_chars": int(stats.get("max_chars", 0) or 0),
            "source_segmentation_policy": str(item.get("source_segmentation_policy") or ""),
            "split_strategy": str(item.get("split_strategy") or ""),
        }
        if source_summary["min_chars"] > 0 and source_summary["min_chars"] < _WARN_MIN_SEGMENT_CHARS:
            undersized_sources.append(dict(source_summary))
        if source_summary["max_chars"] > _WARN_MAX_SEGMENT_CHARS:
            oversized_sources.append(dict(source_summary))
    segment_quality_summary["undersized_source_count"] = len(undersized_sources)
    segment_quality_summary["oversized_source_count"] = len(oversized_sources)
    if fallback_episode_share > 0.50:
        quality_warnings.append(
            {
                "code": "HIGH_FALLBACK_EPISODE_SHARE",
                "message": "More than half of extracted episodes used fallback chunking.",
                "fallback_episode_share": round(fallback_episode_share, 6),
            }
        )
    if int(segmentation_summary.get("fallback_files", 0)) > 0:
        quality_warnings.append(
            {
                "code": "FALLBACK_SOURCES_PRESENT",
                "message": "Some source files still rely on fallback chunking and need source-specific segmentation review.",
                "fallback_files": int(segmentation_summary.get("fallback_files", 0)),
                "fallback_source_files": list(segmentation_summary.get("fallback_source_files") or []),
            }
        )
    if undersized_sources:
        quality_warnings.append(
            {
                "code": "UNDERSIZED_SEGMENTS_PRESENT",
                "message": "Some source files contain very short extracted segments and may be oversplit.",
                "min_segment_chars_warning": _WARN_MIN_SEGMENT_CHARS,
                "affected_sources": [
                    {
                        "source_id": str(item.get("source_id") or ""),
                        "min_chars": int(item.get("min_chars", 0) or 0),
                        "median_chars": int(item.get("median_chars", 0) or 0),
                        "split_strategy": str(item.get("split_strategy") or ""),
                    }
                    for item in undersized_sources
                ],
            }
        )
    if oversized_sources:
        quality_warnings.append(
            {
                "code": "OVERSIZED_SEGMENTS_PRESENT",
                "message": "Some source files contain very large extracted segments and may be undersplit.",
                "max_segment_chars_warning": _WARN_MAX_SEGMENT_CHARS,
                "affected_sources": [
                    {
                        "source_id": str(item.get("source_id") or ""),
                        "max_chars": int(item.get("max_chars", 0) or 0),
                        "median_chars": int(item.get("median_chars", 0) or 0),
                        "split_strategy": str(item.get("split_strategy") or ""),
                    }
                    for item in oversized_sources
                ],
            }
        )
    quality_warnings.append(
        {
            "code": "GROWTH_DATASET_PREFIX_BIAS",
            "message": "DS-GROWTH datasets are prefix-order samples, not pure scale-only benchmarks.",
            "affected_datasets": [f"DS-GROWTH-{cut}" for cut in (50, 100, 200, 400, 800)],
        }
    )
    quality_warnings.append(
        {
            "code": "GENERIC_APPEND_INJECT_DATASET",
            "message": "Inject datasets use generic append marker statements with a fixed subject placeholder and require cautious interpretation.",
            "affected_datasets": [
                "DS-INJECT-C",
                "DS-CONTROL-D",
                "DS-DIVERSE-INJECT-C",
                "DS-DIVERSE-CONTROL-D",
            ],
        }
    )
    if args.max_fallback_episode_share is not None and fallback_episode_share > float(args.max_fallback_episode_share):
        raise SystemExit(
            "fallback episode share "
            f"{fallback_episode_share:.6f} exceeded threshold {float(args.max_fallback_episode_share):.6f}"
        )

    fallback_source_set = set(segmentation_summary.get("fallback_source_files") or [])
    eligible_episodes = [episode for episode in all_base_episodes if episode.source_id not in fallback_source_set]
    composite_source_pool = summary["composite_source_pool"]
    assert isinstance(composite_source_pool, dict)
    composite_source_pool["eligible_source_ids"] = sorted({episode.source_id for episode in eligible_episodes})
    composite_source_pool["excluded_source_ids"] = sorted(fallback_source_set)
    composite_source_pool["eligible_episode_count"] = len(eligible_episodes)
    composite_source_pool["excluded_episode_count"] = len(all_base_episodes) - len(eligible_episodes)
    if eligible_episodes:
        quality_warnings.append(
            {
                "code": "COMPOSITE_DATASETS_EXCLUDE_FALLBACK_SOURCES",
                "message": "Composite benchmark datasets exclude fallback-split sources by default.",
                "eligible_source_ids": len(composite_source_pool["eligible_source_ids"]),
                "excluded_source_ids": len(composite_source_pool["excluded_source_ids"]),
            }
        )
    else:
        eligible_episodes = list(all_base_episodes)
        composite_source_pool["eligible_source_ids"] = sorted({episode.source_id for episode in eligible_episodes})
        composite_source_pool["eligible_episode_count"] = len(eligible_episodes)
        composite_source_pool["excluded_source_ids"] = []
        composite_source_pool["excluded_episode_count"] = 0
        quality_warnings.append(
            {
                "code": "COMPOSITE_DATASETS_FALLBACK_ONLY_POOL",
                "message": "All sources required fallback chunking, so composite datasets use the full fallback pool.",
                "eligible_source_ids": len(composite_source_pool["eligible_source_ids"]),
            }
        )
    if any(
        isinstance(item, dict) and str(item.get("source_segmentation_policy") or "") == "manual_review"
        for item in summary["input_files"]
    ):
        quality_warnings.append(
            {
                "code": "MANUAL_REVIEW_SOURCE_POLICY",
                "message": "Some sources remain manual-review only due unsupported or ambiguous segmentation structure.",
                "source_ids": sorted(
                    str(item.get("source_id") or "")
                    for item in summary["input_files"]
                    if isinstance(item, dict) and str(item.get("source_segmentation_policy") or "") == "manual_review"
                ),
            }
        )
        manual_review_sources = summary["manual_review_sources"]
        assert isinstance(manual_review_sources, list)
        manual_review_reason_counts = summary["manual_review_reason_counts"]
        assert isinstance(manual_review_reason_counts, dict)
        for item in summary["input_files"]:
            if not isinstance(item, dict):
                continue
            if str(item.get("source_segmentation_policy") or "") != "manual_review":
                continue
            reason_code = str(item.get("manual_review_reason_code") or "manual_review")
            manual_review_reason_counts[reason_code] = int(manual_review_reason_counts.get(reason_code, 0)) + 1
            manual_review_sources.append(
                {
                    "source_id": str(item.get("source_id") or ""),
                    "content_sha256": str(item.get("content_sha256") or ""),
                    "source_segmentation_policy": item.get("source_segmentation_policy"),
                    "selected_pattern_family": item.get("selected_pattern_family"),
                    "policy_decision_source": item.get("policy_decision_source"),
                    "policy_confidence": item.get("policy_confidence"),
                    "policy_reason": item.get("policy_reason"),
                    "manual_review_reason_code": item.get("manual_review_reason_code"),
                    "split_strategy": item.get("split_strategy"),
                    "fallback_used": item.get("fallback_used"),
                    "episodes": item.get("episodes"),
                    "candidate_boundary_counts": item.get("candidate_boundary_counts"),
                    "boundary_counts": item.get("boundary_counts"),
                    "content_length_stats": item.get("content_length_stats"),
                    "manual_review_diagnostics": item.get("manual_review_diagnostics"),
                    "reason": item.get("manual_review_reason_code") or "manual_review",
                }
            )
        summary["manual_review_source_count"] = len(manual_review_sources)
    manual_review_source_count = int(summary.get("manual_review_source_count", 0))
    if args.max_manual_review_sources is not None and manual_review_source_count > int(args.max_manual_review_sources):
        raise SystemExit(
            "manual review source count "
            f"{manual_review_source_count} exceeded threshold {int(args.max_manual_review_sources)}"
        )
    if args.max_undersized_sources is not None and len(undersized_sources) > int(args.max_undersized_sources):
        raise SystemExit(
            "undersized source count "
            f"{len(undersized_sources)} exceeded threshold {int(args.max_undersized_sources)}"
        )
    if args.max_oversized_sources is not None and len(oversized_sources) > int(args.max_oversized_sources):
        raise SystemExit(
            "oversized source count "
            f"{len(oversized_sources)} exceeded threshold {int(args.max_oversized_sources)}"
        )

    sampled = uniform_sample(eligible_episodes, args.inject_sample_size)
    inject_kinds = ["age", "job", "talent", "time", "affiliation", "relation", "death", "place"]
    inject_records: list[dict] = []
    control_records: list[dict] = []
    clear_inject_records: list[dict] = []
    for idx, episode in enumerate(sampled):
        kind = inject_kinds[idx % len(inject_kinds)]
        injected_content = inject_conflict_text(episode.content, kind)
        injected_statement = injected_content.split("[INJECT]\n", 1)[1].strip() if "[INJECT]\n" in injected_content else ""
        inject_case_id = _inject_case_id(episode, kind)
        inject_target_scope = _inject_target_scope(kind)
        inject_expected_primary_signal = _inject_expected_primary_signal(kind)
        inject_expected_core_verdict = _inject_expected_core_verdict(kind)
        inject_judge_meta = (
            _maybe_judge_inject_record(
                episode=episode,
                original_content=episode.content,
                injected_statement=injected_statement,
                injected_kind=kind,
            )
            if args.enable_judge_audit
            else None
        )
        inject_quality_label = str((inject_judge_meta or {}).get("inject_quality_label") or "")
        inject_judge_confidence = (
            float((inject_judge_meta or {}).get("judge_confidence") or 0.0) if inject_judge_meta is not None else None
        )
        inject_judge_backend = str((inject_judge_meta or {}).get("judge_backend") or "")
        inject_records.append(
            to_record(
                "DS-INJECT-C",
                episode,
                content=injected_content,
                injected_kind=kind,
                inject_strategy="append_marker_statement",
                inject_case_id=inject_case_id,
                inject_target_scope=inject_target_scope,
                inject_expected_primary_signal=inject_expected_primary_signal,
                inject_expected_core_verdict=inject_expected_core_verdict,
                inject_quality_label=inject_quality_label,
                inject_judge_confidence=inject_judge_confidence,
                inject_judge_backend=inject_judge_backend,
                judge_requested_backend=str((inject_judge_meta or {}).get("judge_requested_backend") or ""),
                judge_effective_backend=str((inject_judge_meta or {}).get("judge_effective_backend") or ""),
                judge_model_id=str((inject_judge_meta or {}).get("judge_model_id") or ""),
                judge_prompt_version=str((inject_judge_meta or {}).get("judge_prompt_version") or ""),
                judge_fallback_used=bool((inject_judge_meta or {}).get("judge_fallback_used", False))
                if inject_judge_meta is not None
                else None,
                judge_input_hash=str((inject_judge_meta or {}).get("judge_input_hash") or ""),
            )
        )
        if _is_structured_inject_case(kind, episode.content, injected_statement):
            clear_inject_records.append(
                to_record(
                    "DS-INJECT-C-STRUCTURED",
                    episode,
                    content=injected_content,
                    injected_kind=kind,
                    inject_strategy="append_marker_statement",
                    inject_case_id=inject_case_id,
                    inject_target_scope=inject_target_scope,
                    inject_expected_primary_signal=inject_expected_primary_signal,
                    inject_expected_core_verdict=inject_expected_core_verdict,
                    inject_quality_label=inject_quality_label,
                    inject_judge_confidence=inject_judge_confidence,
                    inject_judge_backend=inject_judge_backend,
                    judge_requested_backend=str((inject_judge_meta or {}).get("judge_requested_backend") or ""),
                    judge_effective_backend=str((inject_judge_meta or {}).get("judge_effective_backend") or ""),
                    judge_model_id=str((inject_judge_meta or {}).get("judge_model_id") or ""),
                    judge_prompt_version=str((inject_judge_meta or {}).get("judge_prompt_version") or ""),
                    judge_fallback_used=bool((inject_judge_meta or {}).get("judge_fallback_used", False))
                    if inject_judge_meta is not None
                    else None,
                    judge_input_hash=str((inject_judge_meta or {}).get("judge_input_hash") or ""),
                )
            )
        control_records.append(
            to_record(
                "DS-CONTROL-D",
                episode,
                content=episode.content,
                injected_kind=None,
                inject_strategy="control_no_inject",
            )
        )
    add_dataset(
        summary,
        "DS-INJECT-C",
        output_dir / "DS-INJECT-C.jsonl",
        inject_records,
        sampling_strategy="uniform_sample_from_eligible_sources_then_append_inject",
    )
    add_dataset(
        summary,
        "DS-CONTROL-D",
        output_dir / "DS-CONTROL-D.jsonl",
        control_records,
        sampling_strategy="uniform_sample_from_eligible_sources_control",
    )
    if clear_inject_records:
        add_dataset(
            summary,
            "DS-INJECT-C-STRUCTURED",
            output_dir / "DS-INJECT-C-STRUCTURED.jsonl",
            clear_inject_records,
            sampling_strategy="uniform_sample_from_eligible_sources_then_structured_conflict_filter",
        )

    growth_order = shuffled_order(eligible_episodes, seed=args.seed)
    for cut in (50, 100, 200, 400, 800):
        cut_records = [to_record(f"DS-GROWTH-{cut}", ep, content=ep.content) for ep in growth_order[:cut]]
        add_dataset(
            summary,
            f"DS-GROWTH-{cut}",
            output_dir / f"DS-GROWTH-{cut}.jsonl",
            cut_records,
            sampling_strategy=f"shuffled_seed_{args.seed}_prefix_{cut}",
        )

    for cut in diversity_cuts:
        diverse_sample = round_robin_sample(eligible_episodes, cut, seed=args.seed)
        diverse_records = [to_record(f"DS-DIVERSE-{cut}", ep, content=ep.content) for ep in diverse_sample]
        add_dataset(
            summary,
            f"DS-DIVERSE-{cut}",
            output_dir / f"DS-DIVERSE-{cut}.jsonl",
            diverse_records,
            sampling_strategy=f"round_robin_seed_{args.seed}_count_{cut}",
        )

    diverse_strict_sample = round_robin_sample(eligible_episodes, args.inject_sample_size, seed=args.seed)
    diverse_inject_records: list[dict] = []
    diverse_control_records: list[dict] = []
    diverse_clear_inject_records: list[dict] = []
    for idx, episode in enumerate(diverse_strict_sample):
        kind = inject_kinds[idx % len(inject_kinds)]
        injected_content = inject_conflict_text(episode.content, kind)
        injected_statement = injected_content.split("[INJECT]\n", 1)[1].strip() if "[INJECT]\n" in injected_content else ""
        inject_case_id = _inject_case_id(episode, kind)
        inject_target_scope = _inject_target_scope(kind)
        inject_expected_primary_signal = _inject_expected_primary_signal(kind)
        inject_expected_core_verdict = _inject_expected_core_verdict(kind)
        inject_judge_meta = (
            _maybe_judge_inject_record(
                episode=episode,
                original_content=episode.content,
                injected_statement=injected_statement,
                injected_kind=kind,
            )
            if args.enable_judge_audit
            else None
        )
        inject_quality_label = str((inject_judge_meta or {}).get("inject_quality_label") or "")
        inject_judge_confidence = (
            float((inject_judge_meta or {}).get("judge_confidence") or 0.0) if inject_judge_meta is not None else None
        )
        inject_judge_backend = str((inject_judge_meta or {}).get("judge_backend") or "")
        diverse_inject_records.append(
            to_record(
                "DS-DIVERSE-INJECT-C",
                episode,
                content=injected_content,
                injected_kind=kind,
                inject_strategy="append_marker_statement",
                inject_case_id=inject_case_id,
                inject_target_scope=inject_target_scope,
                inject_expected_primary_signal=inject_expected_primary_signal,
                inject_expected_core_verdict=inject_expected_core_verdict,
                inject_quality_label=inject_quality_label,
                inject_judge_confidence=inject_judge_confidence,
                inject_judge_backend=inject_judge_backend,
                judge_requested_backend=str((inject_judge_meta or {}).get("judge_requested_backend") or ""),
                judge_effective_backend=str((inject_judge_meta or {}).get("judge_effective_backend") or ""),
                judge_model_id=str((inject_judge_meta or {}).get("judge_model_id") or ""),
                judge_prompt_version=str((inject_judge_meta or {}).get("judge_prompt_version") or ""),
                judge_fallback_used=bool((inject_judge_meta or {}).get("judge_fallback_used", False))
                if inject_judge_meta is not None
                else None,
                judge_input_hash=str((inject_judge_meta or {}).get("judge_input_hash") or ""),
            )
        )
        if _is_structured_inject_case(kind, episode.content, injected_statement):
            diverse_clear_inject_records.append(
                to_record(
                    "DS-DIVERSE-INJECT-C-STRUCTURED",
                    episode,
                    content=injected_content,
                    injected_kind=kind,
                    inject_strategy="append_marker_statement",
                    inject_case_id=inject_case_id,
                    inject_target_scope=inject_target_scope,
                    inject_expected_primary_signal=inject_expected_primary_signal,
                    inject_expected_core_verdict=inject_expected_core_verdict,
                    inject_quality_label=inject_quality_label,
                    inject_judge_confidence=inject_judge_confidence,
                    inject_judge_backend=inject_judge_backend,
                    judge_requested_backend=str((inject_judge_meta or {}).get("judge_requested_backend") or ""),
                    judge_effective_backend=str((inject_judge_meta or {}).get("judge_effective_backend") or ""),
                    judge_model_id=str((inject_judge_meta or {}).get("judge_model_id") or ""),
                    judge_prompt_version=str((inject_judge_meta or {}).get("judge_prompt_version") or ""),
                    judge_fallback_used=bool((inject_judge_meta or {}).get("judge_fallback_used", False))
                    if inject_judge_meta is not None
                    else None,
                    judge_input_hash=str((inject_judge_meta or {}).get("judge_input_hash") or ""),
                )
            )
        diverse_control_records.append(
            to_record(
                "DS-DIVERSE-CONTROL-D",
                episode,
                content=episode.content,
                injected_kind=None,
                inject_strategy="control_no_inject",
            )
        )
    add_dataset(
        summary,
        "DS-DIVERSE-INJECT-C",
        output_dir / "DS-DIVERSE-INJECT-C.jsonl",
        diverse_inject_records,
        sampling_strategy=f"round_robin_seed_{args.seed}_inject_sample",
    )
    add_dataset(
        summary,
        "DS-DIVERSE-CONTROL-D",
        output_dir / "DS-DIVERSE-CONTROL-D.jsonl",
        diverse_control_records,
        sampling_strategy=f"round_robin_seed_{args.seed}_control_sample",
    )
    if diverse_clear_inject_records:
        add_dataset(
            summary,
            "DS-DIVERSE-INJECT-C-STRUCTURED",
            output_dir / "DS-DIVERSE-INJECT-C-STRUCTURED.jsonl",
            diverse_clear_inject_records,
            sampling_strategy=f"round_robin_seed_{args.seed}_inject_structured_filter",
        )

    summary_path = output_dir / "dataset_manifest.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manual_review_path = output_dir / "manual_review_sources.json"
    manual_review_path.write_text(
        json.dumps(summary.get("manual_review_sources") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    source_lookup_path = output_dir / "source_name_lookup.local.json"
    source_lookup_path.write_text(json.dumps(source_name_lookup, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "summary_path": str(summary_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
