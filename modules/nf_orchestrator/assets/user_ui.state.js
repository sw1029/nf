// --- State ---
let state = {
  projectId: null,
  projectName: "",
  currentDocId: null,
  currentDocType: "EPISODE",
  currentNavTab: "EPISODE",
  docs: {},
  saveTimeout: null,
  postSavePipelineTimer: null,
  postSavePipelinePendingDocId: null,
  postSavePipelineRunning: false,
  backgroundConsistencyTimer: null,
  backgroundConsistencyRunning: false,
  isDirty: false,
  memoDirty: false,
  isComposing: false,
  draggedDocId: null,
  draggedGroup: null,
  activeMemoRenderFrame: null,
  pendingConsistencySegments: [],
  lastSegmentFingerprints: [],
  lastVerdicts: [],
  showOkVerdicts: false,
  activePopoverVerdict: null,
  actionPopoverAnchorRange: null,
  actionPopoverAnchorTarget: null,
  savedSelectionRange: null,
  targetNodeToRemove: null,
  memos: [],
  inlineTags: [],
  inlineTagDirty: false,
  currentDocSnapshotId: null,
  editorText: "",
  pageSlices: [],
  pageCharBudget: 1800,
  usePaginationWorker: true,
  selectionOffset: null,
  pageRenderVersion: 0,
  pageGuideRenderScheduled: false,
  currentPageCount: 1,
  segmentRules: null,
  consistencyOptions: {
    filters: {
      entity_id: "",
      time_key: "",
      timeline_idx: "",
    },
    graph_mode: "off",
    layer3_promotion: true,
    verifier_mode: "off",
    triage_mode: "off",
    verification_loop: true,
  },
  editorConfig: {
    fontSize: "1.1rem",
    lineHeight: "1.8",
    letterSpacing: "0px",
    fontFamily: "'Noto Serif KR', serif",
  },
};

const DEFAULT_SEGMENT_RULES = {
  end_chars: [".", "!", "?", "\n", "。", "！", "？", "…", "．"],
  tail_chars: [".", "…", "'", '"', ")", "]", "}", "’", "”", "」", "』", "》"],
  abbreviation_tokens: [
    "a.m.",
    "cf.",
    "co.",
    "dr.",
    "e.g.",
    "etc.",
    "fig.",
    "i.e.",
    "inc.",
    "jr.",
    "ltd.",
    "mr.",
    "mrs.",
    "ms.",
    "no.",
    "p.m.",
    "prof.",
    "sr.",
    "st.",
    "u.k.",
    "u.s.",
    "vs.",
  ],
  decimal_guard: true,
  ordinal_guard: true,
  max_tail_scan: 24,
};

state.segmentRules = { ...DEFAULT_SEGMENT_RULES };

function _normalizeSegmentRules(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  const endChars = Array.isArray(src.end_chars)
    ? src.end_chars.map((item) => String(item || "")).filter((item) => item.length > 0)
    : DEFAULT_SEGMENT_RULES.end_chars;
  const tailChars = Array.isArray(src.tail_chars)
    ? src.tail_chars.map((item) => String(item || "")).filter((item) => item.length > 0)
    : DEFAULT_SEGMENT_RULES.tail_chars;
  const abbreviationTokens = Array.isArray(src.abbreviation_tokens)
    ? src.abbreviation_tokens.map((item) => String(item || "").toLowerCase()).filter((item) => item.length > 0)
    : DEFAULT_SEGMENT_RULES.abbreviation_tokens;
  const maxTailScan = Number.parseInt(String(src.max_tail_scan ?? ""), 10);
  return {
    end_chars: endChars.length > 0 ? endChars : DEFAULT_SEGMENT_RULES.end_chars,
    tail_chars: tailChars.length > 0 ? tailChars : DEFAULT_SEGMENT_RULES.tail_chars,
    abbreviation_tokens: abbreviationTokens.length > 0 ? abbreviationTokens : DEFAULT_SEGMENT_RULES.abbreviation_tokens,
    decimal_guard: src.decimal_guard !== false,
    ordinal_guard: src.ordinal_guard !== false,
    max_tail_scan: Number.isInteger(maxTailScan) && maxTailScan > 0 ? maxTailScan : DEFAULT_SEGMENT_RULES.max_tail_scan,
  };
}

function _segmentDecimalBoundary(src, idx, decimalGuard) {
  if (!decimalGuard) return false;
  if (idx <= 0 || idx >= src.length - 1) return false;
  return /\d/.test(src[idx - 1] || "") && /\d/.test(src[idx + 1] || "");
}

