from __future__ import annotations

from pathlib import Path

import pytest

import run_local_stack


@pytest.mark.unit
def test_default_stack_state_root_isolated_by_host_and_port(tmp_path: Path) -> None:
    root = run_local_stack._default_stack_state_root(tmp_path, "127.0.0.1", 8085)

    assert root == tmp_path / "verify" / "local_stack" / "127_0_0_1_8085"


@pytest.mark.unit
def test_resolve_storage_path_uses_default_when_unset(tmp_path: Path) -> None:
    default_path = tmp_path / "verify" / "local_stack" / "127_0_0_1_8085" / "nf_orchestrator.sqlite3"

    resolved = run_local_stack._resolve_storage_path(tmp_path, "", default_path=default_path)

    assert resolved == default_path


@pytest.mark.unit
def test_resolve_storage_path_preserves_explicit_relative_override(tmp_path: Path) -> None:
    default_path = tmp_path / "verify" / "local_stack" / "127_0_0_1_8085" / "nf_orchestrator.sqlite3"

    resolved = run_local_stack._resolve_storage_path(
        tmp_path,
        "custom/state.sqlite3",
        default_path=default_path,
    )

    assert resolved == tmp_path / "custom" / "state.sqlite3"
