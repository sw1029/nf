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
def test_user_ui_exposes_consistency_preset_controls() -> None:
    html = _user_ui_html_text()
    assert "consistency-filter-entity" in html
    assert "consistency-filter-time" in html
    assert "consistency-filter-timeline" in html
    assert 'name="consistency-level"' in html
    assert 'value="quick"' in html
    assert 'value="deep"' in html
    assert 'value="strict"' in html
    assert "consistency-level-group" in html
    assert "consistency-graph-mode" not in html
    assert "consistency-layer3-promotion" not in html
    assert "consistency-verifier-mode" not in html
    assert "consistency-triage-mode" not in html
    assert "consistency-loop-enabled" not in html


@pytest.mark.unit
def test_user_ui_consistency_mode_contract_values_from_level_presets() -> None:
    bundle = _user_ui_bundle_text()
    assert "function _readConsistencyOptionsFromUi()" in bundle
    assert 'if (selectedLevel === "deep") {' in bundle
    assert 'graphMode = "auto";' in bundle
    assert 'triageMode = "embedding_anomaly";' in bundle
    assert 'if (selectedLevel === "strict") {' in bundle
    assert 'verifierMode = "conservative_nli";' in bundle
    assert "verificationLoop = true;" in bundle
    assert "layer3_verdict_promotion: layer3Promotion" in bundle
    assert "verification_loop: {" in bundle
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
    assert "SSE_IDLE_TIMEOUT_MS = 30000" in bundle
    assert "JOB_TOTAL_TIMEOUT_MS = 300000" in bundle


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
    assert "window.handleExport = handleJobExport;" in bootstrap


@pytest.mark.unit
def test_user_ui_retry_worker_and_segment_rules_contracts() -> None:
    bundle = _user_ui_bundle_text()
    assert "/jobs/${encodeURIComponent(jobId)}/retry" in bundle
    assert "프론트엔드 모의" not in bundle
    assert "/assets/user_ui.pagination.worker.js" in bundle
    assert "/query/segment-rules" in bundle


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


@pytest.mark.unit
def test_user_ui_memo_metadata_anchor_contract() -> None:
    bundle = _user_ui_bundle_text()
    assert "ui_memos" in bundle
    assert "serializeMemosForMetadata" in bundle
    assert "loadMemosFromMetadata" in bundle
    assert "syncMemoAnchorsFromDom" in bundle


@pytest.mark.unit
def test_user_ui_has_composition_handler_binding() -> None:
    bundle = _user_ui_bundle_text()
    assert "function handleComposition(active)" in bundle
    assert 'editorHost.addEventListener(' in bundle
    assert '"compositionstart"' in bundle
    assert '"compositionend"' in bundle


@pytest.mark.unit
def test_user_ui_load_doc_updates_status_and_page_guides() -> None:
    docs_tree = Path("modules/nf_orchestrator/assets/user_ui.docs_tree.js").read_text(encoding="utf-8")
    editor = Path("modules/nf_orchestrator/assets/user_ui.editor.js").read_text(encoding="utf-8")
    assert "loadMemosFromMetadata(loadedMeta.ui_memos || [])" in docs_tree
    assert "updateStatusBar()" in docs_tree
    assert "schedulePageGuideRender()" in docs_tree
    assert "function renderPageGuides()" in editor


@pytest.mark.unit
def test_user_ui_paged_editor_and_overlay_sidebar_contract() -> None:
    html = _user_ui_html_text()
    editor = Path("modules/nf_orchestrator/assets/user_ui.editor.js").read_text(encoding="utf-8")
    css = Path("modules/nf_orchestrator/assets/user_ui.styles.css").read_text(encoding="utf-8")
    api = Path("modules/nf_orchestrator/assets/user_ui.api.js").read_text(encoding="utf-8")
    assert 'id="editor" class="editor-pages"' in html
    assert 'pageEl.className = "paper page-editor"' in editor
    assert 'gap.className = "page-gap"' in editor
    assert "gap.contentEditable = \"false\"" in editor
    assert "function getEditorText()" in editor
    assert "function setEditorText(text, opts = {})" in editor
    assert "function paginateText(text)" in editor
    assert "function captureSelectionGlobalOffset()" in editor
    assert "function restoreSelectionGlobalOffset(offset)" in editor
    assert "function layoutMemoSidebar()" in editor
    assert "assistantSidebar.classList.contains(\"is-open\")" in editor
    assert "window.layoutMemoSidebar = layoutMemoSidebar;" in editor
    assert ".editor-pages {" in css
    assert ".page-editor {" in css
    assert ".page-gap {" in css
    assert ".sidebar.right.is-open {" in css
    assert "scrollbar-gutter: stable both-edges;" in css
    assert "classList.toggle(\"is-open\")" in api
    assert "layoutMemoSidebar()" in api
    assert "renderMemos()" in api
    assert "schedulePageGuideRender()" in api


@pytest.mark.unit
def test_user_ui_sidebar_and_tab_handlers_use_explicit_event_and_open_close_contract() -> None:
    html = _user_ui_html_text()
    docs_tree = Path("modules/nf_orchestrator/assets/user_ui.docs_tree.js").read_text(encoding="utf-8")
    assistant = Path("modules/nf_orchestrator/assets/user_ui.assistant.js").read_text(encoding="utf-8")
    api = Path("modules/nf_orchestrator/assets/user_ui.api.js").read_text(encoding="utf-8")

    assert "switchNavTab(event, 'EPISODE')" in html
    assert "switchAssistTab(event, 'CHECK')" in html
    assert 'onclick="openRightSidebar()"' in html
    assert 'onclick="closeRightSidebar()"' in html
    assert "function switchNavTab(eventOrType, maybeType)" in docs_tree
    assert "function switchAssistTab(eventOrMode, maybeMode)" in assistant
    assert "function openRightSidebar()" in api
    assert "function closeRightSidebar()" in api
    assert 'if (event.key !== "Escape") return;' in api


@pytest.mark.unit
def test_user_ui_enter_and_popover_positioning_contract() -> None:
    editor = Path("modules/nf_orchestrator/assets/user_ui.editor.js").read_text(encoding="utf-8")
    assistant = Path("modules/nf_orchestrator/assets/user_ui.assistant.js").read_text(encoding="utf-8")
    api = Path("modules/nf_orchestrator/assets/user_ui.api.js").read_text(encoding="utf-8")

    assert 'if (event.key === "Enter") {' in editor
    assert "_insertPlainNewlineAtCaret()" in editor
    assert "positionPopoverInMainContent" in editor
    assert "window.repositionInlineTagWidget = repositionInlineTagWidget;" in editor
    assert "window.repositionTagRemovePopover = repositionTagRemovePopover;" in editor
    assert "window.repositionActionPopover = repositionActionPopover;" in assistant
    assert "function positionPopoverInMainContent(popover, anchorRect, opts = {})" in api
