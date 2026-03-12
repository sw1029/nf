from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest


def _import_module():
    quality_dir = Path("tools/quality").resolve()
    sys.path.insert(0, str(quality_dir))
    try:
        return importlib.import_module("check_source_filename_governance")
    finally:
        if str(quality_dir) in sys.path:
            sys.path.remove(str(quality_dir))


@pytest.mark.unit
def test_find_filename_governance_violations_detects_real_filename_mentions_in_untracked_docs(tmp_path: Path) -> None:
    mod = _import_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    source_dir = repo_root / "test_files"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "real-name.txt").write_text("x", encoding="utf-8")
    doc = repo_root / "doc.md"
    doc.write_text("mention real-name.txt here", encoding="utf-8")

    violations = mod.find_filename_governance_violations(repo_root, source_dir=source_dir)

    assert violations == [
        {
            "path": "doc.md",
            "token": "real-name.txt",
            "match_type": "exact_basename",
            "matched_text": "real-name.txt",
        }
    ]


@pytest.mark.unit
def test_find_filename_governance_violations_detects_exact_stem_mentions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _import_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    source_dir = repo_root / "test_files"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "real-name.txt").write_text("x", encoding="utf-8")
    doc = repo_root / "doc.md"
    doc.write_text("mention real-name without extension", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_visible_text_files", lambda _repo_root: [doc])

    violations = mod.find_filename_governance_violations(repo_root, source_dir=source_dir)

    assert violations == [
        {
            "path": "doc.md",
            "token": "real-name.txt",
            "match_type": "exact_stem",
            "matched_text": "real-name",
        }
    ]


@pytest.mark.unit
def test_find_filename_governance_violations_detects_redacted_path_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _import_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    source_dir = repo_root / "test_files"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "real-secret-title.txt").write_text("x", encoding="utf-8")
    doc = repo_root / "doc.md"
    doc.write_text("mention test_files/real-secret...txt here", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_visible_text_files", lambda _repo_root: [doc])

    violations = mod.find_filename_governance_violations(repo_root, source_dir=source_dir)

    assert violations == [
        {
            "path": "doc.md",
            "token": "real-secret-title.txt",
            "match_type": "redacted_path_prefix",
            "matched_text": "test_files/real-secret...txt",
        }
    ]


@pytest.mark.unit
def test_find_filename_governance_violations_ignores_public_alias_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _import_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    source_dir = repo_root / "test_files"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "real-name.txt").write_text("x", encoding="utf-8")
    doc = repo_root / "doc.md"
    doc.write_text("mention source-01 here", encoding="utf-8")

    monkeypatch.setattr(mod, "_repo_visible_text_files", lambda _repo_root: [doc])

    violations = mod.find_filename_governance_violations(repo_root, source_dir=source_dir)

    assert violations == []
