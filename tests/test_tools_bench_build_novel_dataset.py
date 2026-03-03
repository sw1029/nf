from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_episode_text(path: Path, *, source_name: str, count: int) -> None:
    lines: list[str] = []
    for idx in range(1, count + 1):
        lines.append(f"[{idx}] {source_name} episode {idx}\n")
        lines.append(f"{source_name} body {idx}\n\n")
    path.write_text("".join(lines), encoding="utf-8")


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
    assert manifest["build_options"]["diversity_profile"] == "max"

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
    assert (output_dir / "DS-DIVERSE-200.jsonl").exists()
