from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable

TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".ps1", ".html", ".js", ".css"}
EXCLUDED_PATH_PARTS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "__pycache__",
    "data",
    "node_modules",
    "test_files",
    "verify",
}
REDACTED_PATH_RE = re.compile(r"test_files[\\/](?P<fragment>[^\r\n`\"']+?)\.{3}txt")


def _is_scannable_text_path(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    return not any(part.lower() in EXCLUDED_PATH_PARTS for part in path.parts)


def _repo_visible_text_files(repo_root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        text=True,
        encoding="utf-8",
    )
    paths = []
    seen: set[str] = set()
    for line in output.splitlines():
        rel_path = Path(line)
        rel_key = rel_path.as_posix()
        if rel_key in seen or not _is_scannable_text_path(rel_path):
            continue
        seen.add(rel_key)
        paths.append(repo_root / rel_path)
    return paths


def _denylist(source_dir: Path) -> list[dict[str, str]]:
    return [{"token": path.name, "stem": path.stem} for path in sorted(source_dir.glob("*.txt"))]


def _first_match(text: str, candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        if candidate and candidate in text:
            return candidate
    return None


def _find_redacted_path_match(text: str, *, stem: str) -> str | None:
    for match in REDACTED_PATH_RE.finditer(text):
        fragment = match.group("fragment").strip()
        if fragment and stem.startswith(fragment):
            return match.group(0)
    return None


def _find_violation(text: str, *, token: str, stem: str) -> dict[str, str] | None:
    basename_match = _first_match(text, (f"test_files/{token}", f"test_files\\{token}", token))
    if basename_match:
        return {
            "match_type": "exact_basename",
            "matched_text": basename_match,
        }

    redacted_match = _find_redacted_path_match(text, stem=stem)
    if redacted_match:
        return {
            "match_type": "redacted_path_prefix",
            "matched_text": redacted_match,
        }

    stem_match = _first_match(text, (f"test_files/{stem}", f"test_files\\{stem}", stem))
    if stem_match:
        return {
            "match_type": "exact_stem",
            "matched_text": stem_match,
        }
    return None


def find_filename_governance_violations(repo_root: Path, *, source_dir: Path) -> list[dict[str, str]]:
    denylist = _denylist(source_dir)
    violations: list[dict[str, str]] = []
    for path in _repo_visible_text_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for item in denylist:
            token = item["token"]
            stem = item["stem"]
            violation = _find_violation(text, token=token, stem=stem)
            if violation:
                violations.append(
                    {
                        "path": str(path.relative_to(repo_root)),
                        "token": token,
                        **violation,
                    }
                )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Check repo-visible text files for real corpus filename mentions.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--source-dir", type=Path, default=Path("test_files"))
    args = parser.parse_args()

    violations = find_filename_governance_violations(args.repo_root.resolve(), source_dir=args.source_dir.resolve())
    print(json.dumps({"ok": len(violations) == 0, "violations": violations}, ensure_ascii=False, indent=2))
    return 0 if not violations else 2


if __name__ == "__main__":
    raise SystemExit(main())
