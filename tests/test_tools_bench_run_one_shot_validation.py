from __future__ import annotations

import re
from pathlib import Path

import pytest


def _script_text() -> str:
    return Path("tools/bench/run_one_shot_validation.ps1").read_text(encoding="utf-8")


@pytest.mark.unit
def test_one_shot_script_uses_env_override_without_toml_write() -> None:
    script = _script_text()

    assert 'function Set-TestJudgeEnv' in script
    assert 'function Restore-TestJudgeEnv' in script
    assert '$env:NF_ENABLE_TEST_JUDGE_LOCAL_NLI = "true"' in script
    assert '$env:NF_TEST_JUDGE_LOCAL_NLI_MODEL_ID = "nli-lite-v1"' in script
    assert '$env:NF_TEST_JUDGE_MIN_CONFIDENCE = "0.80"' in script
    assert '$env:NF_TEST_JUDGE_TIMEOUT_MS = "3000"' in script
    assert re.search(r"(?m)^\s*Set-Content\b", script) is None
    assert re.search(r"(?m)^\s*Add-Content\b", script) is None
    assert re.search(r"(?m)^\s*Out-File\b", script) is None


@pytest.mark.unit
def test_one_shot_script_uses_expected_failure_helper_for_probe() -> None:
    script = _script_text()

    assert "function Invoke-PythonJsonAllowExpectedFailure" in script
    assert '$failureResult = Invoke-PythonJsonAllowExpectedFailure @(' in script
    assert 'throw "failure probe unexpectedly succeeded"' in script
    assert 'Write-Step "expected failure validated"' in script


@pytest.mark.unit
def test_one_shot_script_requires_live_bench_runtime_guards_before_delegated_steps() -> None:
    script = _script_text()

    assert "function Resolve-LiveBenchGuardState" in script
    assert '"semantic.guards",' in script
    assert '"runs.throughput.semantic.guards"' in script
    assert 'Write-Step "live bench schema/provenance smoke passed"' in script
    assert 'Write-Step "live bench runtime smoke passed"' in script
    assert 'throw "live bench runtime smoke failed (stack reachable but bench failed):' in script
    assert '$liveBenchRuntimePassed = $true' in script
    assert 'datasets.DS-GROWTH-200.local_profile_only_record_count' in script
    assert 'datasets.DS-GROWTH-200.consistency_corroboration_policy_counts' in script
    assert 'Write-Step "dataset corroboration policy counts: local_profile_only=$localProfileCount"' in script
    assert 'Write-Step "Step 6/6 - delegated long runs blocked"' in script
    assert 'Write-Host "Pending after validation:one-shot guard pass:"' in script
    assert '--only-local-profile-only --include-local-profile-only' in script
    assert 'operational-shadow:local-profile-only' in script
    assert '$liveBenchBlockedReason = "front-door unreachable"' in script
    assert 'throw "one-shot delegated readiness blocked: $liveBenchBlockedReason"' in script
