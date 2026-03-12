from __future__ import annotations

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
        import build_novel_dataset  # type: ignore

        return build_novel_dataset
    finally:
        if str(bench_dir) in sys.path:
            sys.path.remove(str(bench_dir))


def _write_episode_text(path: Path, *, source_name: str, count: int) -> None:
    lines: list[str] = []
    for idx in range(1, count + 1):
        lines.append(f"[{idx}] {source_name} episode {idx}\n")
        lines.append(f"{source_name} body {idx}\n\n")
    path.write_text("".join(lines), encoding="utf-8")


@pytest.mark.unit
def test_make_source_id_is_filename_independent() -> None:
    mod = _import_module()
    payload = "same content".encode("utf-8")
    sha = mod.hashlib.sha256(payload).hexdigest()

    assert mod.make_source_id(sha) == mod.make_source_id(sha)


@pytest.mark.unit
def test_guard_output_dir_for_judge_audit_rejects_canonical_verify_datasets() -> None:
    mod = _import_module()

    with pytest.raises(SystemExit, match="canonical verify/datasets"):
        mod._guard_output_dir_for_judge_audit(Path("verify/datasets"), enable_judge_audit=True)


@pytest.mark.unit
def test_guard_output_dir_for_judge_audit_allows_noncanonical_output(tmp_path: Path) -> None:
    mod = _import_module()

    mod._guard_output_dir_for_judge_audit(tmp_path / "judge_run", enable_judge_audit=True)


