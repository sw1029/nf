// --- UI Helpers & Init ---
const MEMO_METADATA_KEY = "ui_memos";
const DEFAULT_MEMO_COLOR = "yellow";
const MEMO_COLORS = {
  yellow: { bg: "rgba(245, 158, 11, 0.15)", border: "#f59e0b", hoverBg: "rgba(245, 158, 11, 0.3)" },
  blue: { bg: "rgba(59, 130, 246, 0.15)", border: "#3b82f6", hoverBg: "rgba(59, 130, 246, 0.3)" },
  green: { bg: "rgba(16, 185, 129, 0.15)", border: "#10b981", hoverBg: "rgba(16, 185, 129, 0.3)" },
  pink: { bg: "rgba(236, 72, 153, 0.15)", border: "#ec4899", hoverBg: "rgba(236, 72, 153, 0.3)" },
};

let iconsUpdateFrame = null;

function _nowIso() {
  return new Date().toISOString();
}

function _escapeMemoHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function _safeMemoColor(raw) {
  const key = String(raw || "").trim();
  return Object.prototype.hasOwnProperty.call(MEMO_COLORS, key)
    ? key
    : DEFAULT_MEMO_COLOR;
}

function _setSaveStatus(text, color) {
  const toolbarStatus = document.getElementById("save-status");
  if (toolbarStatus) {
    toolbarStatus.innerText = text;
    if (color) toolbarStatus.style.color = color;
  }

  const statusBarStatus = document.getElementById("save-status-text");
  if (statusBarStatus) {
    statusBarStatus.innerText = text;
    if (color) statusBarStatus.style.color = color;
  }
}

function updateIcons() {
  if (!window.lucide || typeof window.lucide.createIcons !== "function") {
    return;
  }
  if (iconsUpdateFrame !== null) return;
  iconsUpdateFrame = requestAnimationFrame(() => {
    iconsUpdateFrame = null;
    window.lucide.createIcons();
  });
}

function _getPageHeightPx(editor) {
  if (!editor) return 1122;
  const style = window.getComputedStyle(editor);
  const raw = style.getPropertyValue("--a4-page-height");
  const parsed = Number.parseFloat(raw);
  if (Number.isFinite(parsed) && parsed > 200) return parsed;
  return 1122;
}

let repaginateFrame = null;
let pageMeasureEl = null;
let pendingRepaginateAfterComposition = false;
let floatingPopoverFrame = null;
let paginationWorker = null;
let paginationWorkerSeq = 0;
const PAGINATION_WORKER_TEXT_THRESHOLD = 4000;

function _normalizeEditorText(value) {
  return String(value ?? "").replace(/\r\n/g, "\n");
}

function _getPageNodes(editor) {
  if (!editor) return [];
  return Array.from(editor.querySelectorAll(".page-editor"));
}

function _readPageText(page) {
  if (!page) return "";
  const range = document.createRange();
  range.selectNodeContents(page);
  return _normalizeEditorText(range.toString());
}

function _getEditorTextFromPages(editor) {
  const pages = _getPageNodes(editor);
  if (!pages.length) {
    return _normalizeEditorText(editor?.innerText || "");
  }
  return pages.map((page) => _readPageText(page)).join("");
}

function _computeRenderedPageCount(editor) {
  if (!editor) return 1;
  const pages = _getPageNodes(editor);
  if (pages.length > 0) return pages.length;
  const pageHeight = _getPageHeightPx(editor);
  const contentHeight = Math.max(pageHeight, editor.scrollHeight || 0);
  return Math.max(1, Math.ceil(contentHeight / pageHeight));
}

function _getScrollbarWidth(target) {
  if (!target) return 0;
  return Math.max(0, target.offsetWidth - target.clientWidth);
}

function _readRootVarPx(name, fallback) {
  const raw = window.getComputedStyle(document.documentElement).getPropertyValue(name);
  const parsed = Number.parseFloat(raw);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return fallback;
}

function _getPageMetrics(editor) {
  const pageHeight = _getPageHeightPx(editor);
  const samplePage = editor ? editor.querySelector(".page-editor") : null;
  const sampleStyle = samplePage ? window.getComputedStyle(samplePage) : null;

  const paddingTop = sampleStyle
    ? Number.parseFloat(sampleStyle.paddingTop) || 60
    : 60;
  const paddingBottom = sampleStyle
    ? Number.parseFloat(sampleStyle.paddingBottom) || 60
    : 60;
  const paddingLeft = sampleStyle
    ? Number.parseFloat(sampleStyle.paddingLeft) || 80
    : 80;
  const paddingRight = sampleStyle
    ? Number.parseFloat(sampleStyle.paddingRight) || 80
    : 80;

  const pageWidth = Math.max(300, editor?.clientWidth || _readRootVarPx("--a4-page-width", 800));
  const contentWidth = Math.max(180, pageWidth - paddingLeft - paddingRight);
  const innerHeight = Math.max(120, pageHeight - paddingTop - paddingBottom);

  return {
    pageHeight,
    pageWidth,
    contentWidth,
    innerHeight,
    paddingTop,
    paddingBottom,
    paddingLeft,
    paddingRight,
  };
}

function _ensurePageMeasureEl(metrics, editor) {
  if (!pageMeasureEl) {
    pageMeasureEl = document.createElement("div");
    pageMeasureEl.id = "editor-page-measure";
    pageMeasureEl.setAttribute("aria-hidden", "true");
    pageMeasureEl.style.position = "fixed";
    pageMeasureEl.style.left = "-99999px";
    pageMeasureEl.style.top = "-99999px";
    pageMeasureEl.style.visibility = "hidden";
    pageMeasureEl.style.pointerEvents = "none";
    pageMeasureEl.style.whiteSpace = "pre-wrap";
    pageMeasureEl.style.wordBreak = "break-word";
    pageMeasureEl.style.overflowWrap = "anywhere";
    document.body.appendChild(pageMeasureEl);
  }

  const samplePage = editor ? editor.querySelector(".page-editor") : null;
  const style = samplePage ? window.getComputedStyle(samplePage) : window.getComputedStyle(document.documentElement);
  pageMeasureEl.style.width = `${metrics.contentWidth}px`;
  pageMeasureEl.style.fontFamily = style.fontFamily || "inherit";
  pageMeasureEl.style.fontSize = style.fontSize || "18px";
  pageMeasureEl.style.lineHeight = style.lineHeight || "1.8";
  pageMeasureEl.style.letterSpacing = style.letterSpacing || "0px";
  pageMeasureEl.style.fontWeight = style.fontWeight || "400";
}

function _sliceFitsPage(text, start, end, metrics) {
  const content = text.slice(start, end);
  if (content.length === 0) {
    pageMeasureEl.innerHTML = "<br>";
  } else {
    pageMeasureEl.textContent = content;
    if (content.endsWith("\n")) {
      pageMeasureEl.appendChild(document.createElement("br"));
    }
  }
  return pageMeasureEl.scrollHeight <= metrics.innerHeight + 0.5;
}

function _snapBreakPoint(text, start, candidate) {
  const min = Math.max(start + 1, candidate - 220);
  for (let idx = candidate; idx > min; idx -= 1) {
    const ch = text[idx - 1];
    if (ch === "\n") return idx;
    if (/\s/.test(ch)) return idx;
    if (/[,.!?;:。！？]/.test(ch)) return idx;
  }
  return candidate;
}

function _updatePageCharBudget(textLength, pageCount) {
  const oldBudget = Number.parseInt(String(state.pageCharBudget ?? ""), 10);
  const baseline = Number.isInteger(oldBudget) && oldBudget > 0 ? oldBudget : 1800;
  const safePages = Math.max(1, Number.isInteger(pageCount) ? pageCount : 1);
  const observed = Math.max(1, Math.round(textLength / safePages));
  const next = Math.round(0.8 * baseline + 0.2 * observed);
  state.pageCharBudget = Math.max(600, Math.min(6000, next));
}

function _hasPageOverflow() {
  const editor = document.getElementById("editor");
  if (!editor) return false;
  const pages = _getPageNodes(editor);
  return pages.some((page) => page.scrollHeight > page.clientHeight + 1);
}

function _getPaginationWorker() {
  if (!state.usePaginationWorker) return null;
  if (typeof Worker === "undefined") return null;
  if (paginationWorker) return paginationWorker;
  try {
    paginationWorker = new Worker("/assets/user_ui.pagination.worker.js");
  } catch (error) {
    console.warn("pagination worker unavailable", error);
    paginationWorker = null;
  }
  return paginationWorker;
}