function _segmentAbbreviationBoundary(src, idx, abbreviationTokens, ordinalGuard) {
  if (src[idx] !== ".") return false;
  let start = idx - 1;
  while (
    start >= 0 &&
    /[A-Za-z0-9_.]/.test(src[start] || "")
  ) {
    start -= 1;
  }
  const token = src.slice(start + 1, idx + 1).trim().toLowerCase();
  if (!token) return false;
  if (abbreviationTokens.has(token)) return true;
  if (ordinalGuard && /^\d+(st|nd|rd|th)\.$/i.test(token)) return true;
  if (/^[a-z]\.$/i.test(token)) {
    const nextChar = src[idx + 1] || "";
    if (/[A-Z]/.test(nextChar)) return true;
  }
  return false;
}

async function loadSegmentRulesFromServer() {
  if (typeof api !== "function") {
    state.segmentRules = _normalizeSegmentRules(state.segmentRules);
    return state.segmentRules;
  }
  try {
    const res = await api("/query/segment-rules");
    state.segmentRules = _normalizeSegmentRules(res?.rules);
  } catch (error) {
    console.warn("segment rules load failed, using defaults", error);
    state.segmentRules = _normalizeSegmentRules(state.segmentRules);
  }
  return state.segmentRules;
}

window.loadSegmentRulesFromServer = loadSegmentRulesFromServer;

function _hashSegmentText(text) {
  let hash = 2166136261;
  const value = String(text || "");
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return `fnv1a:${(hash >>> 0).toString(16)}`;
}

function _trimSegmentSpan(text, start, end) {
  let left = Math.max(0, Number(start || 0));
  let right = Math.max(left, Number(end || 0));
  while (left < right && /\s/.test(text[left])) left += 1;
  while (right > left && /\s/.test(text[right - 1])) right -= 1;
  if (right <= left) return null;
  return { start: left, end: right, text: text.slice(left, right) };
}

function _segmentTextForConsistency(text) {
  const src = String(text || "");
  const segments = [];
  const textLen = src.length;
  const rules = _normalizeSegmentRules(state.segmentRules);
  const endChars = new Set(rules.end_chars);
  const tailChars = new Set(rules.tail_chars);
  const abbreviationTokens = new Set(rules.abbreviation_tokens || []);
  let cursor = 0;
  let idx = 0;

  const appendSegment = (segStart, segEnd, closed) => {
    const trimmed = _trimSegmentSpan(src, segStart, segEnd);
    if (!trimmed) return;
    segments.push({
      start: trimmed.start,
      end: trimmed.end,
      text: trimmed.text,
      fingerprint: _hashSegmentText(trimmed.text),
      closed: Boolean(closed),
    });
  };

  while (idx < textLen) {
    const ch = src[idx];
    if (!endChars.has(ch)) {
      idx += 1;
      continue;
    }
    if (ch === "." && _segmentDecimalBoundary(src, idx, rules.decimal_guard)) {
      idx += 1;
      continue;
    }
    if (ch === "." && _segmentAbbreviationBoundary(src, idx, abbreviationTokens, rules.ordinal_guard)) {
      idx += 1;
      continue;
    }
    let segEnd = idx;
    if (ch !== "\n") {
      segEnd = idx + 1;
      let tailScan = 0;
      while (
        segEnd < textLen &&
        tailChars.has(src[segEnd]) &&
        tailScan < rules.max_tail_scan
      ) {
        segEnd += 1;
        tailScan += 1;
      }
    }
    appendSegment(cursor, segEnd, true);
    cursor = ch === "\n" ? idx + 1 : segEnd;
    idx = cursor;
  }
  appendSegment(cursor, textLen, false);
  return segments;
}

function _collectChangedSegments(prevSegments, nextSegments) {
  const prevBuckets = new Map();
  (Array.isArray(prevSegments) ? prevSegments : []).forEach((item) => {
    if (
      !item ||
      !Number.isInteger(item.start) ||
      !Number.isInteger(item.end)
    )
      return;
    const fingerprint =
      typeof item.fingerprint === "string" && item.fingerprint
        ? item.fingerprint
        : _hashSegmentText(item.text || "");
    if (!prevBuckets.has(fingerprint)) prevBuckets.set(fingerprint, []);
    prevBuckets.get(fingerprint).push({
      start: item.start,
      end: item.end,
    });
  });
  prevBuckets.forEach((bucket) =>
    bucket.sort((left, right) => left.start - right.start),
  );

  const changed = [];
  (Array.isArray(nextSegments) ? nextSegments : []).forEach((item) => {
    if (
      !item ||
      !Number.isInteger(item.start) ||
      !Number.isInteger(item.end)
    )
      return;
    if (!item.closed) return;
    const fingerprint =
      typeof item.fingerprint === "string" && item.fingerprint
        ? item.fingerprint
        : _hashSegmentText(item.text || "");
    const bucket = prevBuckets.get(fingerprint);
    if (!Array.isArray(bucket) || bucket.length === 0) {
      changed.push(item);
      return;
    }

    let bestIdx = 0;
    let bestDist = Math.abs(bucket[0].start - item.start);
    for (let idx = 1; idx < bucket.length; idx += 1) {
      const dist = Math.abs(bucket[idx].start - item.start);
      if (dist < bestDist) {
        bestDist = dist;
        bestIdx = idx;
      }
    }
    bucket.splice(bestIdx, 1);
  });
  return changed;
}

