from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_handle_assets_supports_js_and_css_content_types() -> None:
    source = Path("modules/nf_orchestrator/main.py").read_text(encoding="utf-8")
    assert 'filename.lower().endswith(".js")' in source
    assert 'application/javascript' in source
    assert 'filename.lower().endswith(".css")' in source
    assert 'text/css; charset=utf-8' in source


@pytest.mark.unit
def test_debug_ui_uses_split_static_assets() -> None:
    html = Path("modules/nf_orchestrator/debug_ui.html").read_text(encoding="utf-8")
    assert '/assets/debug_ui.styles.css' in html
    for name in (
        "state",
        "http",
        "projects_docs_tags",
        "schema_consistency",
        "jobs_sse",
        "layout",
        "presets_debug",
        "bootstrap",
    ):
        assert f'/assets/debug_ui.{name}.js' in html
