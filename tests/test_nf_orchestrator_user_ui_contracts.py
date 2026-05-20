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
    state_js = Path("modules/nf_orchestrator/assets/user_ui.state.js").read_text(encoding="utf-8")
    assert '/assets/user_ui.styles.css' in html
    assert "var state = {" in state_js
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
        "window.closeLeftSidebar",
        "window.cancelDocDialog",
        "window.cancelDocMetaDialog",
        "window.createNewDoc",
        "window.handleDocMetaGroupSelectChange",
        "window.handleInput",
        "window.handleTimelineDrop",
        "window.handleTimelinePointerDown",
        "window.moveTimelineDoc",
        "window.moveTimelineDocToPosition",
        "window.runAssistantAction",
        "window.submitDocDialog",
        "window.submitDocMetaDialog",
        "window.openDocMetaDialog",
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
    assert "function _isCompositionEvent(event)" in bundle
    assert "event?.keyCode === 229" in bundle
    assert "if (_isCompositionEvent(event)) return;" in bundle
    assert "pendingRepaginateAfterComposition = true;" in bundle
    assert 'editorHost.addEventListener(' in bundle
    assert '"compositionstart"' in bundle
    assert '"compositionend"' in bundle
    assert '"compositioncancel"' in bundle


@pytest.mark.unit
def test_user_ui_load_doc_updates_status_and_page_guides() -> None:
    docs_tree = Path("modules/nf_orchestrator/assets/user_ui.docs_tree.js").read_text(encoding="utf-8")
    editor = Path("modules/nf_orchestrator/assets/user_ui.editor.js").read_text(encoding="utf-8")
    assert "loadMemosFromMetadata(loadedMeta.ui_memos || [])" in docs_tree
    assert "updateStatusBar()" in docs_tree
    assert "schedulePageGuideRender()" in docs_tree
    assert 'if (typeof updateStatusBar === "function") updateStatusBar();' in editor
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
    assert ".sidebar.mobile-open {" in css
    assert "z-index: 55;" in css
    assert "z-index: 110;" in css
    assert "scrollbar-gutter: stable both-edges;" in css
    assert "classList.toggle(\"is-open\", open)" in api
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
    assert 'onclick="closeRightSidebar(event)"' in html
    assert 'aria-label="작가 도우미 닫기"' in html
    assert "assistant-close-btn" in html
    assert 'id="assistant-sidebar" aria-hidden="true" inert' in html
    assert "function switchNavTab(eventOrType, maybeType)" in docs_tree
    assert "function switchAssistTab(eventOrMode, maybeMode)" in assistant
    assert "eventObj.payload && typeof eventObj.payload === \"object\"" in assistant
    assert "function _setRightSidebarOpen(open)" in api
    assert "sb.setAttribute(\"aria-hidden\", open ? \"false\" : \"true\")" in api
    assert "sb.inert = !open;" in api
    assert "function openRightSidebar()" in api
    assert "function closeRightSidebar(event)" in api
    assert 'sb.classList.remove("mobile-open")' in api
    assert 'event.stopPropagation()' in api
    assert 'if (event.key !== "Escape") return;' in api


@pytest.mark.unit
def test_user_ui_assistant_panel_has_modern_control_contracts() -> None:
    html = _user_ui_html_text()
    css = Path("modules/nf_orchestrator/assets/user_ui.styles.css").read_text(encoding="utf-8")
    assistant = Path("modules/nf_orchestrator/assets/user_ui.assistant.js").read_text(encoding="utf-8")

    assert "assistant-control-panel" in html
    assert "assistant-panel-intro" in html
    assert "assistant-search-query" in html
    assert "assistant-search-episodes" in html
    assert "assistant-search-settings" in html
    assert '<details class="assistant-advanced" open>' in html
    assert "맞춤법 중심" in html
    assert "분위기 강화" in html
    assert "표사" not in html
    assert ".assistant-control-panel" in css
    assert ".assistant-result-card" in css
    assert ".assistant-empty-state" in css
    assert "overscroll-behavior: contain" in css
    assert "#assistant-sidebar .assistant-control-panel" in css
    assert "#assistant-sidebar .assistant-results" in css
    assert "overflow: visible" in css
    assert "z-index: 35" in css
    assert "min-height: 44px" in css
    assert '.assistant-toggle-row input[type="checkbox"]' in css
    assert '.check-mode-label input[type="radio"]' in css
    assert "min-width: 22px" in css
    assert ".check-mode-label:has(input:checked)" in css
    assert "function _setAssistantEmptyState(mode)" in assistant
    assert "검색어를 입력하고 실행하세요" in assistant
    assert "다듬을 방향을 선택하세요" in assistant
    assert "function _readAssistantSearchQuery()" in assistant
    assert "function _assistantDocAllowedBySearchScope(docId)" in assistant
    assert "검색 실행" in assistant
    assert "문장 다듬기" in assistant