function _mergeConsistencySegments(segments) {
  const normalized = (Array.isArray(segments) ? segments : [])
    .filter(
      (item) =>
        item &&
        Number.isInteger(item.start) &&
        Number.isInteger(item.end) &&
        item.end > item.start,
    )
    .map((item) => ({ start: item.start, end: item.end }))
    .sort((left, right) => {
      if (left.start !== right.start) return left.start - right.start;
      return left.end - right.end;
    });
  if (normalized.length === 0) return [];
  const merged = [normalized[0]];
  for (let idx = 1; idx < normalized.length; idx += 1) {
    const current = normalized[idx];
    const tail = merged[merged.length - 1];
    if (current.start <= tail.end + 1) {
      tail.end = Math.max(tail.end, current.end);
    } else {
      merged.push(current);
    }
  }
  return merged;
}

function _spanOverlaps(startA, endA, startB, endB) {
  return startA < endB && startB < endA;
}

function _normalizeGraphMode(raw) {
  if (raw === "manual" || raw === "auto" || raw === "off") return raw;
  if (raw === "on") return "manual";
  return "off";
}

function _normalizeVerifierMode(raw) {
  if (raw === "conservative_nli" || raw === "off") return raw;
  if (raw === "on") return "conservative_nli";
  return "off";
}

function _normalizeTriageMode(raw) {
  if (raw === "embedding_anomaly" || raw === "off") return raw;
  if (raw === "on") return "embedding_anomaly";
  return "off";
}

function _showConsistencyNotice(
  message,
  color = "#3498db",
  ttlMs = 2800,
) {
  const cStatus = document.getElementById("consistency-status");
  if (!cStatus || !message) return;
  cStatus.innerText = String(message);
  cStatus.style.color = color;
  if (ttlMs > 0) {
    setTimeout(() => {
      if (
        cStatus.innerText === message &&
        !state.backgroundConsistencyRunning
      ) {
        cStatus.innerText = "";
      }
    }, ttlMs);
  }
}

function _readConsistencyOptionsFromUi() {
  const entityInput = document.getElementById(
    "consistency-filter-entity",
  );
  const timeInput = document.getElementById("consistency-filter-time");
  const timelineInput = document.getElementById(
    "consistency-filter-timeline",
  );

  const filters = {};
  const entityId =
    entityInput && typeof entityInput.value === "string"
      ? entityInput.value.trim()
      : "";
  const timeKey =
    timeInput && typeof timeInput.value === "string"
      ? timeInput.value.trim()
      : "";
  const timelineIdxRaw =
    timelineInput && typeof timelineInput.value === "string"
      ? timelineInput.value.trim()
      : "";
  if (entityId) filters.entity_id = entityId;
  if (timeKey) filters.time_key = timeKey;
  if (timelineIdxRaw !== "") {
    const parsedTimeline = Number.parseInt(timelineIdxRaw, 10);
    if (Number.isInteger(parsedTimeline) && parsedTimeline >= 0) {
      filters.timeline_idx = parsedTimeline;
    }
  }

  let selectedLevel = "quick";
  const levelRadios = document.getElementsByName("consistency-level");
  if (levelRadios) {
    for (let r of levelRadios) {
      if (r.checked) {
        selectedLevel = r.value;
        break;
      }
    }
  }

  let graphMode = "off";
  let layer3Promotion = false;
  let verifierMode = "off";
  let triageMode = "off";
  let verificationLoop = false;

  if (selectedLevel === "deep") {
    graphMode = "auto";
    layer3Promotion = true;
    triageMode = "embedding_anomaly";
  } else if (selectedLevel === "strict") {
    graphMode = "auto";
    layer3Promotion = true;
    verifierMode = "conservative_nli";
    triageMode = "embedding_anomaly";
    verificationLoop = true;
  }

  state.consistencyOptions = {
    filters: {
      entity_id: entityId,
      time_key: timeKey,
      timeline_idx: timelineIdxRaw,
    },
    graph_mode: graphMode,
    layer3_promotion: layer3Promotion,
    verifier_mode: verifierMode,
    triage_mode: triageMode,
    verification_loop: verificationLoop,
  };

  const consistencyParams = {
    graph_mode: graphMode,
    graph_expand_enabled: graphMode !== "off",
    layer3_verdict_promotion: layer3Promotion,
    verifier: {
      mode: verifierMode,
      promote_ok_threshold: 0.95,
      contradict_alert_threshold: 0.7,
      max_claim_chars: 220,
    },
    triage: {
      mode: triageMode,
      anomaly_threshold: 0.65,
      max_segments_per_run: 8,
    },
    verification_loop: {
      enabled: verificationLoop,
      max_rounds: 2,
      round_timeout_ms: 250,
    },
  };

  return {
    filters,
    params: {
      consistency: consistencyParams,
    },
  };
}