function _sanitizeWorkerPages(text, rawPages) {
  const list = Array.isArray(rawPages) ? rawPages : [];
  const totalLen = text.length;
  const normalized = list
    .map((page) => {
      const start = Number.parseInt(String(page?.start ?? ""), 10);
      const end = Number.parseInt(String(page?.end ?? ""), 10);
      if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
      const safeStart = Math.max(0, Math.min(totalLen, start));
      const safeEnd = Math.max(safeStart, Math.min(totalLen, end));
      return {
        start: safeStart,
        end: safeEnd,
        text: text.slice(safeStart, safeEnd),
      };
    })
    .filter((page) => page && page.end > page.start);
  if (normalized.length === 0) {
    return [{ start: 0, end: 0, text: "" }];
  }
  return normalized;
}

function _paginateTextViaWorker(text, requestId) {
  const worker = _getPaginationWorker();
  if (!worker) return Promise.resolve(null);
  const normalized = _normalizeEditorText(text);
  const budgetRaw = Number.parseInt(String(state.pageCharBudget ?? ""), 10);
  const budget = Number.isInteger(budgetRaw) && budgetRaw > 0 ? budgetRaw : 1800;
  return new Promise((resolve) => {
    const onMessage = (event) => {
      const data = event?.data || {};
      if (data.request_id !== requestId) return;
      worker.removeEventListener("message", onMessage);
      worker.removeEventListener("error", onError);
      const pages = _sanitizeWorkerPages(normalized, data.pages);
      resolve(pages);
    };
    const onError = () => {
      worker.removeEventListener("message", onMessage);
      worker.removeEventListener("error", onError);
      resolve(null);
    };
    worker.addEventListener("message", onMessage);
    worker.addEventListener("error", onError);
    worker.postMessage({
      request_id: requestId,
      text: normalized,
      page_char_budget: budget,
      break_chars: [".", ",", "!", "?", ";", ":", "。", "！", "？"],
    });
  });
}

function paginateText(text) {
  const editor = document.getElementById("editor");
  const normalized = _normalizeEditorText(text);
  const metrics = _getPageMetrics(editor);
  _ensurePageMeasureEl(metrics, editor);

  if (!normalized.length) {
    return [{ start: 0, end: 0, text: "" }];
  }

  const pages = [];
  let cursor = 0;
  const totalLen = normalized.length;

  while (cursor < totalLen) {
    let low = cursor + 1;
    let high = totalLen;
    let best = cursor + 1;

    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      if (_sliceFitsPage(normalized, cursor, mid, metrics)) {
        best = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }

    const candidateEnd = Math.max(cursor + 1, Math.min(totalLen, best));
    const adjustedEnd =
      candidateEnd < totalLen
        ? _snapBreakPoint(normalized, cursor, candidateEnd)
        : candidateEnd;

    const pageEnd = Math.max(cursor + 1, adjustedEnd);
    pages.push({
      start: cursor,
      end: pageEnd,
      text: normalized.slice(cursor, pageEnd),
    });
    cursor = pageEnd;
  }

  return pages.length ? pages : [{ start: 0, end: 0, text: "" }];
}

function captureSelectionGlobalOffset() {
  const editor = document.getElementById("editor");
  const selection = window.getSelection();
  if (!editor || !selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!editor.contains(range.startContainer)) return null;
  const offset = _offsetForPosition(editor, range.startContainer, range.startOffset);
  state.selectionOffset = Number.isInteger(offset) ? offset : null;
  return state.selectionOffset;
}

function restoreSelectionGlobalOffset(offset) {
  const editor = document.getElementById("editor");
  if (!editor || !Number.isInteger(offset)) return false;
  const textNodes = _collectEditorTextNodesLocal(editor);
  const pos = _positionForOffsetLocal(textNodes, offset);
  if (!pos) return false;
  const selection = window.getSelection();
  if (!selection) return false;

  const range = document.createRange();
  range.setStart(pos.node, pos.offset);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);

  const page = pos.node.parentElement?.closest(".page-editor");
  if (page && typeof page.focus === "function") page.focus();
  state.selectionOffset = offset;
  return true;
}

function renderPagedEditor(pages) {
  const editor = document.getElementById("editor");
  if (!editor) return;
  const list = Array.isArray(pages) && pages.length
    ? pages
    : [{ start: 0, end: 0, text: "" }];
  const defaultPlaceholder = state.currentNavTab === "SETTING" ? "등장인물의 이름, 형태, 소속, 특징, 성격 등을 서술형이나 개조식으로 꼼꼼히 작성해 두면 AI가 정합성 점검 시 참고합니다..." :
    state.currentNavTab === "PLOT" ? "핵심 사건과 줄거리 라인을 작성하세요..." :
      "이야기를 펼쳐보세요...";
  const placeholder = editor.getAttribute("placeholder") || defaultPlaceholder;

  const fragment = document.createDocumentFragment();
  list.forEach((page, idx) => {
    const pageEl = document.createElement("div");
    pageEl.className = "paper page-editor";
    pageEl.contentEditable = "true";
    pageEl.dataset.pageIndex = String(idx);
    pageEl.dataset.start = String(Number.isInteger(page.start) ? page.start : 0);
    pageEl.dataset.end = String(Number.isInteger(page.end) ? page.end : 0);
    if (idx === 0) {
      pageEl.dataset.placeholder = "true";
      pageEl.setAttribute("placeholder", placeholder);
    }
    const pageText = typeof page.text === "string" ? page.text : "";
    pageEl.textContent = pageText;
    if (pageText === "" || pageText.endsWith("\n")) {
      pageEl.appendChild(document.createElement("br"));
    }
    fragment.appendChild(pageEl);

    if (idx < list.length - 1) {
      const gap = document.createElement("div");
      gap.className = "page-gap";
      gap.contentEditable = "false";
      gap.setAttribute("data-page-label", `${idx + 1} / ${list.length}`);
      fragment.appendChild(gap);
    }
  });

  editor.innerHTML = "";
  editor.appendChild(fragment);
  state.pageSlices = list.map((page) => ({
    start: Number.isInteger(page.start) ? page.start : 0,
    end: Number.isInteger(page.end) ? page.end : 0,
  }));
  state.currentPageCount = list.length;
  state.pageRenderVersion = Number(state.pageRenderVersion || 0) + 1;
}

function getEditorText() {
  const editor = document.getElementById("editor");
  if (!editor) return "";
  const next = _getEditorTextFromPages(editor);
  state.editorText = next;
  return next;
}

function setEditorText(text, opts = {}) {
  const preserveCaret = Boolean(opts.preserveCaret);
  const prevOffset = preserveCaret ? captureSelectionGlobalOffset() : null;
  const normalized = _normalizeEditorText(text);
  state.editorText = normalized;
  const pages = paginateText(normalized);
  renderPagedEditor(pages);
  if (Array.isArray(state.inlineTags) && state.inlineTags.length > 0) {
    _renderInlineTagsFromState();
  }
  if (preserveCaret && Number.isInteger(prevOffset)) {
    restoreSelectionGlobalOffset(prevOffset);
  }
  _scheduleMemoRender();
  renderPageGuides();
}

async function _repaginateFromDom(requestId) {
  const offset = captureSelectionGlobalOffset();
  const wasMemoDirty = Boolean(state.memoDirty);
  const wasInlineTagDirty = Boolean(state.inlineTagDirty);
  syncMemoAnchorsFromDom();
  syncInlineTagsFromDom();
  const memoSnapshot = state.memos.map((memo) => ({ ...memo }));
  const inlineTagSnapshot = state.inlineTags.map((tag) => ({ ...tag }));
  const normalized = getEditorText();

  const applyRenderedState = (pagesToRender) => {
    renderPagedEditor(pagesToRender);
    if (inlineTagSnapshot.length > 0) {
      state.inlineTags = inlineTagSnapshot;
      _renderInlineTagsFromState();
      state.inlineTagDirty = wasInlineTagDirty;
    }
    if (memoSnapshot.length > 0) {
      _loadMemosFromMetadata(memoSnapshot);
      state.memoDirty = wasMemoDirty;
    }
    if (Number.isInteger(offset)) restoreSelectionGlobalOffset(offset);
    _scheduleMemoRender();
    renderPageGuides();
  };

  const useWorkerPath =
    Boolean(state.usePaginationWorker) &&
    normalized.length >= PAGINATION_WORKER_TEXT_THRESHOLD;
  let pages = null;
  if (useWorkerPath) {
    pages = await _paginateTextViaWorker(normalized, requestId);
    if (requestId !== paginationWorkerSeq) return;
  }
  if (!Array.isArray(pages) || pages.length === 0) {
    pages = paginateText(normalized);
  }
  applyRenderedState(pages);
  _updatePageCharBudget(normalized.length, pages.length);

  if (useWorkerPath && _hasPageOverflow()) {
    const fallbackPages = paginateText(normalized);
    applyRenderedState(fallbackPages);
    _updatePageCharBudget(normalized.length, fallbackPages.length);
  }
}

