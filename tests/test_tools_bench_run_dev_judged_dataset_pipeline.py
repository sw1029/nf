from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from modules.nf_shared.config import Settings


def _import_module():
    bench_dir = Path("tools/bench").resolve()
    sys.path.insert(0, str(bench_dir))
    try:
        sys.modules.pop("run_dev_judged_dataset_pipeline", None)
        return importlib.import_module("run_dev_judged_dataset_pipeline")
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


@pytest.mark.unit
def test_run_dev_judged_dataset_pipeline_requires_developer_mode(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_root = tmp_path / "judge_runs"
    input_dir.mkdir()
    (input_dir / "alpha.txt").write_text("[1] alpha\n본문\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "tools/bench/run_dev_judged_dataset_pipeline.py",
            "--input-dir",
            str(input_dir),
            "--output-root",
            str(output_root),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "--developer-mode is required" in proc.stderr or "--developer-mode is required" in proc.stdout


@pytest.mark.unit
def test_run_dev_judged_dataset_pipeline_fails_fast_when_real_backend_is_required_but_unavailable(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_root = tmp_path / "judge_runs"
    input_dir.mkdir()
    (input_dir / "alpha.txt").write_text("[1] alpha\n본문\n", encoding="utf-8")

    env = os.environ.copy()
    env["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "false"
    env["NF_ENABLE_TEST_JUDGE_REMOTE_API"] = "false"
    env["NF_MODEL_STORE"] = str(tmp_path / "empty_models")

    proc = subprocess.run(
        [
            sys.executable,
            "tools/bench/run_dev_judged_dataset_pipeline.py",
            "--developer-mode",
            "--input-dir",
            str(input_dir),
            "--output-root",
            str(output_root),
            "--judge-backend",
            "local_nli",
            "--require-real-judge-backend",
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode != 0
    combined = proc.stderr + proc.stdout
    assert "real judge backend is required but unavailable" in combined
    assert "heuristic_only_local_model_missing" in combined


@pytest.mark.unit
def test_run_dev_judged_dataset_pipeline_writes_run_scoped_outputs(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_root = tmp_path / "judge_runs"
    input_dir.mkdir()
    lines = []
    for idx in range(1, 5):
        lines.append(f"[{idx}] alpha episode {idx}\n")
        lines.append("장소: 북부 성채\n")
        lines.append("관계: 주인공의 동생,\n\n")
    (input_dir / "alpha.txt").write_text("".join(lines), encoding="utf-8")

    env = os.environ.copy()
    env["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "false"
    env["NF_ENABLE_TEST_JUDGE_REMOTE_API"] = "false"

    proc = subprocess.run(
        [
            sys.executable,
            "tools/bench/run_dev_judged_dataset_pipeline.py",
            "--developer-mode",
            "--input-dir",
            str(input_dir),
            "--output-root",
            str(output_root),
            "--inject-sample-size",
            "4",
            "--diversity-profile",
            "basic",
            "--run-id",
            "test-run",
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    payload = json.loads(proc.stdout.strip())
    run_root = Path(payload["run_root"])
    assert run_root == output_root / "test-run"
    assert (run_root / "baseline_snapshot" / "dataset_manifest.json").exists()
    assert (run_root / "judge_run_manifest.json").exists()
    assert (run_root / "source_policy_judgments.jsonl").exists()
    assert (run_root / "inject_quality_judgments.jsonl").exists()
    assert (run_root / "derived_datasets" / "source_policy_applied" / "summary.json").exists()
    assert (run_root / "derived_datasets" / "DS-INJECT-C-TYPED.jsonl").exists()
    assert (run_root / "derived_datasets" / "DS-DIVERSE-INJECT-C-TYPED.jsonl").exists()
    assert (run_root / "derived_datasets" / "typed_inject_usability.jsonl").exists()
    assert (run_root / "comparison" / "dataset_diff_summary.json").exists()
    assert (run_root / "comparison" / "bench_candidate_summary.json").exists()
    assert (run_root / "report.md").exists()

    manifest = json.loads((run_root / "judge_run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["developer_mode"] is True
    assert manifest["canonical_outputs_modified"] is False
    assert str(manifest["baseline_snapshot_path"]).endswith("baseline_snapshot")
    assert manifest["judge_backend_overrides"]["judge_backend"] == "config"
    assert "judge_backend_availability" in manifest
    assert "requested_backend" in manifest["judge_backend_availability"]
    assert "expected_execution_mode" in manifest["judge_backend_availability"]

    summary = json.loads((run_root / "comparison" / "bench_candidate_summary.json").read_text(encoding="utf-8"))
    assert summary["derived_datasets"]["generated_files"]
    assert "source_policy_shadow_apply" in summary
    assert summary["strict_layer3_audit"]["status"] == "no_strict_artifacts"
    assert int(summary["typed_inject"]["DS-INJECT-C-TYPED"]["rows_total"]) == 0
    assert summary["typed_inject"]["DS-INJECT-C-TYPED"]["skipped_reason_counts"]
    report_text = (run_root / "report.md").read_text(encoding="utf-8")
    assert "## Backend Availability" in report_text


@pytest.mark.unit
def test_run_dev_judged_dataset_pipeline_persists_disabled_backend_override_in_manifest(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_root = tmp_path / "judge_runs"
    input_dir.mkdir()
    (input_dir / "alpha.txt").write_text("[1] alpha\n본문\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "tools/bench/run_dev_judged_dataset_pipeline.py",
            "--developer-mode",
            "--input-dir",
            str(input_dir),
            "--output-root",
            str(output_root),
            "--inject-sample-size",
            "1",
            "--diversity-profile",
            "basic",
            "--run-id",
            "test-run-disabled-backend",
            "--judge-backend",
            "disabled",
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(proc.stdout.strip())
    run_root = Path(payload["run_root"])
    manifest = json.loads((run_root / "judge_run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["judge_backend_overrides"]["judge_backend"] == "disabled"
    availability = manifest["judge_backend_availability"]
    assert availability["requested_backend"] == "disabled"
    assert availability["expected_execution_mode"] == "disabled"


@pytest.mark.unit
def test_judge_backend_availability_marks_present_but_unusable_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()
    monkeypatch.setattr(
        mod,
        "load_config",
        lambda: Settings(enable_test_judge_local_nli=True, test_judge_local_nli_model_id="nli-lite-v1"),
    )
    monkeypatch.setattr(
        mod,
        "describe_model",
        lambda _model_id: {
            "path": Path("data/models/nli-lite-v1"),
            "present": True,
            "manifest_backend": "",
            "runtime_ready": False,
            "reason": "manifest_missing_or_unsupported_backend",
        },
    )

    availability = mod._judge_backend_availability()

    assert availability["requested_backend"] == "local_nli"
    assert availability["local_model_present"] is True
    assert availability["local_model_runtime_ready"] is False
    assert availability["expected_execution_mode"] == "heuristic_only_local_model_unusable"


@pytest.mark.unit
def test_build_source_policy_shadow_apply_generates_run_scoped_source_variant(tmp_path: Path) -> None:
    mod = _import_module()
    input_dir = tmp_path / "input"
    derived_dir = tmp_path / "derived"
    input_dir.mkdir()
    source_text = (
        ("1\n\n첫 번째 에피소드 본문이 충분히 길어서 검증을 통과한다. " * 4)
        + "\n\n"
        + ("2\n\n둘째 에피소드 본문도 충분히 길다. " * 4)
        + "\n\n"
        + ("3\n\n셋째 에피소드 본문도 충분히 길다. " * 4)
    )
    (input_dir / "alpha.txt").write_text(source_text, encoding="utf-8")

    source_rows = [
        {
            "source_id": "SRC-alpha",
            "content_sha256": "a" * 64,
            "source_file": "alpha.txt",
            "audit_status": "judged",
            "segmentation_policy": "source_override_pattern",
            "accepted_pattern_family": ["standalone_number"],
            "confidence": 0.95,
            "reason": "judge_selected:standalone_number_family",
            "candidate_boundary_counts": {"standalone_number": 3},
            "content_length_stats": {"front_matter_hits": 0, "head_nonempty_lines": 3},
        }
    ]

    updated_rows, summary, generated_files = mod._build_source_policy_shadow_apply(
        input_dir=input_dir,
        source_rows=source_rows,
        derived_datasets_dir=derived_dir,
    )

    assert updated_rows[0]["shadow_apply_status"] == "applied"
    assert int(summary["applied_rows"]) == 1
    assert generated_files
    out_path = derived_dir / "source_policy_applied" / "SRC-alpha.jsonl"
    assert out_path.exists()


@pytest.mark.unit
def test_build_source_policy_shadow_apply_skips_validation_failure_when_candidate_family_missing(tmp_path: Path) -> None:
    mod = _import_module()
    input_dir = tmp_path / "input"
    derived_dir = tmp_path / "derived"
    input_dir.mkdir()
    source_text = (
        ("1\n\n첫 번째 에피소드 본문이 충분히 길어서 검증을 통과한다. " * 4)
        + "\n\n"
        + ("2\n\n둘째 에피소드 본문도 충분히 길다. " * 4)
        + "\n\n"
        + ("3\n\n셋째 에피소드 본문도 충분히 길다. " * 4)
    )
    (input_dir / "alpha.txt").write_text(source_text, encoding="utf-8")

    source_rows = [
        {
            "source_id": "SRC-alpha",
            "content_sha256": "a" * 64,
            "source_file": "alpha.txt",
            "audit_status": "judged",
            "segmentation_policy": "source_override_pattern",
            "accepted_pattern_family": ["episode_hwa"],
            "confidence": 0.95,
            "reason": "judge_selected:episode_hwa_family",
            "candidate_boundary_counts": {"standalone_number": 3, "episode_hwa": 0},
            "content_length_stats": {"front_matter_hits": 0, "head_nonempty_lines": 3},
        }
    ]

    updated_rows, summary, _generated_files = mod._build_source_policy_shadow_apply(
        input_dir=input_dir,
        source_rows=source_rows,
        derived_datasets_dir=derived_dir,
    )

    assert updated_rows[0]["shadow_apply_status"] == "skipped_validation_failed"
    assert int(summary["validation_failed_rows"]) == 1
    assert not (derived_dir / "source_policy_applied" / "SRC-alpha.jsonl").exists()


@pytest.mark.unit
def test_build_source_policy_shadow_apply_accepts_family_when_any_member_is_present(tmp_path: Path) -> None:
    mod = _import_module()
    input_dir = tmp_path / "input"
    derived_dir = tmp_path / "derived"
    input_dir.mkdir()
    source_text = (
        ("1화\n\n첫 번째 에피소드 본문이 충분히 길어서 검증을 통과한다. " * 4)
        + "\n\n"
        + ("2화\n\n둘째 에피소드 본문도 충분히 길다. " * 4)
        + "\n\n"
        + ("3화\n\n셋째 에피소드 본문도 충분히 길다. " * 4)
    )
    (input_dir / "alpha.txt").write_text(source_text, encoding="utf-8")

    source_rows = [
        {
            "source_id": "SRC-alpha",
            "content_sha256": "a" * 64,
            "source_file": "alpha.txt",
            "audit_status": "judged",
            "segmentation_policy": "source_override_pattern",
            "accepted_pattern_family": ["episode_hwa", "angle_episode_hwa", "title_number_hwa"],
            "confidence": 0.95,
            "reason": "judge_selected:episode_hwa_family",
            "candidate_boundary_counts": {"episode_hwa": 3, "angle_episode_hwa": 0, "title_number_hwa": 0},
            "content_length_stats": {"front_matter_hits": 0, "head_nonempty_lines": 3},
        }
    ]

    updated_rows, summary, generated_files = mod._build_source_policy_shadow_apply(
        input_dir=input_dir,
        source_rows=source_rows,
        derived_datasets_dir=derived_dir,
    )

    assert updated_rows[0]["shadow_apply_status"] == "applied"
    assert updated_rows[0]["shadow_apply_validation"]["accepted_pattern_family_source"] == "judge_output"
    assert int(summary["applied_rows"]) == 1
    assert generated_files


@pytest.mark.unit
def test_build_source_policy_shadow_apply_uses_dominant_pattern_fallback_for_low_confidence_manual_review(tmp_path: Path) -> None:
    mod = _import_module()
    input_dir = tmp_path / "input"
    derived_dir = tmp_path / "derived"
    input_dir.mkdir()
    source_text = (
        ("1. 첫 번째 에피소드\n\n첫 번째 에피소드 본문이 충분히 길어서 검증을 통과한다. " * 4)
        + "\n\n"
        + ("2. 둘째 에피소드\n\n둘째 에피소드 본문도 충분히 길다. " * 4)
        + "\n\n"
        + ("3. 셋째 에피소드\n\n셋째 에피소드 본문도 충분히 길다. " * 4)
    )
    (input_dir / "alpha.txt").write_text(source_text, encoding="utf-8")

    source_rows = [
        {
            "source_id": "SRC-alpha",
            "content_sha256": "a" * 64,
            "source_file": "alpha.txt",
            "audit_status": "judged",
            "segmentation_policy": "manual_review",
            "accepted_pattern_family": [],
            "confidence": 0.74,
            "reason": "judge_confidence_below_threshold",
            "current_segmentation_policy": "auto",
            "current_policy_decision_source": "profile_auto",
            "candidate_boundary_counts": {"numbered_title": 3, "plain_title_paren": 0},
            "content_length_stats": {"front_matter_hits": 0, "head_nonempty_lines": 3},
        }
    ]

    updated_rows, summary, generated_files = mod._build_source_policy_shadow_apply(
        input_dir=input_dir,
        source_rows=source_rows,
        derived_datasets_dir=derived_dir,
    )

    assert updated_rows[0]["shadow_apply_status"] == "applied"
    assert updated_rows[0]["shadow_apply_validation"]["accepted_pattern_family"] == ["numbered_title"]
    assert updated_rows[0]["shadow_apply_validation"]["accepted_pattern_family_source"] == "dominant_pattern_fallback"
    assert int(summary["applied_rows"]) == 1
    assert generated_files


@pytest.mark.unit
def test_source_policy_judgments_escalates_profile_auto_segment_quality_anomaly_to_shadow_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_module()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    oversized_body = "긴본문" * 9000
    (input_dir / "alpha.txt").write_text(
        "[1] 짧은 화\n\n짧다.\n\n"
        f"[2] 긴 화\n\n{oversized_body}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "load_config", lambda: Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8))
    monkeypatch.setattr(
        mod,
        "judge_source_policy",
        lambda **_kwargs: {
            "judge_backend": "local_nli",
            "judge_requested_backend": "local_nli",
            "judge_effective_backend": "heuristic",
            "judge_model_id": "nli-lite-v1",
            "judge_prompt_version": "source-policy-judge-v1",
            "judge_fallback_used": True,
            "judge_input_hash": "hash-shadow",
            "segmentation_policy": "manual_review",
            "accepted_pattern_family": [],
            "confidence": 0.74,
            "reason": "judge_confidence_below_threshold",
            "manual_review_required": True,
        },
    )

    rows = mod._source_policy_judgments(input_dir=input_dir)

    assert len(rows) == 1
    assert rows[0]["audit_status"] == "judged"
    assert "undersized_segments_present" in rows[0]["audit_trigger_reasons"]
    assert "oversized_segments_present" in rows[0]["audit_trigger_reasons"]
    assert rows[0]["current_segment_quality_flags"]["undersized"] is True
    assert rows[0]["current_segment_quality_flags"]["oversized"] is True
    assert rows[0]["judge_effective_backend"] == "heuristic"


@pytest.mark.unit
def test_build_typed_inject_variants_produces_clear_conflict_sidecar_for_typed_slot_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_module()
    baseline_dir = tmp_path / "baseline"
    derived_dir = tmp_path / "derived"
    baseline_dir.mkdir()
    derived_dir.mkdir()

    row = {
        "dataset": "DS-INJECT-C",
        "source_id": "SRC-1",
        "inject_case_id": "INJ-1",
        "injected_kind": "age",
        "inject_subject_text": "주인공",
        "source_boundary_pattern": "episode_hwa",
        "content": "나이: 14세\n\n[INJECT]\n주인공의 나이는 50세였다.\n",
    }
    (baseline_dir / "DS-INJECT-C.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "load_config", lambda: Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8))
    monkeypatch.setattr("modules.nf_model_gateway.local.text_pair_classifier.ensure_model", lambda _model_id: None)

    generated_files, typed_summary = mod._build_typed_inject_variants(
        baseline_snapshot_dir=baseline_dir,
        derived_datasets_dir=derived_dir,
    )

    assert generated_files
    assert int(typed_summary["DS-INJECT-C-TYPED"]["rows_total"]) == 1
    assert int(typed_summary["DS-INJECT-C-TYPED"]["label_counts"]["clear_conflict"]) == 1
    sidecar_rows = (derived_dir / "typed_inject_usability.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(sidecar_rows) == 1
    first_sidecar = json.loads(sidecar_rows[0])
    assert first_sidecar["inject_quality_label"] == "clear_conflict"
    assert first_sidecar["typed_slot_key"] == "age"
    assert first_sidecar["typed_original_value"] == 14
    assert first_sidecar["typed_injected_value"] == 50
    assert first_sidecar["usable_for_strict"] is True


@pytest.mark.unit
def test_build_typed_inject_variants_skips_rows_without_grounded_original_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_module()
    baseline_dir = tmp_path / "baseline"
    derived_dir = tmp_path / "derived"
    baseline_dir.mkdir()
    derived_dir.mkdir()

    row = {
        "dataset": "DS-INJECT-C",
        "source_id": "SRC-1",
        "inject_case_id": "INJ-1",
        "injected_kind": "age",
        "inject_subject_text": "주인공",
        "source_boundary_pattern": "episode_hwa",
        "content": "주인공은 검을 들었다.\n\n[INJECT]\n주인공의 나이는 50세였다.\n",
    }
    (baseline_dir / "DS-INJECT-C.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(mod, "load_config", lambda: Settings(enable_test_judge_local_nli=True, test_judge_min_confidence=0.8))
    monkeypatch.setattr("modules.nf_model_gateway.local.text_pair_classifier.ensure_model", lambda _model_id: None)

    generated_files, typed_summary = mod._build_typed_inject_variants(
        baseline_snapshot_dir=baseline_dir,
        derived_datasets_dir=derived_dir,
    )

    assert generated_files
    assert int(typed_summary["DS-INJECT-C-TYPED"]["rows_total"]) == 0
    assert int(typed_summary["DS-INJECT-C-TYPED"]["skipped_reason_counts"]["typed_variant_missing_original_slot"]) == 1
    sidecar_rows = (derived_dir / "typed_inject_usability.jsonl").read_text(encoding="utf-8").splitlines()
    assert sidecar_rows == []


def _strict_artifact(
    *,
    consistency_p95: float,
    retrieval_fts_p95: float,
    level: str = "strict",
    timeout_count: int = 0,
    rounds_total: int = 10,
    conflicting_unknown_count: int = 0,
    violate_count_total: int = 0,
    layer3_model_enabled_jobs: int = 0,
    layer3_effective_capable_jobs: int = 0,
) -> dict:
    return {
        "timings_ms": {
            "consistency_p95": consistency_p95,
            "retrieval_fts_p95": retrieval_fts_p95,
        },
        "status": {
            "index_fts": "SUCCEEDED",
            "index_vec": "SUCCEEDED",
            "ingest_failures": 0,
            "consistency_failures": 0,
            "retrieve_vec_failures": 0,
        },
        "parallel": {
            "consistency_level": level,
        },
        "consistency_runtime": {
            "unknown_reason_counts": {"CONFLICTING_EVIDENCE": conflicting_unknown_count},
            "verification_loop_trigger_count": 3,
            "verification_loop_rounds_total": rounds_total,
            "verification_loop_timeout_count": timeout_count,
            "verification_loop_stagnation_break_count": 1,
            "self_evidence_filtered_count": 2,
            "vid_count_total": 10,
            "violate_count_total": violate_count_total,
            "unknown_count_total": 3,
            "layer3_model_enabled_jobs": layer3_model_enabled_jobs,
            "layer3_effective_capable_jobs": layer3_effective_capable_jobs,
            "layer3_promoted_ok_count": 1 if layer3_effective_capable_jobs > 0 else 0,
        },
    }


@pytest.mark.unit
def test_build_strict_layer3_audit_reports_no_artifacts_when_not_supplied(tmp_path: Path) -> None:
    mod = _import_module()
    comparison_dir = tmp_path / "comparison"
    comparison_dir.mkdir()
    typed_path = tmp_path / "typed_inject_usability.jsonl"
    typed_path.write_text(
        json.dumps(
            {
                "dataset": "DS-INJECT-C-TYPED",
                "source_id": "SRC-1",
                "inject_case_id": "INJ-1",
                "injected_kind": "age",
                "inject_quality_label": "contextless_append",
                "judge_confidence": 0.42,
                "usable_for_strict": False,
                "usable_for_layer3_audit": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary, summary_path = mod._build_strict_layer3_audit(
        comparison_dir=comparison_dir,
        typed_usability_path=typed_path,
        baseline_artifact=None,
        control_artifact=None,
        inject_artifact=None,
    )

    assert summary["status"] == "no_strict_artifacts"
    assert summary_path == "strict artifacts not provided"
    assert int(summary["typed_inject_disagreement"]["rows_total"]) == 1
    assert int(summary["typed_inject_disagreement"]["clear_conflict_rows"]) == 0


@pytest.mark.unit
def test_build_strict_layer3_audit_excludes_no_conflict_rows_from_disagreement(tmp_path: Path) -> None:
    mod = _import_module()
    comparison_dir = tmp_path / "comparison"
    comparison_dir.mkdir()
    typed_path = tmp_path / "typed_inject_usability.jsonl"
    typed_path.write_text(
        json.dumps(
            {
                "dataset": "DS-INJECT-C-TYPED",
                "source_id": "SRC-1",
                "inject_case_id": "INJ-1",
                "injected_kind": "death",
                "inject_quality_label": "no_conflict",
                "judge_confidence": 0.93,
                "judge_reason": "typed_slot_matches_original",
                "usable_for_strict": False,
                "usable_for_layer3_audit": True,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary, _summary_path = mod._build_strict_layer3_audit(
        comparison_dir=comparison_dir,
        typed_usability_path=typed_path,
        baseline_artifact=None,
        control_artifact=None,
        inject_artifact=None,
    )

    typed_summary = summary["typed_inject_disagreement"]
    assert int(typed_summary["rows_total"]) == 1
    assert int(typed_summary["clear_conflict_rows"]) == 0
    assert int(typed_summary["no_conflict_rows"]) == 1
    assert int(typed_summary["disagreement_rows"]) == 0
    assert typed_summary["disagreement_samples"] == []


@pytest.mark.unit
def test_build_strict_layer3_audit_evaluates_with_artifacts_and_typed_sidecar(tmp_path: Path) -> None:
    mod = _import_module()
    comparison_dir = tmp_path / "comparison"
    comparison_dir.mkdir()
    typed_path = tmp_path / "typed_inject_usability.jsonl"
    typed_rows = [
        {
            "dataset": "DS-INJECT-C-TYPED",
            "source_id": "SRC-1",
            "inject_case_id": "INJ-1",
            "injected_kind": "age",
            "inject_quality_label": "clear_conflict",
            "judge_confidence": 0.91,
            "usable_for_strict": True,
            "usable_for_layer3_audit": True,
        },
        {
            "dataset": "DS-INJECT-C-TYPED",
            "source_id": "SRC-2",
            "inject_case_id": "INJ-2",
            "injected_kind": "job",
            "inject_quality_label": "ambiguous_subject",
            "judge_confidence": 0.66,
            "usable_for_strict": False,
            "usable_for_layer3_audit": True,
        },
    ]
    typed_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in typed_rows), encoding="utf-8")

    baseline_path = tmp_path / "baseline.json"
    control_path = tmp_path / "control.json"
    inject_path = tmp_path / "inject.json"
    baseline_path.write_text(json.dumps(_strict_artifact(consistency_p95=1000.0, retrieval_fts_p95=300.0, level="quick")), encoding="utf-8")
    control_path.write_text(json.dumps(_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict", conflicting_unknown_count=0, violate_count_total=0, layer3_model_enabled_jobs=1, layer3_effective_capable_jobs=1)), encoding="utf-8")
    inject_path.write_text(json.dumps(_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict", conflicting_unknown_count=2, violate_count_total=1, layer3_model_enabled_jobs=1, layer3_effective_capable_jobs=1)), encoding="utf-8")

    summary, summary_path = mod._build_strict_layer3_audit(
        comparison_dir=comparison_dir,
        typed_usability_path=typed_path,
        baseline_artifact=baseline_path,
        control_artifact=control_path,
        inject_artifact=inject_path,
    )

    assert summary["status"] == "evaluated"
    assert summary["strict_layer3_gate"]["status"] == "PASS"
    assert float(summary["false_positive_drift"]["signal_rate_gap"]) > 0.0
    assert int(summary["typed_inject_disagreement"]["clear_conflict_rows"]) == 1
    assert int(summary["typed_inject_disagreement"]["disagreement_rows"]) == 1
    assert int(summary["typed_inject_disagreement"]["usable_for_strict_rows"]) == 1
    assert summary_path.endswith("strict_layer3_audit_summary.json")


@pytest.mark.unit
def test_resolve_strict_artifacts_auto_discovers_latest_operational_triplet(tmp_path: Path) -> None:
    mod = _import_module()
    bench_dir = tmp_path / "bench"
    bench_dir.mkdir()

    older_baseline = bench_dir / "20260307T010000Z.json"
    newer_baseline = bench_dir / "20260307T020000Z.json"
    control_path = bench_dir / "20260307T030000Z.json"
    inject_path = bench_dir / "20260307T040000Z.json"
    older_baseline.write_text(json.dumps({"bench_label": "operational-main:DS-200"}), encoding="utf-8")
    newer_baseline.write_text(json.dumps({"bench_label": "operational-main:DS-200"}), encoding="utf-8")
    control_path.write_text(json.dumps({"bench_label": "operational-strict-main:DS-CONTROL-D"}), encoding="utf-8")
    inject_path.write_text(json.dumps({"bench_label": "operational-strict-main:DS-INJECT-C"}), encoding="utf-8")

    baseline, control, inject, resolution = mod._resolve_strict_artifacts(
        baseline_artifact=None,
        control_artifact=None,
        inject_artifact=None,
        strict_artifact_dir=bench_dir,
    )

    assert baseline == newer_baseline
    assert control == control_path
    assert inject == inject_path
    assert resolution["mode"] == "auto_discovery"
    assert resolution["status"] == "complete"
    assert resolution["missing"] == []


@pytest.mark.unit
def test_resolve_strict_artifacts_prefers_layer3_capable_strict_artifacts(tmp_path: Path) -> None:
    mod = _import_module()
    bench_dir = tmp_path / "bench"
    bench_dir.mkdir()

    baseline_path = bench_dir / "20260307T020000Z.json"
    older_control = bench_dir / "20260307T030000Z.json"
    older_inject = bench_dir / "20260307T040000Z.json"
    newer_control = bench_dir / "20260307T050000Z.json"
    newer_inject = bench_dir / "20260307T060000Z.json"
    baseline_path.write_text(json.dumps({"bench_label": "operational-main:DS-200"}), encoding="utf-8")
    older_control.write_text(
        json.dumps(
            {
                "bench_label": "operational-strict-main:DS-CONTROL-D",
                **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, layer3_model_enabled_jobs=1, layer3_effective_capable_jobs=1),
            }
        ),
        encoding="utf-8",
    )
    older_inject.write_text(
        json.dumps(
            {
                "bench_label": "operational-strict-main:DS-INJECT-C",
                **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, layer3_model_enabled_jobs=1, layer3_effective_capable_jobs=1),
            }
        ),
        encoding="utf-8",
    )
    newer_control.write_text(
        json.dumps(
            {
                "bench_label": "operational-strict-main:DS-CONTROL-D",
                **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, layer3_model_enabled_jobs=0, layer3_effective_capable_jobs=0),
            }
        ),
        encoding="utf-8",
    )
    newer_inject.write_text(
        json.dumps(
            {
                "bench_label": "operational-strict-main:DS-INJECT-C",
                **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, layer3_model_enabled_jobs=0, layer3_effective_capable_jobs=0),
            }
        ),
        encoding="utf-8",
    )

    baseline, control, inject, resolution = mod._resolve_strict_artifacts(
        baseline_artifact=None,
        control_artifact=None,
        inject_artifact=None,
        strict_artifact_dir=bench_dir,
    )

    assert baseline == baseline_path
    assert control == older_control
    assert inject == older_inject
    assert resolution["status"] == "complete"


@pytest.mark.unit
def test_run_dev_judged_dataset_pipeline_uses_auto_discovered_strict_artifacts(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_root = tmp_path / "judge_runs"
    bench_dir = tmp_path / "bench"
    input_dir.mkdir()
    bench_dir.mkdir()
    lines = []
    for idx in range(1, 5):
        lines.append(f"[{idx}] alpha episode {idx}\n")
        lines.append("?μ냼: 遺곷? ?깆콈\n")
        lines.append("愿怨? 二쇱씤怨듭쓽 ?숈깮,\n\n")
    (input_dir / "alpha.txt").write_text("".join(lines), encoding="utf-8")

    (bench_dir / "20260307T020000Z.json").write_text(
        json.dumps({"bench_label": "operational-main:DS-200", **_strict_artifact(consistency_p95=1000.0, retrieval_fts_p95=300.0, level="quick")}),
        encoding="utf-8",
    )
    (bench_dir / "20260307T030000Z.json").write_text(
        json.dumps({"bench_label": "operational-strict-main:DS-CONTROL-D", **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict", conflicting_unknown_count=0, violate_count_total=0, layer3_model_enabled_jobs=1, layer3_effective_capable_jobs=1)}),
        encoding="utf-8",
    )
    (bench_dir / "20260307T040000Z.json").write_text(
        json.dumps({"bench_label": "operational-strict-main:DS-INJECT-C", **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict", conflicting_unknown_count=2, violate_count_total=1, layer3_model_enabled_jobs=1, layer3_effective_capable_jobs=1)}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "false"
    env["NF_ENABLE_TEST_JUDGE_REMOTE_API"] = "false"

    proc = subprocess.run(
        [
            sys.executable,
            "tools/bench/run_dev_judged_dataset_pipeline.py",
            "--developer-mode",
            "--input-dir",
            str(input_dir),
            "--output-root",
            str(output_root),
            "--inject-sample-size",
            "4",
            "--diversity-profile",
            "basic",
            "--run-id",
            "test-run-auto-strict",
            "--strict-artifact-dir",
            str(bench_dir),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    payload = json.loads(proc.stdout.strip())
    run_root = Path(payload["run_root"])
    summary = json.loads((run_root / "comparison" / "bench_candidate_summary.json").read_text(encoding="utf-8"))
    strict_summary = summary["strict_layer3_audit"]
    assert strict_summary["status"] == "evaluated"
    assert strict_summary["artifact_resolution"]["mode"] == "auto_discovery"
    assert strict_summary["artifact_resolution"]["status"] == "complete"


@pytest.mark.unit
def test_run_dev_judged_dataset_pipeline_auto_discovery_prefers_layer3_capable_strict_artifacts(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_root = tmp_path / "judge_runs"
    bench_dir = tmp_path / "bench"
    input_dir.mkdir()
    bench_dir.mkdir()
    lines = []
    for idx in range(1, 5):
        lines.append(f"[{idx}] alpha episode {idx}\n")
        lines.append("?μ냼: 遺곷? ?깆콈\n")
        lines.append("愿怨? 二쇱씤怨듭쓽 ?숈깮,\n\n")
    (input_dir / "alpha.txt").write_text("".join(lines), encoding="utf-8")

    (bench_dir / "20260307T020000Z.json").write_text(
        json.dumps({"bench_label": "operational-main:DS-200", **_strict_artifact(consistency_p95=1000.0, retrieval_fts_p95=300.0, level="quick")}),
        encoding="utf-8",
    )
    (bench_dir / "20260307T030000Z.json").write_text(
        json.dumps({"bench_label": "operational-strict-main:DS-CONTROL-D", **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict", conflicting_unknown_count=0, violate_count_total=0, layer3_model_enabled_jobs=1, layer3_effective_capable_jobs=1)}),
        encoding="utf-8",
    )
    (bench_dir / "20260307T040000Z.json").write_text(
        json.dumps({"bench_label": "operational-strict-main:DS-INJECT-C", **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict", conflicting_unknown_count=2, violate_count_total=1, layer3_model_enabled_jobs=1, layer3_effective_capable_jobs=1)}),
        encoding="utf-8",
    )
    (bench_dir / "20260307T050000Z.json").write_text(
        json.dumps({"bench_label": "operational-strict-main:DS-CONTROL-D", **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict", conflicting_unknown_count=0, violate_count_total=0, layer3_model_enabled_jobs=0, layer3_effective_capable_jobs=0)}),
        encoding="utf-8",
    )
    (bench_dir / "20260307T060000Z.json").write_text(
        json.dumps({"bench_label": "operational-strict-main:DS-INJECT-C", **_strict_artifact(consistency_p95=1700.0, retrieval_fts_p95=430.0, level="strict", conflicting_unknown_count=2, violate_count_total=1, layer3_model_enabled_jobs=0, layer3_effective_capable_jobs=0)}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "false"
    env["NF_ENABLE_TEST_JUDGE_REMOTE_API"] = "false"

    proc = subprocess.run(
        [
            sys.executable,
            "tools/bench/run_dev_judged_dataset_pipeline.py",
            "--developer-mode",
            "--input-dir",
            str(input_dir),
            "--output-root",
            str(output_root),
            "--inject-sample-size",
            "4",
            "--diversity-profile",
            "basic",
            "--run-id",
            "test-run-auto-strict-layer3",
            "--strict-artifact-dir",
            str(bench_dir),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    payload = json.loads(proc.stdout.strip())
    run_root = Path(payload["run_root"])
    summary = json.loads((run_root / "comparison" / "bench_candidate_summary.json").read_text(encoding="utf-8"))
    strict_summary = summary["strict_layer3_audit"]
    assert strict_summary["status"] == "evaluated"
    assert strict_summary["strict_layer3_gate"]["status"] == "PASS"
    assert strict_summary["artifact_resolution"]["artifacts"]["control_artifact"].endswith("20260307T030000Z.json")
    assert strict_summary["artifact_resolution"]["artifacts"]["inject_artifact"].endswith("20260307T040000Z.json")