function _buildConsistencyJobPayload(docId, range, preflight) {
  const options = _readConsistencyOptionsFromUi();
  return {
    type: "CONSISTENCY",
    project_id: state.projectId,
    inputs: {
      input_doc_id: docId,
      input_snapshot_id: "latest",
      range,
      preflight,
      schema_scope: "explicit_only",
      filters: options.filters,
    },
    params: options.params,
  };
}

let fallbackHighlightActive = false;

function clearInlineVerdictHighlights() {
  if (window.CSS && CSS.highlights) {
    CSS.highlights.delete("nf-violate");
    CSS.highlights.delete("nf-unknown");
  }

  const editor = document.getElementById("editor");
  if (!editor) return;
  const spans = editor.querySelectorAll(".nf-highlight-fallback");
  spans.forEach((span) => {
    const parent = span.parentNode;
    if (!parent) return;
    while (span.firstChild) parent.insertBefore(span.firstChild, span);
    parent.removeChild(span);
  });
  if (spans.length > 0) {
    editor.normalize();
  }
  fallbackHighlightActive = false;
}

function renderInlineVerdictHighlights(verdicts) {
  clearInlineVerdictHighlights();
  const editor = document.getElementById("editor");
  if (!editor) return;
  const text = editor.textContent || "";
  if (!text) return;

  const textNodes = _collectEditorTextNodes(editor);
  if (!textNodes.length) return;

  const rows = Array.isArray(verdicts) ? verdicts : [];
  const highlightItems = [];

  rows.forEach((item) => {
    const verdict = String(item?.verdict || "UNKNOWN");
    if (verdict !== "VIOLATE" && verdict !== "UNKNOWN") return;
    const span =
      item && typeof item.segment_span === "object"
        ? item.segment_span
        : {};
    const start = Number.isInteger(span.start) ? span.start : null;
    const end = Number.isInteger(span.end) ? span.end : null;
    if (
      start === null ||
      end === null ||
      end <= start ||
      start < 0 ||
      start >= text.length
    )
      return;
    const clampedEnd = Math.min(end, text.length);
    if (clampedEnd <= start) return;
    highlightItems.push({ start, end: clampedEnd, verdict });
  });

  if (
    window.CSS &&
    CSS.highlights &&
    typeof window.Highlight === "function"
  ) {
    const violateRanges = [];
    const unknownRanges = [];
    highlightItems.forEach(({ start, end, verdict }) => {
      const startPos = _positionForOffset(textNodes, start);
      const endPos = _positionForOffset(textNodes, end);
      if (!startPos || !endPos) return;
      const range = document.createRange();
      range.setStart(startPos.node, startPos.offset);
      range.setEnd(endPos.node, endPos.offset);
      if (verdict === "VIOLATE") violateRanges.push(range);
      else unknownRanges.push(range);
    });

    if (violateRanges.length > 0) {
      CSS.highlights.set("nf-violate", new Highlight(...violateRanges));
    }
    if (unknownRanges.length > 0) {
      CSS.highlights.set("nf-unknown", new Highlight(...unknownRanges));
    }
  } else {
    fallbackHighlightActive = true;
    highlightItems.sort((a, b) => b.start - a.start);
    highlightItems.forEach(({ start, end, verdict }) => {
      const startPos = _positionForOffset(textNodes, start);
      const endPos = _positionForOffset(textNodes, end);
      if (!startPos || !endPos) return;
      const range = document.createRange();
      range.setStart(startPos.node, startPos.offset);
      range.setEnd(endPos.node, endPos.offset);

      const span = document.createElement("span");
      const bgClass =
        verdict === "VIOLATE" ? "nf-violate-bg" : "nf-unknown-bg";
      span.className = `nf-highlight-fallback ${bgClass}`;

      try {
        range.surroundContents(span);
      } catch (e) {
        const contents = range.extractContents();
        span.appendChild(contents);
        range.insertNode(span);
      }
    });
  }
}

// ... (Config Management omitted, stays same) ...
