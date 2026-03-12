import importlib
import sys
from pathlib import Path

import pytest


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        return importlib.import_module("source_policy_profile")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


@pytest.mark.unit
def test_summarize_consistency_corroboration_policy_detects_local_profile_block() -> None:
    mod = _import_module()

    summary = mod.summarize_consistency_corroboration_policy(
        "이름: 금철생\n\n나이: 스물 다섯\n\n소속: 사도련 백전귀(百戰鬼)\n\n별호: 규백도귀\n\n무위: 절정"
    )

    assert summary["policy"] == "local_profile_only"
    assert int(summary["explicit_profile_block_line_count"]) >= 5
    assert int(summary["explicit_profile_distinct_signal_count"]) >= 4
    assert int(summary["explicit_profile_signal_counts"]["affiliation"]) >= 1


@pytest.mark.unit
def test_summarize_consistency_corroboration_policy_keeps_default_for_narrative_text() -> None:
    mod = _import_module()

    summary = mod.summarize_consistency_corroboration_policy("무림맹은 갈라지고, 사도련은 들썩거린다.")

    assert summary["policy"] == "default"
    assert int(summary["explicit_profile_block_line_count"]) == 0