function _scheduleRepaginateFromDom() {
  if (state.isComposing) {
    pendingRepaginateAfterComposition = true;
    return;
  }
  if (repaginateFrame !== null) return;
  repaginateFrame = requestAnimationFrame(() => {
    repaginateFrame = null;
    const requestId = ++paginationWorkerSeq;
    void _repaginateFromDom(requestId);
  });
}

function _isCollapsedSelectionIn(page) {
  const selection = window.getSelection();
  if (!selection || !selection.isCollapsed || selection.rangeCount === 0) {
    return false;
  }
  return page.contains(selection.anchorNode);
}

function _isCaretAtPageBoundary(page, expectEnd) {
  const selection = window.getSelection();
  if (!selection || !selection.isCollapsed || selection.rangeCount === 0) {
    return false;
  }
  const offset = _offsetForPosition(page, selection.anchorNode, selection.anchorOffset);
  if (!Number.isInteger(offset)) return false;
  const range = document.createRange();
  range.selectNodeContents(page);
  const total = range.toString().length;
  return expectEnd ? offset >= total : offset <= 0;
}

function _moveCaretToPageEdge(page, toEnd) {
  const textNodes = _collectEditorTextNodesLocal(page);
  const selection = window.getSelection();
  if (!selection) return;

  const range = document.createRange();
  if (!textNodes.length) {
    range.selectNodeContents(page);
    range.collapse(!toEnd);
  } else if (toEnd) {
    const tail = textNodes[textNodes.length - 1];
    range.setStart(tail, (tail.nodeValue || "").length);
    range.collapse(true);
  } else {
    const head = textNodes[0];
    range.setStart(head, 0);
    range.collapse(true);
  }

  selection.removeAllRanges();
  selection.addRange(range);
  if (typeof page.focus === "function") page.focus();
}

function _insertTextAtSelection(text) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return false;
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const node = document.createTextNode(String(text || ""));
  range.insertNode(node);
  range.setStart(node, node.nodeValue.length);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
  return true;
}

function _insertPlainNewlineAtCaret() {
  return _insertTextAtSelection("\n");
}

function _handlePaste(event) {
  const page = event.target?.closest?.(".page-editor");
  if (!page) return;

  event.preventDefault();

  let text = (event.clipboardData || window.clipboardData).getData("text/plain");
  if (!text) return;

  text = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  if (_insertTextAtSelection(text)) {
    if (typeof handleInput === "function") handleInput();
    _scheduleRepaginateFromDom();
    _scheduleFloatingPopoverReposition();
  }
}

function _scheduleFloatingPopoverReposition() {
  if (floatingPopoverFrame !== null) return;
  floatingPopoverFrame = requestAnimationFrame(() => {
    floatingPopoverFrame = null;
    if (typeof repositionInlineTagWidget === "function")
      repositionInlineTagWidget();
    if (typeof repositionTagRemovePopover === "function")
      repositionTagRemovePopover();
    if (typeof repositionActionPopover === "function")
      repositionActionPopover();
  });
}

function _handlePageBoundaryKeydown(event) {
  const page = event.target?.closest?.(".page-editor");
  if (!page || !_isCollapsedSelectionIn(page)) return;

  if (event.key === "Enter") {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    event.preventDefault();
    if (_insertPlainNewlineAtCaret()) {
      handleInput();
      _scheduleRepaginateFromDom();
      _scheduleFloatingPopoverReposition();
    }
    return;
  }

  if (event.key === "ArrowRight" || event.key === "ArrowDown") {
    if (!_isCaretAtPageBoundary(page, true)) return;
    const nextPage = page.nextElementSibling?.classList?.contains("page-gap")
      ? page.nextElementSibling.nextElementSibling
      : page.nextElementSibling;
    if (nextPage && nextPage.classList.contains("page-editor")) {
      event.preventDefault();
      _moveCaretToPageEdge(nextPage, false);
    }
    return;
  }

  if (event.key === "ArrowLeft" || event.key === "ArrowUp" || event.key === "Backspace") {
    if (!_isCaretAtPageBoundary(page, false)) return;
    const prevGap = page.previousElementSibling;
    const prevPage = prevGap && prevGap.classList.contains("page-gap")
      ? prevGap.previousElementSibling
      : page.previousElementSibling;
    if (prevPage && prevPage.classList.contains("page-editor")) {
      event.preventDefault();
      _moveCaretToPageEdge(prevPage, true);
    }
  }
}

function layoutMemoSidebar() {
  const sidebar = document.getElementById("memo-sidebar");
  const editor = document.getElementById("editor");
  const editorContainer = document.querySelector(".editor-container");
  if (!sidebar || !editor || !editorContainer) return false;
  const assistantSidebar = document.getElementById("assistant-sidebar");

  const minWidth = 180;
  const preferredWidth = 220;
  const maxWidth = 250;
  const laneGap = 10;
  const edgePadding = 10;
  const minVisibleWidth = 120;

  const scrollbarReserve = _getScrollbarWidth(editorContainer) + edgePadding;
  const editorRight = editor.offsetLeft + editor.offsetWidth;
  const laneStart = editorRight + laneGap;
  const assistantSidebarWidth =
    assistantSidebar && assistantSidebar.classList.contains("is-open")
      ? Math.max(0, assistantSidebar.offsetWidth || 320)
      : 0;
  const laneEnd =
    editorContainer.clientWidth - scrollbarReserve - assistantSidebarWidth;
  const availableWidth = laneEnd - laneStart;

  if (availableWidth < 80) {
    sidebar.style.display = "";
    sidebar.style.left = "auto";
    sidebar.style.right = `${scrollbarReserve + 10}px`;
    sidebar.style.width = `${preferredWidth}px`;
    return true;
  }

  let width = Math.min(maxWidth, Math.max(minWidth, availableWidth));
  if (availableWidth < minWidth) {
    width = Math.max(minVisibleWidth, availableWidth);
  } else {
    width = Math.min(width, Math.max(preferredWidth, minWidth));
  }

  sidebar.style.display = "";
  sidebar.style.left = `${laneStart}px`;
  sidebar.style.right = "auto";
  sidebar.style.width = `${Math.floor(width)}px`;
  return true;
}

function _scheduleSave(delayMs = 2000) {
  if (state.saveTimeout) {
    clearTimeout(state.saveTimeout);
    state.saveTimeout = null;
  }
  if (state.isComposing) return;
  state.saveTimeout = setTimeout(() => {
    state.saveTimeout = null;
    void saveDoc(false);
  }, delayMs);
}

function _scheduleMemoRender() {
  if (state.activeMemoRenderFrame !== null) return;
  state.activeMemoRenderFrame = requestAnimationFrame(() => {
    state.activeMemoRenderFrame = null;
    renderMemos();
  });
}

function schedulePageGuideRender() {
  if (state.pageGuideRenderScheduled) return;
  state.pageGuideRenderScheduled = true;
  requestAnimationFrame(() => {
    state.pageGuideRenderScheduled = false;
    renderPageGuides();
  });
}

function renderPageGuides() {
  const editor = document.getElementById("editor");
  const guides = document.getElementById("page-guides");
  if (!editor || !guides) return;
  guides.innerHTML = "";
  guides.style.left = `${editor.offsetLeft}px`;
  guides.style.top = `${editor.offsetTop}px`;
  guides.style.width = `${editor.offsetWidth}px`;
  guides.style.height = `${editor.scrollHeight}px`;
  state.currentPageCount = _computeRenderedPageCount(editor);
  layoutMemoSidebar();
}

function updateStatusBar() {
  const normalized = getEditorText();
  const charCount = normalized.length;
  const textWithoutSpaces = normalized.replace(/\s+/g, "").length;
  const pageCount = Math.max(1, Number(state.currentPageCount || 1));

  const charEl = document.getElementById("char-count");
  if (charEl)
    charEl.innerText = `${charCount}자 (공백제외 ${textWithoutSpaces}자)`;

  const pageEl = document.getElementById("page-count");
  if (pageEl) pageEl.innerText = `${pageCount} 쪽`;

  state.currentPageCount = pageCount;
  schedulePageGuideRender();
}

