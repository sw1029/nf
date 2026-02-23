from __future__ import annotations

import argparse
import sys
from pathlib import Path


TEXT_EXTENSIONS = {
    ".py",
    ".ps1",
    ".cmd",
    ".bat",
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".sql",
    ".csv",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".scss",
    ".html",
    ".xml",
    ".sh",
}

ROOT_FILENAMES = {
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "pytest.ini",
}

NO_BOM_FILENAMES = {
    # pytest/iniconfig cannot parse BOM-prefixed ini files on Windows.
    "pytest.ini",
}

INCLUDE_DIRS = ("modules", "tests", "tools", "plan")
EXCLUDE_PREFIXES = (
    ".git/",
    ".pytest_cache/",
    "__pycache__/",
    "data/",
    "verify/",
    "test_files/",
)


def _is_excluded(rel_path: str) -> bool:
    return any(rel_path.startswith(prefix) for prefix in EXCLUDE_PREFIXES)


def _iter_policy_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []

    for item in repo_root.iterdir():
        if not item.is_file():
            continue
        if item.name in ROOT_FILENAMES:
            files.append(item)
            continue
        if item.suffix.lower() in TEXT_EXTENSIONS:
            files.append(item)

    for dirname in INCLUDE_DIRS:
        base = repo_root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root).as_posix()
            if _is_excluded(rel):
                continue
            if path.suffix.lower() in TEXT_EXTENSIONS:
                files.append(path)

    dedup = {p.resolve(): p for p in files}
    return [dedup[key] for key in sorted(dedup.keys())]


def _encoding_error(raw: bytes, *, require_bom: bool = True) -> str | None:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16-bom-not-allowed"
    if require_bom and not raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-bom-required"
    if not require_bom and raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-bom-not-allowed"
    body = raw[3:] if require_bom else raw
    try:
        body.decode("utf-8")
        return None
    except UnicodeDecodeError as exc:
        return f"not-utf8@{exc.start}"


def collect_violations(repo_root: Path) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    for path in _iter_policy_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            violations.append((rel, f"read-error:{exc}"))
            continue
        err = _encoding_error(raw, require_bom=path.name not in NO_BOM_FILENAMES)
        if err:
            violations.append((rel, err))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repo text files are UTF-8 with BOM.")
    parser.add_argument("--repo-root", default=".", help="Path to repository root.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    violations = collect_violations(repo_root)
    if not violations:
        print("UTF-8-BOM policy check passed")
        return 0

    print("UTF-8-BOM policy violations detected:")
    for rel, reason in violations:
        print(f"- {rel}: {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