@pytest.mark.unit
def test_source_policy_registry_lookup_uses_content_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()
    registry_path = tmp_path / "source_policy_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "source_policy_registry_version": "test-r1",
                "sources": [
                    {
                        "source_id": "SRC-aaaa",
                        "content_sha256": "a" * 64,
                        "segmentation_policy": "manual_review",
                        "allowed_patterns": [],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_SOURCE_POLICY_REGISTRY_PATH", registry_path)

    registry, version = mod._load_source_policy_registry()

    assert version == "test-r1"
    assert registry["a" * 64]["source_id"] == "SRC-aaaa"


@pytest.mark.unit
def test_manual_review_reason_code_detects_front_matter_dominant() -> None:
    mod = _import_module()
    text = "All rights are reserved.\n\n머리말\n\n프롤로그\n\n본문\n"

    reason = mod._manual_review_reason_code(text, {name: 0 for name in mod._PATTERN_NAMES})

    assert reason == "front_matter_dominant"


@pytest.mark.unit
def test_manual_review_reason_code_detects_unsupported_header_variant() -> None:
    mod = _import_module()
    text = "제1장 시작\n본문\n\n제2장 계속\n다음 본문\n"

    reason = mod._manual_review_reason_code(text, {name: 0 for name in mod._PATTERN_NAMES})

    assert reason == "blank_line_gate_filtered_candidates"


@pytest.mark.unit
def test_manual_review_reason_code_detects_blank_line_gate_filtered_candidates() -> None:
    mod = _import_module()
    text = "1. 첫 장\n본문이 바로 이어진다.\n2. 둘째 장\n다음 본문\n"

    reason = mod._manual_review_reason_code(text, {name: 0 for name in mod._PATTERN_NAMES})

    assert reason == "blank_line_gate_filtered_candidates"


@pytest.mark.unit
def test_maybe_judge_inject_record_returns_judge_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_module()
    episode = mod.Episode(
        source_file="sample.txt",
        source_id="SRC-aaaa",
        source_content_sha256="a" * 64,
        episode_no=1,
        header="[1] sample",
        content="본문",
        segmentation_mode="header_boundary",
        boundary_pattern="bracket",
    )

    monkeypatch.setattr(
        mod,
        "load_config",
        lambda: Settings(enable_test_judge_local_nli=True, test_judge_local_nli_model_id="nli-test"),
    )
    monkeypatch.setattr(
        mod,
        "judge_inject_quality",
        lambda **kwargs: {
            "inject_quality_label": "clear_conflict",
            "judge_confidence": 0.91,
            "judge_backend": "local_nli",
            "judge_requested_backend": "local_nli",
            "judge_effective_backend": "local_nli_fallback",
            "judge_model_id": "nli-test",
            "judge_prompt_version": "inject-quality-judge-v1",
            "judge_fallback_used": True,
            "judge_input_hash": "hash-1",
        },
    )

    result = mod._maybe_judge_inject_record(
        episode=episode,
        original_content="원문",
        injected_statement="주인공의 나이는 50세였다.",
        injected_kind="age",
    )

    assert result is not None
    assert result["judge_requested_backend"] == "local_nli"
    assert result["judge_effective_backend"] == "local_nli_fallback"
    assert result["judge_model_id"] == "nli-test"
    assert result["judge_fallback_used"] is True
    assert result["judge_input_hash"] == "hash-1"


def _split_with_defaults(mod, text: str, *, source_file: str = "sample.txt", source_policy: dict | None = None):
    source_content_sha256 = mod.hashlib.sha256(text.encode("utf-8")).hexdigest()
    source_id = mod.make_source_id(source_content_sha256)
    return mod.split_episodes_with_stats(
        text,
        source_file=source_file,
        source_id=source_id,
        source_content_sha256=source_content_sha256,
        source_policy=source_policy or mod._source_policy_from_registry(None),
    )


@pytest.mark.unit
def test_split_episodes_supports_common_hwa_headers() -> None:
    mod = _import_module()
    text = (
        "1화\n\n첫 화 본문\n\n"
        "0화 프롤로그\n\n프롤로그 본문\n\n"
        "<1화>\n\n앵글 본문\n\n"
        "회귀자의 빌런 사냥법 2화\n\n타이틀 화 본문\n\n"
    )

    episodes, stats = _split_with_defaults(mod, text)

    assert [episode.episode_no for episode in episodes] == [1, 0, 1, 2]
    assert episodes[0].boundary_pattern == "episode_hwa"
    assert episodes[2].boundary_pattern == "angle_episode_hwa"
    assert episodes[3].boundary_pattern == "title_number_hwa"
    assert stats["fallback_used"] is False
    assert int(stats["boundary_counts"]["episode_hwa"]) == 2
    assert int(stats["boundary_counts"]["angle_episode_hwa"]) == 1
    assert int(stats["boundary_counts"]["title_number_hwa"]) == 1


@pytest.mark.unit
def test_split_episodes_supports_ep_prefix_headers() -> None:
    mod = _import_module()
    text = (
        "EP.0 \ud504\ub864\ub85c\uadf8\n\n\uc5d0\ud53c\uc18c\ub4dc \ubcf8\ubb38\n\n"
        "EP.1 \uc5d0\ud53c\uc18c\ub4dc\n\n\ub2e4\uc74c \ubcf8\ubb38\n\n"
    )

    episodes, stats = _split_with_defaults(mod, text)

    assert [episode.episode_no for episode in episodes] == [0, 1]
    assert episodes[0].boundary_pattern == "ep_prefix"
    assert stats["fallback_used"] is False
    assert int(stats["boundary_counts"]["ep_prefix"]) == 2


@pytest.mark.unit
def test_split_episodes_supports_bracketed_numbered_title_headers() -> None:
    mod = _import_module()
    text = (
        "\u30101. \uc0b4\ub824\ubcf4\uc2dc\uaca0\uc5b4\uc694?\u3011\n\n\ube0c\ub77c\ucf13 \ubcf8\ubb38\n\n"
        "\u30102. \ub2e4\uc74c \uc7a5\uba74\u3011\n\n\ub2e4\uc74c \ubcf8\ubb38\n\n"
    )

    episodes, stats = _split_with_defaults(mod, text)

    assert [episode.episode_no for episode in episodes] == [1, 2]
    assert episodes[0].boundary_pattern == "bracketed_numbered_title"
    assert stats["fallback_used"] is False
    assert int(stats["boundary_counts"]["bracketed_numbered_title"]) == 2


@pytest.mark.unit
def test_split_episodes_supports_section_jo_headers() -> None:
    mod = _import_module()
    text = (
        "\uc81c1\uc870. \uad50\uc2e4\uc5d0 \ub4e4\uc5b4\uac11\ub2c8\ub2e4\n\n\uc870\ubb38 \ubcf8\ubb38\n\n"
        "\uc81c2\uc870. \ub2e4\uc74c \uc870\ubb38\n\n\ub2e4\uc74c \ubcf8\ubb38\n\n"
    )

    episodes, stats = _split_with_defaults(mod, text)

    assert [episode.episode_no for episode in episodes] == [1, 2]
    assert episodes[0].boundary_pattern == "section_jo"
    assert stats["fallback_used"] is False
    assert int(stats["boundary_counts"]["section_jo"]) == 2


@pytest.mark.unit
def test_split_episodes_supports_prologue_and_chapter_jang_headers() -> None:
    mod = _import_module()
    text = (
        "\ud504\ub864\ub85c\uadf8\n\n\ubb3c\uc74c \uc18d\uc758 \ub178\uc778\uc774 \ub208\uc744 \ub5b4\ub2e4.\n\n"
        "\uc81c1\uc7a5 \ubb34\ub2f9\ud30c\uc758 \ub178\uc778\n\n\ub178\uc778\uc740 \ucc9c\ucc9c\ud788 \uc0b0\ubb38\uc744 \ub098\uc130\ub2e4.\n\n"
        "\uc81c2\uc7a5 \uac15\ud638\ucd08\ucd9c\n\n\uc18c\ub144\uc740 \ucc98\uc74c \uac15\ud638\ub97c \ubc14\ub77c\ubcf4\uc558\ub2e4.\n\n"
    )

    episodes, stats = _split_with_defaults(mod, text)

    assert [episode.episode_no for episode in episodes] == [0, 1, 2]
    assert episodes[0].boundary_pattern == "prologue_header"
    assert episodes[1].boundary_pattern == "chapter_jang"
    assert stats["fallback_used"] is False
    assert int(stats["boundary_counts"]["prologue_header"]) == 1
    assert int(stats["boundary_counts"]["chapter_jang"]) == 2


@pytest.mark.unit
def test_split_episodes_supports_source_specific_standalone_number_override() -> None:
    mod = _import_module()
    text = (
        "1\n\n첫 본문\n\n"
        "2\n\n둘째 본문\n\n"
        "3\n\n셋째 본문\n"
    )

    episodes, stats = _split_with_defaults(
        mod,
        text,
        source_policy={
            "segmentation_policy": "source_override_pattern",
            "allowed_patterns": ["standalone_number"],
            "policy_decision_source": "registry_override",
            "policy_confidence": 1.0,
            "reason": "test_override",
        },
    )

    assert [episode.episode_no for episode in episodes] == [1, 2, 3]
    assert episodes[0].boundary_pattern == "standalone_number"
    assert stats["fallback_used"] is False
    assert stats["source_segmentation_policy"] == "source_override_pattern"
    assert int(stats["boundary_counts"]["standalone_number"]) == 3


@pytest.mark.unit
def test_split_episodes_supports_common_title_headers() -> None:
    mod = _import_module()
    text = (
        "001. \ud504\ub864\ub85c\uadf8\n\n\uc22b\uc790 \uc810 \ubcf8\ubb38\n\n"
        "1. \ub2e8\ud3b8 \uc81c\ubaa9\n\n\ub2e8\ud3b8 \ubcf8\ubb38\n\n"
        "\ucc38\uc744\uc131 \uac15\ud55c \ub9c8\ubc95\uc0ac (2)\n\n\uc77c\ubc18 \uad04\ud638 \ubcf8\ubb38\n\n"
        "< \ucd5c\uace0\uc758 \ubcf4\uc0c1(3) >\n\n\uc575\uae00 \uad04\ud638 \ubcf8\ubb38\n"
    )

    episodes, stats = _split_with_defaults(mod, text)

    assert [episode.episode_no for episode in episodes] == [1, 1, 2, 3]
    assert episodes[0].boundary_pattern == "numbered_title"
    assert episodes[2].boundary_pattern == "plain_title_paren"
    assert episodes[3].boundary_pattern == "angle_title_paren"
    assert stats["fallback_used"] is False
    assert int(stats["boundary_counts"]["numbered_title"]) == 2
    assert int(stats["boundary_counts"]["plain_title_paren"]) == 1
    assert int(stats["boundary_counts"]["angle_title_paren"]) == 1
    assert int(stats["boundary_counts"]["angle_title_paren"]) == 1


@pytest.mark.unit
def test_build_novel_dataset_generates_diverse_sets_and_manifest_fields(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_episode_text(input_dir / "alpha.txt", source_name="alpha", count=170)
    _write_episode_text(input_dir / "beta.txt", source_name="beta", count=170)

    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "200",
            "--seed",
            "42",
            "--diversity-profile",
            "max",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is True

    manifest_path = output_dir / "dataset_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "source_snapshot_hash" in manifest
    assert manifest["dataset_generation_version"] == "20260312-r7"
    assert manifest["build_input_hash_policy"] == "sha256(raw_bytes_per_file)"
    assert manifest["build_options"]["diversity_profile"] == "max"
    assert manifest["judge_audit_enabled"] is False
    assert int(manifest["judge_audit_policy_count"]) == 0
    assert "segmentation_summary" in manifest
    assert isinstance(manifest["quality_warnings"], list)

    datasets = manifest["datasets"]
    required = (
        "DS-DIVERSE-200",
        "DS-DIVERSE-400",
        "DS-DIVERSE-800",
        "DS-DIVERSE-CONTROL-D",
        "DS-DIVERSE-INJECT-C",
    )
    for key in required:
        assert key in datasets

    diverse_200 = datasets["DS-DIVERSE-200"]
    assert int(diverse_200["unique_source_files"]) > 1
    assert isinstance(diverse_200["top_source_distribution"], list)
    assert diverse_200["sampling_strategy"] == "round_robin_seed_42_count_200"
    assert isinstance(diverse_200["source_order"], list)
    assert diverse_200["dataset_generation_version"] == "20260312-r7"
    assert "consistency_corroboration_policy_counts" in diverse_200
    assert (output_dir / "DS-DIVERSE-200.jsonl").exists()

    first_input = manifest["input_files"][0]
    assert first_input["split_strategy"] == "header_boundary"
    assert first_input["fallback_used"] is False
    assert "content_sha256" in first_input
    assert "candidate_boundary_counts" in first_input
    assert int(first_input["boundary_counts"]["bracket"]) > 0
    assert "content_length_stats" in first_input

    inject_path = output_dir / "DS-INJECT-C.jsonl"
    first_inject = json.loads(inject_path.read_text(encoding="utf-8").splitlines()[0])
    assert first_inject["source_segmentation_mode"] == "header_boundary"
    assert first_inject["inject_strategy"] == "append_marker_statement"
    assert "consistency_corroboration_policy" in first_inject
    assert first_inject["inject_subject_text"] == "주인공"
    assert first_inject["inject_expected_signal"] == "conflict_signal_expected"


@pytest.mark.unit
def test_build_novel_dataset_does_not_write_judge_metadata_without_explicit_flag(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for idx in range(1, 6):
        lines.append(f"[{idx}] alpha episode {idx}\n")
        lines.append("장소: 북부 성채\n")
        lines.append("관계: 주인공의 동생\n\n")
    (input_dir / "alpha.txt").write_text("".join(lines), encoding="utf-8")

    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    env = dict(**os.environ)
    env["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "true"
    env["NF_TEST_JUDGE_LOCAL_NLI_MODEL_ID"] = "nli-lite-v1"
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "4",
            "--seed",
            "42",
            "--diversity-profile",
            "basic",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is True

    manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["judge_audit_enabled"] is False
    assert int(manifest["judge_audit_policy_count"]) == 0

    inject_first = json.loads((output_dir / "DS-INJECT-C.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert inject_first["judge_requested_backend"] in ("", None)
    assert inject_first["judge_effective_backend"] in ("", None)
    assert inject_first["judge_prompt_version"] in ("", None)
    assert inject_first["judge_input_hash"] in ("", None)


@pytest.mark.unit
def test_build_novel_dataset_is_hash_stable_when_judge_env_is_set_without_flag(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir_a = tmp_path / "datasets_a"
    output_dir_b = tmp_path / "datasets_b"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir_a.mkdir(parents=True, exist_ok=True)
    output_dir_b.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for idx in range(1, 6):
        lines.append(f"[{idx}] alpha episode {idx}\n")
        lines.append("장소: 북부 성채\n")
        lines.append("관계: 주인공의 동생\n\n")
    (input_dir / "alpha.txt").write_text("".join(lines), encoding="utf-8")

    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    base_args = [
        sys.executable,
        str(script_path),
        "--input-dir",
        str(input_dir),
        "--inject-sample-size",
        "4",
        "--seed",
        "42",
        "--diversity-profile",
        "basic",
    ]

    subprocess.run(
        [*base_args, "--output-dir", str(output_dir_a)],
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )

    env_with_judge = dict(os.environ)
    env_with_judge["NF_ENABLE_TEST_JUDGE_LOCAL_NLI"] = "true"
    env_with_judge["NF_TEST_JUDGE_LOCAL_NLI_MODEL_ID"] = "nli-lite-v1"
    subprocess.run(
        [*base_args, "--output-dir", str(output_dir_b)],
        check=True,
        capture_output=True,
        text=True,
        env=env_with_judge,
    )

    for file_name in ("DS-INJECT-C.jsonl", "DS-DIVERSE-INJECT-C.jsonl"):
        left = (output_dir_a / file_name).read_text(encoding="utf-8")
        right = (output_dir_b / file_name).read_text(encoding="utf-8")
        assert left == right

    manifest_a = json.loads((output_dir_a / "dataset_manifest.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((output_dir_b / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest_a["judge_audit_enabled"] is False
    assert manifest_b["judge_audit_enabled"] is False
    assert int(manifest_a["judge_audit_policy_count"]) == 0
    assert int(manifest_b["judge_audit_policy_count"]) == 0
    assert manifest_a["input_files"] == manifest_b["input_files"]


@pytest.mark.unit
def test_build_novel_dataset_manifest_marks_fallback_chunking_and_quality_warning(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    (input_dir / "fallback.txt").write_text("본문만 있고 화 구분 헤더는 없다.\n" * 1500, encoding="utf-8")

    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "10",
            "--seed",
            "7",
            "--diversity-profile",
            "basic",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is True

    manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["segmentation_summary"]["fallback_files"] == 1
    assert manifest["segmentation_summary"]["fallback_episode_share"] == pytest.approx(1.0)
    assert int(manifest["manual_review_source_count"]) == 1
    assert manifest["manual_review_reason_counts"] == {"no_repeated_markers": 1}
    assert any(item["code"] == "HIGH_FALLBACK_EPISODE_SHARE" for item in manifest["quality_warnings"])
    assert any(item["code"] == "FALLBACK_SOURCES_PRESENT" for item in manifest["quality_warnings"])
    assert any(item["code"] == "GROWTH_DATASET_PREFIX_BIAS" for item in manifest["quality_warnings"])
    assert any(item["code"] == "GENERIC_APPEND_INJECT_DATASET" for item in manifest["quality_warnings"])
    assert any(item["code"] == "COMPOSITE_DATASETS_FALLBACK_ONLY_POOL" for item in manifest["quality_warnings"])
    fallback_warning = next(item for item in manifest["quality_warnings"] if item["code"] == "FALLBACK_SOURCES_PRESENT")
    assert len(fallback_warning["fallback_source_files"]) == 1
    assert fallback_warning["fallback_source_files"][0].startswith("SRC-")
    first_input = manifest["input_files"][0]
    assert first_input["fallback_used"] is True
    assert first_input["split_strategy"] == "fallback_chunk"
    assert first_input["manual_review_diagnostics"]["reason_code"] == "no_repeated_markers"
    assert (output_dir / "manual_review_sources.json").exists()
    manual_review = manifest["manual_review_sources"][0]
    assert manual_review["manual_review_diagnostics"]["reason_code"] == "no_repeated_markers"


@pytest.mark.unit
def test_build_novel_dataset_emits_segment_size_quality_warnings(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    oversized_body = "긴본문" * 9000
    (input_dir / "alpha.txt").write_text(
        "[1] 짧은 화\n\n짧다.\n\n"
        f"[2] 긴 화\n\n{oversized_body}\n",
        encoding="utf-8",
    )

    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "10",
            "--seed",
            "13",
            "--diversity-profile",
            "basic",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is True

    manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    segment_quality = manifest["segment_quality_summary"]
    assert segment_quality["min_segment_chars_warning"] == 40
    assert segment_quality["max_segment_chars_warning"] == 20000
    assert int(segment_quality["undersized_source_count"]) == 1
    assert int(segment_quality["oversized_source_count"]) == 1

    warning_codes = {item["code"] for item in manifest["quality_warnings"]}
    assert "UNDERSIZED_SEGMENTS_PRESENT" in warning_codes
    assert "OVERSIZED_SEGMENTS_PRESENT" in warning_codes

    input_row = manifest["input_files"][0]
    assert input_row["segment_quality_flags"]["undersized"] is True
    assert input_row["segment_quality_flags"]["oversized"] is True


@pytest.mark.unit
def test_build_novel_dataset_fails_when_manual_review_source_threshold_exceeded(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    (input_dir / "fallback.txt").write_text("헤더 없는 긴 본문\n" * 3000, encoding="utf-8")
    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "10",
            "--seed",
            "7",
            "--diversity-profile",
            "basic",
            "--max-manual-review-sources",
            "0",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "manual review source count" in proc.stderr


@pytest.mark.unit
def test_build_novel_dataset_fails_when_undersized_source_threshold_exceeded(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    (input_dir / "alpha.txt").write_text(
        "[1] 짧은 화\n\n짧다.\n\n"
        "[2] 정상 화\n\n" + ("정상 본문 " * 400) + "\n",
        encoding="utf-8",
    )
    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "10",
            "--seed",
            "13",
            "--diversity-profile",
            "basic",
            "--max-undersized-sources",
            "0",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "undersized source count" in proc.stderr


@pytest.mark.unit
def test_build_novel_dataset_fails_when_oversized_source_threshold_exceeded(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    oversized_body = "긴본문" * 9000
    (input_dir / "alpha.txt").write_text(
        f"[1] 긴 화\n\n{oversized_body}\n\n"
        "[2] 둘째 화\n\n정상 본문\n",
        encoding="utf-8",
    )
    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "10",
            "--seed",
            "13",
            "--diversity-profile",
            "basic",
            "--max-oversized-sources",
            "0",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "oversized source count" in proc.stderr


@pytest.mark.unit
def test_build_novel_dataset_excludes_fallback_sources_from_composite_sets(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_episode_text(input_dir / "alpha.txt", source_name="alpha", count=120)
    (input_dir / "fallback.txt").write_text("헤더 없는 긴 본문\n" * 5000, encoding="utf-8")

    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "20",
            "--seed",
            "9",
            "--diversity-profile",
            "basic",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is True

    manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    pool = manifest["composite_source_pool"]
    expected_alpha_id = _import_module().make_source_id(
        _import_module().hashlib.sha256((input_dir / "alpha.txt").read_bytes()).hexdigest()
    )
    expected_fallback_id = _import_module().make_source_id(
        _import_module().hashlib.sha256((input_dir / "fallback.txt").read_bytes()).hexdigest()
    )
    assert pool["excluded_source_ids"] == [expected_fallback_id]
    assert pool["eligible_source_ids"] == [expected_alpha_id]

    growth = manifest["datasets"]["DS-GROWTH-50"]
    assert growth["unique_source_files"] == 1
    assert growth["top_source_distribution"][0]["source_id"] == expected_alpha_id
    assert growth["sampling_strategy"] == "shuffled_seed_9_prefix_50"
    assert growth["dataset_generation_version"] == "20260312-r7"

    inject_first = json.loads((output_dir / "DS-INJECT-C.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert inject_first["source_id"].startswith("SRC-")


@pytest.mark.unit
def test_build_novel_dataset_records_manual_review_counts_and_structured_subset(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "datasets"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for idx in range(1, 81):
        lines.append(f"[{idx}] alpha episode {idx}\n")
        lines.append(f"장소: alpha-city-{idx}\n")
        lines.append(f"사건은 2000년 1월 {idx % 28 + 1}일에 발생했다.\n\n")
    (input_dir / "alpha.txt").write_text("".join(lines), encoding="utf-8")
    script_path = Path("tools/bench/build_novel_dataset.py").resolve()
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--inject-sample-size",
            "40",
            "--seed",
            "11",
            "--diversity-profile",
            "basic",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is True

    manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert int(manifest["manual_review_source_count"]) == 0
    assert manifest["manual_review_reason_counts"] == {}

    structured_path = output_dir / "DS-INJECT-C-STRUCTURED.jsonl"
    assert structured_path.exists()
    first_structured = json.loads(structured_path.read_text(encoding="utf-8").splitlines()[0])
    assert first_structured["inject_case_id"].startswith("INJ-")
    assert first_structured["inject_target_scope"] == "global_slot"
    assert first_structured["inject_expected_primary_signal"] == "explicit_slot_conflict"
    assert first_structured["inject_expected_core_verdict"] == "UNKNOWN_OR_VIOLATE"