@pytest.mark.unit
def test_user_ui_mobile_doc_selection_closes_sidebar_and_caps_timeline_render() -> None:
    docs_tree = Path("modules/nf_orchestrator/assets/user_ui.docs_tree.js").read_text(encoding="utf-8")
    css = Path("modules/nf_orchestrator/assets/user_ui.styles.css").read_text(encoding="utf-8")
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    jobs = Path("modules/nf_orchestrator/assets/user_ui.jobs.js").read_text(encoding="utf-8")

    assert "const TIMELINE_RENDER_LIMIT = 200;" in docs_tree
    assert "displayDocs.slice(0, TIMELINE_RENDER_LIMIT)" in docs_tree
    assert "timeline-overflow-note" in docs_tree
    assert "function showDocDialog({" in docs_tree
    assert "closeMobileLeftSidebarIfOpen();" in docs_tree
    assert "function submitDocDialog(event)" in docs_tree
    assert "function cancelDocDialog()" in docs_tree
    assert "function hideCtxMenu()" in docs_tree
    assert "e.target.closest?.(\".menu-btn\")" in docs_tree
    assert "menu.dataset.owner = ownerKey;" in docs_tree
    assert "const ownerKey = `doc:${docId}`;" in docs_tree
    assert "const ownerKey = `group:${groupName}`;" in docs_tree
    assert "menu.dataset.owner === ownerKey" in docs_tree
    assert "getBoundingClientRect()" in docs_tree
    assert "window.innerWidth - rect.width - 8" in docs_tree
    assert "showCtxMenu(triggerRect.right + 6, triggerRect.top, options, ownerKey)" in docs_tree
    assert "prompt(" not in docs_tree
    assert "confirm(" not in docs_tree
    assert "await showDocDialog({" in docs_tree
    assert "title: \"새 챕터\"" in docs_tree
    assert "title: \"이름 변경\"" in docs_tree
    assert "챕터/회차 변경" in docs_tree
    assert "function openDocMetaDialog(docId)" in docs_tree
    assert "function submitDocMetaDialog(event)" in docs_tree
    assert "doc-meta-group-select" in html
    assert "doc-meta-episode-input" in html
    assert "doc-meta-btn" in css
    assert "episode-chip" in css
    assert "title: \"챕터 이름 변경\"" in docs_tree
    assert "title: \"문서 삭제\"" in docs_tree
    assert "function closeMobileLeftSidebarIfOpen()" in docs_tree
    assert "function setEditorDocumentActive(active)" in docs_tree
    assert "main.classList.toggle(\"has-active-doc\", isActive)" in docs_tree
    assert "toolbar.inert = !isActive;" in docs_tree
    assert "toolbar.setAttribute(\"aria-hidden\", isActive ? \"false\" : \"true\")" in docs_tree
    assert "setEditorDocumentActive(false);" in docs_tree
    assert "setEditorDocumentActive(true);" in docs_tree
    assert "function closeLeftSidebar(event)" in jobs
    assert "function _setMainContentBlockedByLeftSidebar(open)" in jobs
    assert "closeButton.focus({ preventScroll: true });" in jobs
    assert "main.setAttribute(\"aria-hidden\", \"true\")" in jobs
    assert "main.inert = blocked;" in jobs
    assert "window.addEventListener(\"resize\"" in jobs
    assert "closeLeftSidebar();" in docs_tree
    assert "event.stopPropagation();" in jobs
    assert "sidebar.classList.remove(\"mobile-open\")" in docs_tree
    assert 'class="mobile-sidebar-close"' in html
    assert 'onpointerdown="closeLeftSidebar(event)"' in html
    assert "closeMobileLeftSidebarIfOpen();" in docs_tree
    assert "await loadDoc(res.document.doc_id);" in docs_tree
    assert "height: 100vh;" in css
    assert "transform: translateX(-100%);" in css
    assert "transition: transform 0.3s ease;" in css
    assert "z-index: 160;" in css
    assert "z-index: 110;" in css
    assert ".main-content.has-active-doc .editor-toolbar" in css
    assert ".main-content:not(.has-active-doc) .editor-toolbar" in css
    assert "/* Editor Docked Toolbar */" in css
    assert "align-self: center;" in css
    assert "flex: 0 0 auto;" in css
    assert "max-width: min(90%, 640px);" in css
    assert "pointer-events: none;" in css
    assert "pointer-events: auto;" in css
    assert "max-width: calc(100% - 20px);" in css
    assert "display: none;" in css
    assert ".doc-action-modal" in css
    assert ".doc-action-dialog-input" in css
    assert ".sidebar.mobile-open ~ .main-content" in css
    assert "background: rgba(249, 249, 248, 0.96);" in css
    assert "z-index: 120;" in css
    assert "isolation: isolate;" in css
    assert "visibility: hidden !important;" in css
    assert ".mobile-sidebar-close:hover ~ .sidebar-title" in css
    assert ".sidebar.mobile-open .sidebar-header" in css
    assert "display: grid;" in css
    assert "grid-template-columns: minmax(0, 1fr) 32px;" in css
    assert "grid-column: 2;" in css
    assert "transform: translateX(-3px);" in css
    assert "@media (max-width: 420px) and (orientation: portrait)" in css
    assert "width: min(88vw, 300px);" in css
    assert ".sidebar.mobile-open {\n          transform: translateX(0);" in css
    assert "grid-template-columns: minmax(0, 1fr) 30px;" in css
    assert "padding: 16px 10px 14px 16px;" in css
    assert "sidebar-title-portrait-settle" in css
    assert "font-size: clamp(1rem, 4.8vw, 1.12rem);" in css
    assert "touch-action: manipulation;" in css
    assert ".timeline-overflow-note" in css
    assert ".mobile-sidebar-close" in css
    assert 'id="editor-toolbar" class="editor-toolbar" aria-hidden="true" inert' in html
    assert 'id="doc-action-dialog" class="overlay" aria-hidden="true"' in html
    assert 'onsubmit="submitDocDialog(event)"' in html
    assert 'onclick="cancelDocDialog()"' in html


