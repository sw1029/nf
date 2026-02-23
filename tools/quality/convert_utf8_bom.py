from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.quality.check_utf8 import _iter_policy_files

UTF8_BOM = b"\xef\xbb\xbf"
NO_BOM_FILENAMES = {"pytest.ini"}


def _decode_text(raw: bytes) -> str:
    if raw.startswith(UTF8_BOM):
        return raw[3:].decode("utf-8")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949")


def convert_repo(repo_root: Path, *, dry_run: bool = False) -> tuple[int, int]:
    files = _iter_policy_files(repo_root)
    changed = 0
    for path in files:
        raw = path.read_bytes()
        text = _decode_text(raw)
        next_raw = text.encode("utf-8")
        if path.name not in NO_BOM_FILENAMES:
            next_raw = UTF8_BOM + next_raw
        if raw == next_raw:
            continue
        changed += 1
        if not dry_run:
            path.write_bytes(next_raw)
    return len(files), changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert policy text files to UTF-8 with BOM.")
    parser.add_argument("--repo-root", default=".", help="Path to repository root.")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would change.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    total, changed = convert_repo(repo_root, dry_run=args.dry_run)
    mode = "would change" if args.dry_run else "changed"
    print(f"UTF-8-BOM conversion scanned {total} files, {mode}: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
