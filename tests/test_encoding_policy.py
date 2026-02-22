from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_repo_text_files_are_utf8_without_bom() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(repo_root / "tools" / "quality" / "check_utf8.py"), "--repo-root", str(repo_root)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, (result.stdout + "\n" + result.stderr).strip()