@pytest.mark.unit
def test_user_ui_timeline_order_controls_patch_timeline_index() -> None:
    docs_tree = Path("modules/nf_orchestrator/assets/user_ui.docs_tree.js").read_text(encoding="utf-8")
    css = Path("modules/nf_orchestrator/assets/user_ui.styles.css").read_text(encoding="utf-8")
    bootstrap = Path("modules/nf_orchestrator/assets/user_ui.bootstrap.js").read_text(encoding="utf-8")

    assert "function moveTimelineDoc(event, docId, direction)" in docs_tree
    assert "function moveTimelineDocToPosition(event, docId, rawPosition)" in docs_tree
    assert "function handleTimelineDragStart(event, docId)" in docs_tree
    assert "function handleTimelineDrop(event, targetDocId)" in docs_tree
    assert "function handleTimelinePointerDown(event, docId)" in docs_tree
    assert "function handleTimelineItemClick(event, docId)" in docs_tree
    assert "elementFromPoint(event.clientX, event.clientY)" in docs_tree
    assert "function _getTimelineDisplayDocs()" in docs_tree
    assert "function _buildTimelineMoveUpdates(displayDocs, currentIdx, targetIdx)" in docs_tree
    assert "timeline_idx: update.timeline_idx" in docs_tree
    assert 'draggable="true"' in docs_tree
    assert "onpointerdown=\"handleTimelinePointerDown(event, '${doc.doc_id}')\"" in docs_tree
    assert 'class="timeline-position-input"' in docs_tree
    assert 'class="timeline-jump-btn"' in docs_tree
    assert "this.previousElementSibling.value" in docs_tree
    assert "moveTimelineDoc(event, '${doc.doc_id}', -1)" in docs_tree
    assert "moveTimelineDoc(event, '${doc.doc_id}', 1)" in docs_tree
    assert "timeline-order-btn" in docs_tree
    assert "timeline-drag-handle" in docs_tree
    assert ".timeline-title-row" in css
    assert ".timeline-order-btn" in css
    assert ".timeline-drag-handle" in css
    assert ".timeline-position-input" in css
    assert ".timeline-jump-btn" in css
    assert "window.moveTimelineDoc = moveTimelineDoc;" in bootstrap
    assert "window.moveTimelineDocToPosition = moveTimelineDocToPosition;" in bootstrap
    assert "window.handleTimelinePointerDown = handleTimelinePointerDown;" in bootstrap


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
