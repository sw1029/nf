from __future__ import annotations

from pathlib import Path
import re

import pytest


def _user_ui_html_text() -> str:
    return Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")


def _user_ui_asset_text() -> str:
    assets_dir = Path("modules/nf_orchestrator/assets")
    chunks: list[str] = []
    for path in sorted(assets_dir.glob("user_ui.*.js")):
        chunks.append(path.read_text(encoding="utf-8"))
    css_path = assets_dir / "user_ui.styles.css"
    if css_path.exists():
        chunks.append(css_path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _user_ui_bundle_text() -> str:
    return _user_ui_html_text() + "\n" + _user_ui_asset_text()


@pytest.mark.unit
def test_user_ui_search_renderer_uses_retrieval_evidence_shape() -> None:
    bundle = _user_ui_bundle_text()
    assert "evidence.snippet_text" in bundle
    assert "r.text.substring" not in bundle


@pytest.mark.unit
def test_user_ui_verdict_renderer_uses_current_api_fields() -> None:
    bundle = _user_ui_bundle_text()
    assert "claim_text" in bundle
    assert "reliability_overall" in bundle
    assert "unknown_reasons" in bundle
    assert "analysis-card.unknown" in bundle
    assert "v.claim ||" not in bundle


@pytest.mark.unit
def test_user_ui_fetches_verdict_detail_endpoint() -> None:
    bundle = _user_ui_bundle_text()
    assert "/query/verdicts/${encodeURIComponent(vid)}?project_id=${encodeURIComponent(state.projectId)}" in bundle


@pytest.mark.unit
def test_user_ui_export_formats_match_backend_contract() -> None:
    html = _user_ui_html_text()
    assert 'name="export-fmt" value="txt"' in html
    assert 'name="export-fmt" value="docx"' in html
    assert 'name="export-fmt" value="json"' not in html


@pytest.mark.unit
def test_user_ui_has_background_consistency_hooks() -> None:
    bundle = _user_ui_bundle_text()
    assert "_segmentTextForConsistency" in bundle
    assert "pendingConsistencySegments" in bundle
    assert "scheduleBackgroundConsistencyCheck" in bundle
    assert "runBackgroundConsistencyCheck" in bundle
    assert "toggle-show-ok" in bundle


@pytest.mark.unit
def test_user_ui_exposes_advanced_consistency_controls() -> None:
    html = _user_ui_html_text()
    assert "consistency-filter-entity" in html
    assert "consistency-filter-time" in html
    assert "consistency-filter-timeline" in html
    assert "consistency-graph-mode" in html
    assert "consistency-layer3-promotion" in html
    assert "consistency-verifier-mode" in html
    assert "consistency-triage-mode" in html
    assert "consistency-loop-enabled" in html


@pytest.mark.unit
def test_user_ui_consistency_mode_contract_values_and_checkbox_sync() -> None:
    html = _user_ui_html_text()
    bundle = _user_ui_bundle_text()
    assert '<option value="auto">' in html
    assert '<option value="manual">' in html
    assert '<option value="conservative_nli">' in html
    assert '<option value="embedding_anomaly">' in html
    assert "layer3Input.checked" in bundle
    assert "loopInput.checked" in bundle
    assert "value === 'on'" not in bundle


@pytest.mark.unit
def test_user_ui_supports_whitelist_ignore_and_inline_highlight() -> None:
    bundle = _user_ui_bundle_text()
    assert "markVerdictAsWhitelisted" in bundle
    assert "markVerdictAsIgnored" in bundle
    assert "renderInlineVerdictHighlights" in bundle
    assert "::highlight(nf-violate)" in bundle
    assert "::highlight(nf-unknown)" in bundle


@pytest.mark.unit
def test_user_ui_verdict_detail_renders_fact_paths() -> None:
    bundle = _user_ui_bundle_text()
    assert "fact_paths" in bundle
    assert "CONTRADICT" in bundle
    assert "CONTRADICT evidence link missing" not in bundle


@pytest.mark.unit
def test_user_ui_wait_for_job_prefers_sse_and_falls_back_to_polling() -> None:
    bundle = _user_ui_bundle_text()
    assert "_waitForJobViaSse" in bundle
    assert "_waitForJobByPolling" in bundle
    assert "EventSource" in bundle
    assert "/jobs/${encodeURIComponent(jobId)}/events" in bundle


@pytest.mark.unit
def test_user_ui_assets_and_inline_handler_exports_exist() -> None:
    html = _user_ui_html_text()
    assert '/assets/user_ui.styles.css' in html
    for name in (
        "state",
        "api",
        "editor",
        "docs_tree",
        "assistant",
        "jobs",
        "bootstrap",
    ):
        assert f'/assets/user_ui.{name}.js' in html

    bootstrap = Path("modules/nf_orchestrator/assets/user_ui.bootstrap.js").read_text(encoding="utf-8")
    for handler in (
        "window.closeExportModal",
        "window.createNewDoc",
        "window.handleInput",
        "window.runAssistantAction",
        "window.toggleJobsPanel",
    ):
        assert handler in bootstrap


@pytest.mark.unit
def test_user_ui_function_declarations_have_no_duplicates_after_split() -> None:
    assets_text = _user_ui_asset_text()
    names = re.findall(r"^\s*function\s+([A-Za-z_$][\w$]*)\s*\(", assets_text, flags=re.M)
    assert names
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    assert not duplicates
