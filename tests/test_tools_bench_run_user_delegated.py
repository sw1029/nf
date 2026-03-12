from __future__ import annotations

from pathlib import Path

import pytest


def _script_text() -> str:
    return Path("tools/bench/run_user_delegated.ps1").read_text(encoding="utf-8")


@pytest.mark.unit
def test_run_user_delegated_invokes_one_shot_runtime_gate_before_operational_phase() -> None:
    script = _script_text()

    assert 'Invoke-ScenarioStep -Title "One-shot validation runtime gate"' in script
    assert '"tools/bench/run_one_shot_validation.ps1"' in script
    assert '"-SkipFailureProbe"' in script
    assert '"-BenchOutputDir", $OutputDir' in script


@pytest.mark.unit
def test_run_user_delegated_includes_operational_graph_verification_benchmark_and_probe() -> None:
    script = _script_text()

    assert 'BenchLabel = "operational-graph-main:DS-200"' in script
    assert '"Operational graph verification benchmark DS-200 (graph-on)"' in script
    assert '"Operational graph grouping probe (DS-200 graph-on)"' in script
    assert '"tools/bench/check_graphrag_applied.py"' in script
    assert '"--bootstrap-grouping-if-empty"' in script
    assert '"--require-applied"' in script


@pytest.mark.unit
def test_run_user_delegated_passes_optional_shadow_lane_artifact_to_gate_report() -> None:
    script = _script_text()

    assert 'Get-LatestPipelineArtifactByLabelPrefix -DirPath $OutputDir -LabelPrefix "operational-shadow:"' in script
    assert '"--pipeline-shadow", $latestShadowPipeline.FullName' in script


@pytest.mark.unit
def test_run_user_delegated_tags_canonical_operational_artifacts_with_explicit_cohort() -> None:
    script = _script_text()

    assert '$script:CanonicalOperationalArtifactCohort = "operational_closeout"' in script
    assert '"--artifact-cohort", $script:CanonicalOperationalArtifactCohort' in script