function _collectEditorTextNodesLocal(editor) {
  const nodes = [];
  const roots = _getPageNodes(editor);
  const targets = roots.length ? roots : [editor];
  targets.forEach((target) => {
    const walker = document.createTreeWalker(
      target,
      NodeFilter.SHOW_TEXT,
      null,
    );
    let node = walker.nextNode();
    while (node) {
      const value = node.nodeValue || "";
      if (value.length > 0) nodes.push(node);
      node = walker.nextNode();
    }
  });
  return nodes;
}

function _positionForOffsetLocal(textNodes, absoluteOffset) {
  if (!textNodes.length) return null;
  let consumed = 0;
  for (const node of textNodes) {
    const value = node.nodeValue || "";
    const nextConsumed = consumed + value.length;
    if (absoluteOffset <= nextConsumed) {
      return {
        node,
        offset: Math.max(0, Math.min(value.length, absoluteOffset - consumed)),
      };
    }
    consumed = nextConsumed;
  }
  const tail = textNodes[textNodes.length - 1];
  return { node: tail, offset: (tail.nodeValue || "").length };
}

function _offsetForPosition(root, node, offset) {
  if (!root || !node) return null;
  const range = document.createRange();
  range.selectNodeContents(root);
  try {
    range.setEnd(node, offset);
  } catch (_error) {
    return null;
  }
  return range.toString().length;
}

function _offsetsFromRange(root, range) {
  if (!root || !range) return null;
  const start = _offsetForPosition(root, range.startContainer, range.startOffset);
  const end = _offsetForPosition(root, range.endContainer, range.endOffset);
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  return {
    start: Math.min(start, end),
    end: Math.max(start, end),
  };
}

function _applyMemoSpanStyle(span, colorKey) {
  const safeColor = _safeMemoColor(colorKey);
  const palette = MEMO_COLORS[safeColor] || MEMO_COLORS[DEFAULT_MEMO_COLOR];
  span.dataset.color = safeColor;
  span.style.backgroundColor = palette.bg;
  span.style.borderBottom = `2px dashed ${palette.border}`;
}

function _normalizeMemoList(rawList, textLen = null) {
  const source = Array.isArray(rawList) ? rawList : [];
  const nowIso = _nowIso();
  const limit = Number.isInteger(textLen) ? Math.max(0, textLen) : null;

  const normalized = source
    .map((raw, idx) => {
      const startRaw = Number.parseInt(String(raw?.start ?? ""), 10);
      const endRaw = Number.parseInt(String(raw?.end ?? ""), 10);
      if (!Number.isInteger(startRaw) || !Number.isInteger(endRaw)) return null;

      let start = startRaw;
      let end = endRaw;
      if (limit !== null) {
        start = Math.max(0, Math.min(limit, start));
        end = Math.max(0, Math.min(limit, end));
      }
      if (end <= start) return null;

      return {
        id:
          typeof raw?.id === "string" && raw.id.trim()
            ? raw.id.trim()
            : `memo_${Date.now()}_${idx}`,
        start,
        end,
        text:
          typeof raw?.text === "string"
            ? raw.text
            : String(raw?.text || ""),
        color: _safeMemoColor(raw?.color),
        created_at:
          typeof raw?.created_at === "string" && raw.created_at
            ? raw.created_at
            : nowIso,
        updated_at:
          typeof raw?.updated_at === "string" && raw.updated_at
            ? raw.updated_at
            : nowIso,
      };
    })
    .filter((item) => item && item.end > item.start)
    .sort((left, right) => {
      if (left.start !== right.start) return left.start - right.start;
      if (left.end !== right.end) return left.end - right.end;
      return left.id.localeCompare(right.id);
    });

  return normalized;
}

function _stripMemoMarkup(editor) {
  if (!editor) return;
  const spans = editor.querySelectorAll(".inline-memo-marked");
  spans.forEach((span) => {
    const parent = span.parentNode;
    if (!parent) return;
    while (span.firstChild) {
      parent.insertBefore(span.firstChild, span);
    }
    parent.removeChild(span);
  });
  if (spans.length > 0) {
    editor.normalize();
  }
}

