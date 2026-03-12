import re
from typing import Any


_PROFILE_LINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("name", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:이름|name)\s*[:은는]")),
    ("age", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:나이|연령|age)\s*[:은는]")),
    ("affiliation", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:소속|affiliation)\s*[:은는]")),
    ("job", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:직업|클래스|job|class)\s*[:은는]")),
    ("relation", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:관계|relation)\s*[:은는]")),
    ("talent", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:재능|talent)\s*[:은는]")),
    ("death", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:사망|생존|death|alive)\s*[:은는]")),
    ("alias", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:별호|alias)\s*[:은는]")),
    ("origin", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:출신|origin)\s*[:은는]")),
    ("martial", re.compile(r"^\s*(?:[\-\*\u2022]\s*)?(?:무위|경지|등급|rank)\s*[:은는]")),
)
_LOCAL_PROFILE_CORE_KEYS = {"name", "affiliation", "job", "relation", "talent", "alias", "origin", "martial"}
_LOCAL_PROFILE_MIN_LINES = 3
_LOCAL_PROFILE_MIN_DISTINCT = 3


def _matched_profile_key(line: str) -> str:
    for key, pattern in _PROFILE_LINE_PATTERNS:
        if pattern.search(line):
            return key
    return ""


def summarize_consistency_corroboration_policy(text: str) -> dict[str, Any]:
    signal_counts: dict[str, int] = {}
    best_cluster: list[str] = []
    current_cluster: list[str] = []

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key = _matched_profile_key(line)
        if not key:
            if len(current_cluster) > len(best_cluster):
                best_cluster = list(current_cluster)
            current_cluster = []
            continue
        signal_counts[key] = int(signal_counts.get(key, 0)) + 1
        current_cluster.append(key)

    if len(current_cluster) > len(best_cluster):
        best_cluster = list(current_cluster)

    cluster_keys = set(best_cluster)
    cluster_line_count = len(best_cluster)
    cluster_distinct_count = len(cluster_keys)
    local_profile_only = (
        cluster_line_count >= _LOCAL_PROFILE_MIN_LINES
        and cluster_distinct_count >= _LOCAL_PROFILE_MIN_DISTINCT
        and bool(cluster_keys.intersection(_LOCAL_PROFILE_CORE_KEYS))
    )
    reason = ""
    if local_profile_only:
        reason = f"explicit_profile_block:{cluster_line_count}lines/{cluster_distinct_count}signals"
    return {
        "policy": "local_profile_only" if local_profile_only else "default",
        "reason": reason,
        "explicit_profile_block_line_count": cluster_line_count,
        "explicit_profile_distinct_signal_count": cluster_distinct_count,
        "explicit_profile_signal_counts": signal_counts,
    }


def record_consistency_corroboration_policy(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        return summarize_consistency_corroboration_policy("")
    policy = str(record.get("consistency_corroboration_policy") or "")
    if not policy:
        return summarize_consistency_corroboration_policy(str(record.get("content") or ""))
    reason = str(record.get("consistency_corroboration_reason") or "")
    try:
        block_line_count = int(record.get("explicit_profile_block_line_count") or 0)
    except (TypeError, ValueError):
        block_line_count = 0
    try:
        distinct_signal_count = int(record.get("explicit_profile_distinct_signal_count") or 0)
    except (TypeError, ValueError):
        distinct_signal_count = 0
    signal_counts_raw = record.get("explicit_profile_signal_counts")
    signal_counts = (
        {str(key): int(value) for key, value in signal_counts_raw.items()}
        if isinstance(signal_counts_raw, dict)
        else {}
    )
    return {
        "policy": policy,
        "reason": reason,
        "explicit_profile_block_line_count": block_line_count,
        "explicit_profile_distinct_signal_count": distinct_signal_count,
        "explicit_profile_signal_counts": signal_counts,
    }