function _insertCaretAfterNode(node) {
  if (!node) return;
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.setStartAfter(node);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function _selectionWithinSinglePage(range) {
  if (!range) return false;
  const startPage = range.startContainer?.parentElement?.closest?.(".page-editor");
  const endPage = range.endContainer?.parentElement?.closest?.(".page-editor");
  if (!startPage || !endPage) return false;
  return startPage === endPage;
}

const INLINE_TAG_TYPE_TO_PATH = {
  인물: "사용자태그/인물",
  사건: "사용자태그/사건",
  복선: "사용자태그/복선",
};

const INLINE_TAG_PATH_TO_TYPE = Object.entries(INLINE_TAG_TYPE_TO_PATH).reduce(
  (acc, [tagType, tagPath]) => {
    acc[String(tagPath)] = String(tagType);
    return acc;
  },
  {},
);

function _tagPathForInlineType(tagType) {
  return INLINE_TAG_TYPE_TO_PATH[String(tagType || "").trim()] || "";
}

function _inlineTypeForTagPath(tagPath) {
  const key = String(tagPath || "").trim();
  return INLINE_TAG_PATH_TO_TYPE[key] || key || "태그";
}

function _inlineTagLabel(record) {
  if (!record || typeof record !== "object") return "태그";
  const tagType =
    typeof record.tag_type === "string" && record.tag_type.trim()
      ? record.tag_type.trim()
      : _inlineTypeForTagPath(record.tag_path);
  return tagType || "태그";
}

function _stripInlineTagMarkup(editor) {
  if (!editor) return;
  const spans = editor.querySelectorAll(".inline-tag-marked");
  spans.forEach((span) => {
    const parent = span.parentNode;
    if (!parent) return;
    while (span.firstChild) {
      parent.insertBefore(span.firstChild, span);
    }
    parent.removeChild(span);
  });
  if (spans.length > 0) editor.normalize();
}

function _refreshInlineTagDirtyFlag() {
  state.inlineTagDirty = state.inlineTags.some((tag) => tag.sync_state !== "synced");
}

function _normalizeInlineTagRecords(rawList, textLen = null) {
  const source = Array.isArray(rawList) ? rawList : [];
  const limit = Number.isInteger(textLen) ? Math.max(0, textLen) : null;
  const normalized = source
    .map((raw, idx) => {
      const startRaw = Number.parseInt(String(raw?.start ?? raw?.span_start ?? ""), 10);
      const endRaw = Number.parseInt(String(raw?.end ?? raw?.span_end ?? ""), 10);
      if (!Number.isInteger(startRaw) || !Number.isInteger(endRaw)) return null;
      let start = startRaw;
      let end = endRaw;
      if (limit !== null) {
        start = Math.max(0, Math.min(limit, start));
        end = Math.max(0, Math.min(limit, end));
      }
      if (end <= start) return null;
      const localIdRaw =
        typeof raw?.local_id === "string" && raw.local_id.trim()
          ? raw.local_id.trim()
          : typeof raw?.assign_id === "string" && raw.assign_id.trim()
            ? raw.assign_id.trim()
            : `itag_${Date.now()}_${idx}`;
      const tagPathRaw =
        typeof raw?.tag_path === "string" && raw.tag_path.trim()
          ? raw.tag_path.trim()
          : _tagPathForInlineType(raw?.tag_type);
      return {
        local_id: localIdRaw,
        assign_id:
          typeof raw?.assign_id === "string" && raw.assign_id.trim()
            ? raw.assign_id.trim()
            : null,
        doc_id:
          typeof raw?.doc_id === "string" && raw.doc_id.trim()
            ? raw.doc_id.trim()
            : state.currentDocId || null,
        snapshot_id:
          typeof raw?.snapshot_id === "string" && raw.snapshot_id.trim()
            ? raw.snapshot_id.trim()
            : state.currentDocSnapshotId || null,
        start,
        end,
        tag_path: tagPathRaw,
        tag_type:
          typeof raw?.tag_type === "string" && raw.tag_type.trim()
            ? raw.tag_type.trim()
            : _inlineTypeForTagPath(tagPathRaw),
        user_value:
          typeof raw?.user_value === "string"
            ? raw.user_value
            : typeof raw?.text === "string"
              ? raw.text
              : "",
        sync_state:
          raw?.sync_state === "synced" || (typeof raw?.assign_id === "string" && raw.assign_id.trim())
            ? "synced"
            : "pending",
      };
    })
    .filter((item) => item && item.end > item.start)
    .sort((left, right) => {
      if (left.start !== right.start) return left.start - right.start;
      if (left.end !== right.end) return left.end - right.end;
      return left.local_id.localeCompare(right.local_id);
    });
  return normalized;
}

function _renderInlineTagsFromState() {
  const editor = document.getElementById("editor");
  if (!editor) return;
  _stripInlineTagMarkup(editor);
  const textLen = getEditorText().length;
  const normalized = _normalizeInlineTagRecords(state.inlineTags, textLen);
  const toRender = [...normalized].sort((left, right) => {
    if (left.start !== right.start) return right.start - left.start;
    return right.end - left.end;
  });

  for (const tag of toRender) {
    const textNodes = _collectEditorTextNodesLocal(editor);
    if (!textNodes.length) continue;
    const startPos = _positionForOffsetLocal(textNodes, tag.start);
    const endPos = _positionForOffsetLocal(textNodes, tag.end);
    if (!startPos || !endPos) continue;

    const range = document.createRange();
    range.setStart(startPos.node, startPos.offset);
    range.setEnd(endPos.node, endPos.offset);

    const span = document.createElement("span");
    span.className = "inline-tag-marked";
    span.dataset.inlineTagId = tag.local_id;
    span.dataset.tagType = _inlineTagLabel(tag);
    span.dataset.tagPath = tag.tag_path || "";
    if (tag.assign_id) span.dataset.assignId = tag.assign_id;
    span.title = `태그: ${_inlineTagLabel(tag)}`;

    try {
      range.surroundContents(span);
    } catch (_error) {
      const fragment = range.extractContents();
      span.appendChild(fragment);
      range.insertNode(span);
    }
  }

  state.inlineTags = normalized;
  _refreshInlineTagDirtyFlag();
}

function syncInlineTagsFromDom() {
  const editor = document.getElementById("editor");
  if (!editor || !Array.isArray(state.inlineTags)) return;
  const next = [];
  state.inlineTags.forEach((tag) => {
    const span = editor.querySelector(`.inline-tag-marked[data-inline-tag-id="${tag.local_id}"]`);
    if (!span) return;

    const beforeRange = document.createRange();
    beforeRange.selectNodeContents(editor);
    beforeRange.setEndBefore(span);
    const start = beforeRange.toString().length;

    const spanRange = document.createRange();
    spanRange.selectNodeContents(span);
    const length = spanRange.toString().length;
    if (length <= 0) return;

    next.push({
      ...tag,
      start,
      end: start + length,
      user_value: spanRange.toString(),
    });
  });
  state.inlineTags = _normalizeInlineTagRecords(next, getEditorText().length);
  _refreshInlineTagDirtyFlag();
}

async function _syncInlineTagAssignment(tag) {
  if (!state.projectId || !state.currentDocId || !tag) return false;
  const snapshotId = state.currentDocSnapshotId;
  if (!snapshotId) return false;
  try {
    const res = await api(
      `/projects/${encodeURIComponent(state.projectId)}/tags/assignments`,
      "POST",
      {
        doc_id: state.currentDocId,
        snapshot_id: snapshotId,
        span_start: tag.start,
        span_end: tag.end,
        tag_path: tag.tag_path,
        user_value: tag.user_value || "",
        created_by: "USER",
      },
    );
    const assignment = res?.assignment || {};
    tag.assign_id =
      typeof assignment.assign_id === "string" && assignment.assign_id
        ? assignment.assign_id
        : tag.assign_id;
    tag.snapshot_id = snapshotId;
    tag.sync_state = "synced";
    return true;
  } catch (error) {
    console.warn("inline tag sync failed", error);
    tag.sync_state = "pending";
    return false;
  }
}

async function syncPendingInlineTags() {
  if (!Array.isArray(state.inlineTags) || state.inlineTags.length === 0) {
    state.inlineTagDirty = false;
    return;
  }
  const queue = state.inlineTags.filter((tag) => tag.sync_state !== "synced");
  for (const tag of queue) {
    await _syncInlineTagAssignment(tag);
  }
  state.inlineTags = _normalizeInlineTagRecords(state.inlineTags, getEditorText().length);
  _refreshInlineTagDirtyFlag();
}

async function syncInlineTagsAfterSnapshot(snapshotId) {
  if (!snapshotId || !Array.isArray(state.inlineTags) || state.inlineTags.length === 0) {
    state.currentDocSnapshotId = snapshotId || state.currentDocSnapshotId;
    state.inlineTagDirty = false;
    return;
  }
  syncInlineTagsFromDom();
  state.currentDocSnapshotId = snapshotId;
  state.inlineTags = state.inlineTags.map((tag) => ({
    ...tag,
    assign_id: null,
    snapshot_id: snapshotId,
    sync_state: "pending",
  }));
  _refreshInlineTagDirtyFlag();
  await syncPendingInlineTags();
  _renderInlineTagsFromState();
}

function restoreInlineTagsFromAssignments(assignments) {
  const editor = document.getElementById("editor");
  if (!editor) return;
  _stripInlineTagMarkup(editor);
  const textLen = getEditorText().length;
  const normalized = _normalizeInlineTagRecords(
    (Array.isArray(assignments) ? assignments : []).map((item) => ({
      local_id:
        typeof item?.assign_id === "string" && item.assign_id
          ? item.assign_id
          : `itag_${Date.now()}`,
      assign_id: item?.assign_id || null,
      doc_id: item?.doc_id || state.currentDocId,
      snapshot_id: item?.snapshot_id || state.currentDocSnapshotId,
      start: item?.span_start,
      end: item?.span_end,
      tag_path: item?.tag_path || "",
      tag_type: _inlineTypeForTagPath(item?.tag_path || ""),
      user_value:
        typeof item?.user_value === "string" ? item.user_value : "",
      sync_state: "synced",
    })),
    textLen,
  );
  state.inlineTags = normalized;
  state.inlineTagDirty = false;
  _renderInlineTagsFromState();
}

function _serializeMemosForMetadata() {
  syncMemoAnchorsFromDom();
  return state.memos.map((memo) => ({
    id: memo.id,
    start: memo.start,
    end: memo.end,
    text: memo.text,
    color: _safeMemoColor(memo.color),
    created_at: memo.created_at,
    updated_at: memo.updated_at,
  }));
}

function _loadMemosFromMetadata(rawMemos) {
  const editor = document.getElementById("editor");
  if (!editor) return;

  _stripMemoMarkup(editor);

  const textLen = getEditorText().length;
  const normalized = _normalizeMemoList(rawMemos, textLen);
  const toRender = [...normalized].sort((left, right) => {
    if (left.start !== right.start) return right.start - left.start;
    return right.end - left.end;
  });

  for (const memo of toRender) {
    const textNodes = _collectEditorTextNodesLocal(editor);
    if (!textNodes.length) continue;

    const startPos = _positionForOffsetLocal(textNodes, memo.start);
    const endPos = _positionForOffsetLocal(textNodes, memo.end);
    if (!startPos || !endPos) continue;

    const range = document.createRange();
    range.setStart(startPos.node, startPos.offset);
    range.setEnd(endPos.node, endPos.offset);

    const span = document.createElement("span");
    span.className = "inline-memo-marked";
    span.dataset.memoId = memo.id;
    _applyMemoSpanStyle(span, memo.color);

    try {
      range.surroundContents(span);
    } catch (_error) {
      const fragment = range.extractContents();
      span.appendChild(fragment);
      range.insertNode(span);
    }
  }

  state.memos = normalized;
  state.memoDirty = false;
  _scheduleMemoRender();
}

function syncMemoAnchorsFromDom() {
  const editor = document.getElementById("editor");
  if (!editor) return;
  const nowIso = _nowIso();

  const next = [];
  state.memos.forEach((memo) => {
    const span = editor.querySelector(
      `.inline-memo-marked[data-memo-id="${memo.id}"]`,
    );
    if (!span) return;

    const beforeRange = document.createRange();
    beforeRange.selectNodeContents(editor);
    beforeRange.setEndBefore(span);
    const start = beforeRange.toString().length;

    const spanRange = document.createRange();
    spanRange.selectNodeContents(span);
    const length = spanRange.toString().length;
    if (length <= 0) return;

    const color = _safeMemoColor(span.dataset.color || memo.color);
    _applyMemoSpanStyle(span, color);

    next.push({
      id: memo.id,
      start,
      end: start + length,
      text: typeof memo.text === "string" ? memo.text : "",
      color,
      created_at: memo.created_at || nowIso,
      updated_at: memo.updated_at || nowIso,
    });
  });

  state.memos = _normalizeMemoList(next, getEditorText().length);
}

function _markMemoDirty(delayMs = 1200) {
  state.memoDirty = true;
  _setSaveStatus("저장되지 않음", "#e67e22");
  _scheduleSave(delayMs);
}

window.serializeMemosForMetadata = _serializeMemosForMetadata;
window.loadMemosFromMetadata = _loadMemosFromMetadata;
window.syncMemoAnchorsFromDom = syncMemoAnchorsFromDom;
window.syncInlineTagsFromDom = syncInlineTagsFromDom;
window.syncPendingInlineTags = syncPendingInlineTags;
window.syncInlineTagsAfterSnapshot = syncInlineTagsAfterSnapshot;
window.restoreInlineTagsFromAssignments = restoreInlineTagsFromAssignments;
window.schedulePageGuideRender = schedulePageGuideRender;
window.updateStatusBar = updateStatusBar;
window.layoutMemoSidebar = layoutMemoSidebar;
window.renderPagedEditor = renderPagedEditor;
window.getEditorText = getEditorText;
window.setEditorText = setEditorText;
window.paginateText = paginateText;
window.captureSelectionGlobalOffset = captureSelectionGlobalOffset;
window.restoreSelectionGlobalOffset = restoreSelectionGlobalOffset;
window.resetMemoStateForDoc = function () {
  const editor = document.getElementById("editor");
  if (editor) _stripMemoMarkup(editor);

  state.memos = [];
  state.memoDirty = false;
  state.targetNodeToRemove = null;

  const sidebar = document.getElementById("memo-sidebar");
  if (sidebar) sidebar.innerHTML = "";
};

window.resetInlineTagStateForDoc = function () {
  const editor = document.getElementById("editor");
  if (editor) _stripInlineTagMarkup(editor);
  state.inlineTags = [];
  state.inlineTagDirty = false;
};

function handleLocalExport() {
  if (!state.currentDocId) {
    alert("먼저 문서를 열어주세요.");
    return closeExportModal();
  }
  const format = document.querySelector('input[name="export-fmt"]:checked').value;
  const title = document.getElementById("doc-title-input").value || "export";
  const contentText = getEditorText();

  if (format === "txt") {
    const blob = new Blob([contentText], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  } else if (format === "docx") {
    const preHtml = "<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'><head><meta charset='utf-8'><title>Export HTML To Doc</title></head><body>";
    const postHtml = "</body></html>";
    const html =
      preHtml + document.getElementById("editor").innerHTML + postHtml;
    const blob = new Blob(["\ufeff", html], { type: "application/msword" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title}.doc`;
    a.click();
    URL.revokeObjectURL(url);
  }
  closeExportModal();
}

window.handleLocalExport = handleLocalExport;

function execCmd(command, value = null) {
  document.execCommand(command, false, value);
  const firstPage = document.querySelector("#editor .page-editor");
  if (firstPage) firstPage.focus();
  handleInput();
}

document.addEventListener("DOMContentLoaded", () => {
  updateIcons();

  const observer = new MutationObserver(() => updateIcons());
  observer.observe(document.body, { childList: true, subtree: true });

  const editorContainer = document.querySelector(".editor-container");
  if (editorContainer) {
    editorContainer.addEventListener(
      "scroll",
      () => {
        _scheduleMemoRender();
        _scheduleFloatingPopoverReposition();
      },
      { passive: true },
    );
  }

  const editorHost = document.getElementById("editor");
  if (editorHost) {
    editorHost.addEventListener(
      "input",
      (event) => {
        if (event.target?.classList?.contains("page-editor")) {
          handleInput();
          _scheduleRepaginateFromDom();
        }
      },
      true,
    );

    editorHost.addEventListener(
      "compositionstart",
      (event) => {
        if (event.target?.classList?.contains("page-editor")) {
          handleComposition(true);
        }
      },
      true,
    );

    editorHost.addEventListener(
      "compositionend",
      (event) => {
        if (!event.target?.classList?.contains("page-editor")) return;
        handleComposition(false);
        if (pendingRepaginateAfterComposition) {
          pendingRepaginateAfterComposition = false;
          const requestId = ++paginationWorkerSeq;
          void _repaginateFromDom(requestId);
        } else {
          _scheduleRepaginateFromDom();
        }
      },
      true,
    );

    editorHost.addEventListener("keydown", _handlePageBoundaryKeydown, true);
    editorHost.addEventListener("paste", _handlePaste, true);
  }

  window.addEventListener("resize", () => {
    layoutMemoSidebar();
    _scheduleMemoRender();
    schedulePageGuideRender();
    _scheduleFloatingPopoverReposition();
  });

  window.addEventListener("nf:layout-changed", () => {
    layoutMemoSidebar();
    _scheduleMemoRender();
    schedulePageGuideRender();
    _scheduleFloatingPopoverReposition();
  });

  setEditorText("", { preserveCaret: false });
  layoutMemoSidebar();
  updateStatusBar();
  schedulePageGuideRender();
});

// --- Auto Save & Hotkeys ---
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    void saveDoc(true);
  }
});

setInterval(() => {
  if (
    state.currentDocId &&
    (state.isDirty || state.memoDirty || state.inlineTagDirty) &&
    !state.isComposing
  ) {
    void saveDoc(false);
  }
}, 5000);

function handleComposition(active) {
  state.isComposing = Boolean(active);
  if (state.isComposing) {
    if (state.saveTimeout) {
      clearTimeout(state.saveTimeout);
      state.saveTimeout = null;
    }
    return;
  }
  updateStatusBar();
  _scheduleSave(350);
}

// --- Editor Input Handler ---
function handleInput() {
  state.isDirty = true;
  clearInlineVerdictHighlights();
  _setSaveStatus("저장되지 않음", "#e67e22");

  updateStatusBar();
  collectGarbageMemos();

  if (!state.isComposing) {
    _scheduleSave(2000);
  }
}

window.collectGarbageMemos = function () {
  const editor = document.getElementById("editor");
  if (!editor) return;

  const originalLength = state.memos.length;
  state.memos = state.memos.filter((memo) => {
    const span = editor.querySelector(
      `.inline-memo-marked[data-memo-id="${memo.id}"]`,
    );
    return Boolean(span);
  });

  if (state.memos.length !== originalLength) {
    _markMemoDirty(1200);
    _scheduleMemoRender();
  }
};

async function saveDoc(immediate = false) {
  if (!state.currentDocId) return;
  if (!state.isDirty && !state.memoDirty && !state.inlineTagDirty) return;
  if (state.isComposing && !immediate) return;
  syncInlineTagsFromDom();

  const titleInputEl = document.getElementById("doc-title-input");
  const content = getEditorText();
  const title = titleInputEl ? titleInputEl.value : "";

  const shouldSaveContent = Boolean(state.isDirty);
  const shouldSaveMemos = Boolean(state.memoDirty);
  const shouldSyncInlineTags = Boolean(state.inlineTagDirty);

  let memoPayload = null;
  if (shouldSaveMemos) {
    memoPayload = _serializeMemosForMetadata();
  }

  if (immediate) showLoading("저장 중...");
  else _setSaveStatus("저장 중...", "#3498db");

  if (state.docs[state.currentDocId]) {
    state.docs[state.currentDocId].title = title;
    state.docs[state.currentDocId].updated_at = new Date().toISOString();
    if (memoPayload) {
      const nextMeta = {
        ...(state.docs[state.currentDocId].metadata || {}),
        [MEMO_METADATA_KEY]: memoPayload,
      };
      state.docs[state.currentDocId].metadata = nextMeta;
    }

    if (state.currentNavTab === "TIMELINE") {
      renderTimelineView();
    } else {
      renderDocList();
    }
  }

  const payload = { title };
  if (shouldSaveContent) payload.content = content;
  if (memoPayload) {
    payload.metadata = {
      [MEMO_METADATA_KEY]: memoPayload,
    };
  }

  try {
    const prevSnapshotId = state.currentDocSnapshotId;
    const res = await api(
      `/projects/${state.projectId}/documents/${state.currentDocId}`,
      "PATCH",
      payload,
    );
    const updatedDoc =
      res && typeof res.document === "object" && res.document
        ? res.document
        : null;
    if (updatedDoc && state.docs[state.currentDocId]) {
      state.docs[state.currentDocId] = {
        ...state.docs[state.currentDocId],
        ...updatedDoc,
      };
    }
    const snapshotIdRaw = updatedDoc?.head_snapshot_id;
    const nextSnapshotId =
      typeof snapshotIdRaw === "string" && snapshotIdRaw.trim()
        ? snapshotIdRaw.trim()
        : prevSnapshotId;
    state.currentDocSnapshotId = nextSnapshotId || null;

    if (shouldSaveContent) {
      const nextSegments = _segmentTextForConsistency(content);
      state.pendingConsistencySegments = _collectChangedSegments(
        state.lastSegmentFingerprints,
        nextSegments,
      );
      state.lastSegmentFingerprints = nextSegments;
      state.isDirty = false;
    }
    if (shouldSaveMemos) {
      state.memoDirty = false;
    }
    if (nextSnapshotId && nextSnapshotId !== prevSnapshotId) {
      await syncInlineTagsAfterSnapshot(nextSnapshotId);
    } else if (shouldSyncInlineTags) {
      await syncPendingInlineTags();
    }

    _setSaveStatus("저장됨", "#aaa");
    if (immediate) hideLoading();

    updateStatusBar();
    _scheduleMemoRender();

    if (shouldSaveContent) {
      schedulePostSavePipeline(state.currentDocId, true);
    }
  } catch (e) {
    _setSaveStatus("저장 실패", "red");
    if (immediate) hideLoading();
    console.error(e);
  }
}

// --- Config Management ---
function updateEditorConfig(key, value) {
  state.editorConfig[key] = value;
  const root = document.querySelector(":root");

  if (key === "fontSize") root.style.setProperty("--editor-font-size", value);
  if (key === "lineHeight")
    root.style.setProperty("--editor-line-height", value);
  if (key === "letterSpacing")
    root.style.setProperty("--editor-letter-spacing", value);
  if (key === "fontFamily")
    root.style.setProperty("--editor-font-family", value);

  localStorage.setItem("nf_editor_config", JSON.stringify(state.editorConfig));

  const requestId = ++paginationWorkerSeq;
  void _repaginateFromDom(requestId);
  schedulePageGuideRender();
  _scheduleMemoRender();
}

function loadEditorConfig() {
  const saved = localStorage.getItem("nf_editor_config");
  if (!saved) return;

  try {
    const config = JSON.parse(saved);
    Object.keys(config).forEach((k) => updateEditorConfig(k, config[k]));
  } catch (e) {
    console.warn("failed to load editor config", e);
  }
}

// --- Inline Tagging (Drag & Float) ---
let _selectionTimeout = null;

function _positionFloatingPopover(popover, rect, opts = {}) {
  if (!popover || !rect) return false;
  if (typeof positionPopoverInMainContent === "function") {
    return positionPopoverInMainContent(popover, rect, opts);
  }

  const align = opts.align === "start" || opts.align === "end"
    ? opts.align
    : "center";
  const vertical = opts.vertical === "below" ? "below" : "above";
  const gap = Number.isFinite(Number(opts.gap)) ? Number(opts.gap) : 8;

  let left = rect.left;
  if (align === "center") left = rect.left + rect.width / 2;
  if (align === "end") left = rect.right;
  const top =
    vertical === "below"
      ? rect.bottom + window.scrollY + gap
      : rect.top + window.scrollY - gap;

  popover.style.left = `${left + window.scrollX}px`;
  popover.style.top = `${top}px`;
  popover.style.transform = align === "center" ? "translate(-50%, -100%)" : "none";
  return true;
}

function repositionInlineTagWidget() {
  const widget = document.getElementById("inline-tag-widget");
  if (!widget || widget.style.display !== "block") return false;

  let rect = null;
  if (state.savedSelectionRange && typeof state.savedSelectionRange.getBoundingClientRect === "function") {
    rect = state.savedSelectionRange.getBoundingClientRect();
  }
  if (!rect || (!rect.width && !rect.height)) {
    const selection = window.getSelection();
    if (selection && selection.rangeCount > 0 && !selection.isCollapsed) {
      rect = selection.getRangeAt(0).getBoundingClientRect();
    }
  }
  if (!rect || (!rect.width && !rect.height)) return false;

  return _positionFloatingPopover(widget, rect, {
    align: "center",
    vertical: "above",
    gap: 10,
    margin: 8,
  });
}

function repositionTagRemovePopover() {
  const removePopover = document.getElementById("tag-remove-popover");
  const anchorNode = state.targetNodeToRemove;
  if (!removePopover || removePopover.style.display !== "block" || !anchorNode) {
    return false;
  }
  if (typeof anchorNode.getBoundingClientRect !== "function") return false;
  const rect = anchorNode.getBoundingClientRect();
  if (!rect || (!rect.width && !rect.height)) return false;

  return _positionFloatingPopover(removePopover, rect, {
    align: "center",
    vertical: "above",
    gap: 10,
    margin: 8,
  });
}

window.repositionInlineTagWidget = repositionInlineTagWidget;
window.repositionTagRemovePopover = repositionTagRemovePopover;

document.addEventListener("selectionchange", () => {
  clearTimeout(_selectionTimeout);
  _selectionTimeout = setTimeout(() => {
    const editor = document.getElementById("editor");
    const widget = document.getElementById("inline-tag-widget");
    if (!editor || !widget) return;

    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !editor.contains(selection.anchorNode)) {
      if (widget.style.display === "block" && !widget.contains(document.activeElement)) {
        widget.style.display = "none";
      }
      if (!selection || selection.isCollapsed) state.savedSelectionRange = null;
      return;
    }

    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return;

    widget.style.display = "block";
    state.savedSelectionRange = range.cloneRange();
    _positionFloatingPopover(widget, rect, {
      align: "center",
      vertical: "above",
      gap: 10,
      margin: 8,
    });
  }, 300);
});

// For clicks on existing tags
document.addEventListener("mouseup", (e) => {
  const widget = document.getElementById("inline-tag-widget");
  const removePopover = document.getElementById("tag-remove-popover");

  if (
    (widget && widget.contains(e.target)) ||
    (removePopover && removePopover.contains(e.target))
  ) {
    return;
  }

  if (
    e.target.classList.contains("inline-tag-marked") ||
    e.target.classList.contains("inline-memo-marked")
  ) {
    if (removePopover) {
      removePopover.style.display = "block";
      const titleEl = document.getElementById("tag-remove-title");
      if (titleEl) {
        titleEl.innerText = e.target.classList.contains("inline-memo-marked")
          ? "📝 부여된 메모"
          : "부여된 태그";
      }
    }
    state.targetNodeToRemove = e.target;
    repositionTagRemovePopover();
    if (widget) widget.style.display = "none";
    return;
  }

  if (removePopover) {
    removePopover.style.display = "none";
    state.targetNodeToRemove = null;
  }
});


document.addEventListener("mousedown", (e) => {
  const editor = document.getElementById("editor");
  const widget = document.getElementById("inline-tag-widget");
  const removePopover = document.getElementById("tag-remove-popover");

  if (
    widget &&
    widget.style.display === "block" &&
    !widget.contains(e.target) &&
    editor &&
    !editor.contains(e.target)
  ) {
    widget.style.display = "none";
  }

  if (
    removePopover &&
    removePopover.style.display === "block" &&
    !removePopover.contains(e.target) &&
    !e.target.classList.contains("inline-tag-marked") &&
    !e.target.classList.contains("inline-memo-marked")
  ) {
    removePopover.style.display = "none";
    state.targetNodeToRemove = null;
  }
});

window.applyInlineTag = function (tagType) {
  const editor = document.getElementById("editor");
  const widget = document.getElementById("inline-tag-widget");
  if (widget) widget.style.display = "none";

  if (!editor || !state.savedSelectionRange) return;
  if (!_selectionWithinSinglePage(state.savedSelectionRange)) {
    alert("태그는 한 페이지 범위에서만 지정할 수 있습니다.");
    state.savedSelectionRange = null;
    return;
  }
  const offsets = _offsetsFromRange(editor, state.savedSelectionRange);
  if (!offsets || offsets.end <= offsets.start) {
    state.savedSelectionRange = null;
    return;
  }
  const tagPath = _tagPathForInlineType(tagType);
  if (!tagPath) {
    alert("지원하지 않는 태그 유형입니다.");
    state.savedSelectionRange = null;
    return;
  }

  const selection = window.getSelection();
  if (!selection) return;
  selection.removeAllRanges();
  selection.addRange(state.savedSelectionRange);

  const span = document.createElement("span");
  const localId = `itag_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  span.className = "inline-tag-marked";
  span.dataset.inlineTagId = localId;
  span.dataset.tagType = tagType;
  span.dataset.tagPath = tagPath;
  span.title = `태그: ${tagType}`;


  const fragment = state.savedSelectionRange.extractContents();
  span.appendChild(fragment);
  state.savedSelectionRange.insertNode(span);

  _insertCaretAfterNode(span);
  state.savedSelectionRange = null;
  const selectedText = span.textContent || "";
  state.inlineTags = _normalizeInlineTagRecords([
    ...state.inlineTags,
    {
      local_id: localId,
      assign_id: null,
      doc_id: state.currentDocId,
      snapshot_id: state.currentDocSnapshotId,
      start: offsets.start,
      end: offsets.end,
      tag_path: tagPath,
      tag_type: tagType,
      user_value: selectedText,
      sync_state: "pending",
    },
  ]);
  _refreshInlineTagDirtyFlag();
  void syncPendingInlineTags();

  updateStatusBar();
};

window.applyInlineMemo = function () {
  const editor = document.getElementById("editor");
  const widget = document.getElementById("inline-tag-widget");
  if (widget) widget.style.display = "none";

  if (!editor || !state.savedSelectionRange) return;
  if (!_selectionWithinSinglePage(state.savedSelectionRange)) {
    alert("메모는 한 페이지 범위에서만 지정할 수 있습니다.");
    state.savedSelectionRange = null;
    return;
  }

  const offsets = _offsetsFromRange(editor, state.savedSelectionRange);
  if (!offsets || offsets.end <= offsets.start) {
    state.savedSelectionRange = null;
    return;
  }

  const selection = window.getSelection();
  if (!selection) return;
  selection.removeAllRanges();
  selection.addRange(state.savedSelectionRange);

  const memoId = `memo_${Date.now()}`;
  const span = document.createElement("span");
  span.className = "inline-memo-marked";
  span.dataset.memoId = memoId;
  _applyMemoSpanStyle(span, DEFAULT_MEMO_COLOR);

  const fragment = state.savedSelectionRange.extractContents();
  span.appendChild(fragment);
  state.savedSelectionRange.insertNode(span);

  _insertCaretAfterNode(span);
  state.savedSelectionRange = null;

  const nowIso = _nowIso();
  state.memos.push({
    id: memoId,
    start: offsets.start,
    end: offsets.end,
    text: "",
    color: DEFAULT_MEMO_COLOR,
    created_at: nowIso,
    updated_at: nowIso,
  });

  _markMemoDirty(1200);
  _scheduleMemoRender();
  updateStatusBar();
};

window.removeInlineTagOrMemo = function () {
  const removePopover = document.getElementById("tag-remove-popover");
  if (removePopover) removePopover.style.display = "none";

  const node = state.targetNodeToRemove;
  if (!node || !node.parentNode) return;
  const isTag = node.classList.contains("inline-tag-marked");

  if (node.classList.contains("inline-memo-marked")) {
    const memoId = node.dataset.memoId;
    state.memos = state.memos.filter((memo) => memo.id !== memoId);
    _markMemoDirty(800);
  }
  if (isTag) {
    const localId = node.dataset.inlineTagId || "";
    const record = state.inlineTags.find((tag) => tag.local_id === localId);
    state.inlineTags = state.inlineTags.filter((tag) => tag.local_id !== localId);
    _refreshInlineTagDirtyFlag();
    if (
      state.projectId &&
      record &&
      typeof record.assign_id === "string" &&
      record.assign_id
    ) {
      void api(
        `/projects/${encodeURIComponent(state.projectId)}/tags/assignments/${encodeURIComponent(record.assign_id)}`,
        "DELETE",
      ).catch((error) => {
        console.warn("inline tag delete failed", error);
      });
    }
  }

  const parent = node.parentNode;
  while (node.firstChild) {
    parent.insertBefore(node.firstChild, node);
  }
  parent.removeChild(node);

  state.targetNodeToRemove = null;
  updateStatusBar();
  _scheduleMemoRender();
};

window.renderMemos = function () {
  const sidebar = document.getElementById("memo-sidebar");
  const editor = document.getElementById("editor");
  const editorContainer = document.querySelector(".editor-container");
  if (!sidebar || !editor || !editorContainer) return;
  if (!layoutMemoSidebar()) {
    sidebar.innerHTML = "";
    return;
  }

  sidebar.innerHTML = "";

  const memoLayouts = [];
  state.memos.forEach((memo) => {
    const span = editor.querySelector(
      `.inline-memo-marked[data-memo-id="${memo.id}"]`,
    );
    if (!span) return;

    const color = _safeMemoColor(memo.color);
    const palette = MEMO_COLORS[color];
    _applyMemoSpanStyle(span, color);

    const containerTop = editorContainer.getBoundingClientRect().top;
    const scrollY = editorContainer.scrollTop;
    const rect = span.getBoundingClientRect();
    const topPos = rect.top - containerTop + scrollY - 10;

    const card = document.createElement("div");
    card.className = "memo-card";
    card.style.borderColor = palette.border;
    card.dataset.memoId = memo.id;

    card.innerHTML = `
      <div class="memo-card-header" style="color: ${palette.border}">
        <span>📝 메모</span>
        <button class="memo-card-delete" onclick="deleteMemoById('${memo.id}')"><i data-lucide="x" style="width:14px; height:14px;"></i></button>
      </div>
      <textarea class="memo-card-body" placeholder="메모를 작성하세요..." oninput="updateMemoText('${memo.id}', this.value)">${_escapeMemoHtml(memo.text || "")}</textarea>
      <div style="display:flex; gap: 4px; margin-top: 6px; padding-top: 6px; border-top: 1px solid #f1f5f9;">
        <button onclick="updateMemoColor('${memo.id}', 'yellow')" style="width:14px; height:14px; border-radius:50%; background:#fcd34d; border:1px solid #f59e0b; cursor:pointer;" title="노랑"></button>
        <button onclick="updateMemoColor('${memo.id}', 'blue')" style="width:14px; height:14px; border-radius:50%; background:#93c5fd; border:1px solid #3b82f6; cursor:pointer;" title="파랑"></button>
        <button onclick="updateMemoColor('${memo.id}', 'green')" style="width:14px; height:14px; border-radius:50%; background:#6ee7b7; border:1px solid #10b981; cursor:pointer;" title="초록"></button>
        <button onclick="updateMemoColor('${memo.id}', 'pink')" style="width:14px; height:14px; border-radius:50%; background:#f9a8d4; border:1px solid #ec4899; cursor:pointer;" title="분홍"></button>
      </div>
    `;

    card.addEventListener("mouseenter", () => {
      span.style.backgroundColor = palette.hoverBg;
    });
    card.addEventListener("mouseleave", () => {
      span.style.backgroundColor = palette.bg;
    });

    memoLayouts.push({ memo, card, topPos, height: 130 });
  });

  memoLayouts.sort((left, right) => left.topPos - right.topPos);

  let currentTop = 0;
  const gap = 12;

  memoLayouts.forEach((layout) => {
    const adjustedTop = layout.topPos < currentTop ? currentTop : layout.topPos;
    currentTop = adjustedTop + layout.height + gap;
    layout.card.style.top = `${adjustedTop}px`;
    sidebar.appendChild(layout.card);
  });

  updateIcons();
};

window.updateMemoColor = function (id, color) {
  const memo = state.memos.find((item) => item.id === id);
  if (!memo) return;

  memo.color = _safeMemoColor(color);
  memo.updated_at = _nowIso();
  _markMemoDirty(800);
  _scheduleMemoRender();
};

window.updateMemoText = function (id, val) {
  const memo = state.memos.find((item) => item.id === id);
  if (!memo) return;

  memo.text = String(val ?? "");
  memo.updated_at = _nowIso();
  _markMemoDirty(1200);
};

window.deleteMemoById = function (id) {
  const span = document.querySelector(
    `.inline-memo-marked[data-memo-id="${id}"]`,
  );
  if (span) {
    state.targetNodeToRemove = span;
    window.removeInlineTagOrMemo();
    return;
  }

  const prevLen = state.memos.length;
  state.memos = state.memos.filter((memo) => memo.id !== id);
  if (state.memos.length !== prevLen) {
    _markMemoDirty(800);
    _scheduleMemoRender();
    updateStatusBar();
  }
};
