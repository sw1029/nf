// --- Assistant ---
function switchAssistTab(eventOrMode, maybeMode) {
  const mode =
    typeof eventOrMode === "string" ? eventOrMode : String(maybeMode || "");
  const evt =
    typeof eventOrMode === "object" && eventOrMode !== null
      ? eventOrMode
      : null;
  if (!mode) return;
  document
    .querySelectorAll("#assistant-sidebar .tab-btn")
    .forEach((b) => b.classList.remove("active"));
  const targetBtn = evt?.currentTarget || evt?.target?.closest?.(".tab-btn");
  if (targetBtn) {
    targetBtn.classList.add("active");
  } else {
    const tabs = Array.from(
      document.querySelectorAll("#assistant-sidebar .tab-btn"),
    );
    const tabIndexByMode = { CHECK: 0, SEARCH: 1, PROPOSE: 2 };
    const idx = tabIndexByMode[mode];
    if (Number.isInteger(idx) && tabs[idx]) tabs[idx].classList.add("active");
  }

  state.assistantMode = mode;

  const btn = document.getElementById("assist-action-btn");
  if (mode === "CHECK") btn.innerText = "오류 점검하기";
  if (mode === "SEARCH") btn.innerText = "기억 검색하기";
  if (mode === "PROPOSE") btn.innerText = "현재 문단 다듬기 제안받기";

  document.querySelectorAll(".assist-panel-content").forEach(el => {
    el.style.display = 'none';
  });
  const activePanel = document.getElementById(`assist-panel-${mode}`);
  if (activePanel) activePanel.style.display = 'block';
}

// --- API Helper for Jobs ---
function _toProgressPercent(rawProgress) {
  const numeric = Number(rawProgress);
  if (!Number.isFinite(numeric)) return null;
  if (numeric <= 1.0)
    return Math.max(0, Math.min(100, Math.round(numeric * 100)));
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function _jobErrorMessage(job) {
  if (!job || typeof job !== "object") return "작업 실패";
  if (typeof job.error === "string" && job.error.trim()) return job.error;
  if (typeof job.error_message === "string" && job.error_message.trim())
    return job.error_message;
  return "작업 실패";
}

function _eventStatusText(eventObj) {
  if (!eventObj || typeof eventObj !== "object") return "";
  const level = String(eventObj.level || "").toUpperCase();
  const message = String(eventObj.message || "").trim();
  const payload =
    eventObj && typeof eventObj.payload === "object"
      ? eventObj.payload
      : {};
  const reasonCode = String(payload.reason_code || "").trim();
  if (reasonCode === "PAUSED_DUE_TO_MEMORY_PRESSURE") {
    const bdg = document.getElementById("memory-pressure-badge");
    if (bdg) {
      bdg.style.display = "inline-flex";
      clearTimeout(bdg.hideTimeout);
      bdg.hideTimeout = setTimeout(() => {
        bdg.style.display = "none";
      }, 5000);
    }
    return "메모리 압력으로 대기 중";
  }
  if (message && level) return `[${level}] ${message}`;
  if (message) return message;
  return "";
}

async function _waitForJobByPolling(
  jobId,
  onProgress,
  onStatus,
  startPct = 10,
) {
  let percentage = Math.max(0, Math.min(95, Number(startPct) || 10));
  return new Promise((resolve, reject) => {
    const check = async () => {
      try {
        const res = await api(`/jobs/${jobId}`);
        const job = res.job || {};
        const status = String(job.status || "");

        if (status === "SUCCEEDED") {
          if (onProgress) onProgress(100);
          if (onStatus) onStatus("작업 완료");
          resolve(job);
          return;
        }
        if (status === "FAILED" || status === "CANCELED") {
          if (onStatus) onStatus(`작업 실패 (${status})`);
          reject(new Error(_jobErrorMessage(job)));
          return;
        }

        percentage = Math.min(95, percentage + 8);
        if (onProgress) onProgress(percentage);
        if (onStatus) onStatus(`상태: ${status || "RUNNING"}`);
        setTimeout(check, 1000);
      } catch (e) {
        reject(e);
      }
    };
    check();
  });
}

async function _waitForJobViaSse(jobId, onProgress, onStatus) {
  if (typeof EventSource === "undefined") {
    throw new Error("eventsource-not-supported");
  }
  return new Promise((resolve, reject) => {
    const source = new EventSource(
      `/jobs/${encodeURIComponent(jobId)}/events`,
    );
    let done = false;
    let hasMessage = false;
    let fallbackPct = 10;
    let statusErrorCount = 0;
    let lastStatusText = "";

    const finish = (cb) => {
      if (done) return;
      done = true;
      clearInterval(statusTimer);
      source.close();
      cb();
    };

    const checkStatus = async () => {
      if (done) return;
      try {
        const res = await api(`/jobs/${jobId}`);
        const job = res.job || {};
        const status = String(job.status || "");
        if (status === "SUCCEEDED") {
          finish(() => {
            if (onProgress) onProgress(100);
            if (onStatus) onStatus("작업 완료");
            resolve(job);
          });
          return;
        }
        if (status === "FAILED" || status === "CANCELED") {
          finish(() => {
            if (onStatus) onStatus(`작업 실패 (${status})`);
            reject(new Error(_jobErrorMessage(job)));
          });
          return;
        }
        if (!hasMessage) {
          fallbackPct = Math.min(90, fallbackPct + 6);
          if (onProgress) onProgress(fallbackPct);
          const fallbackStatusText = `상태: ${status || "RUNNING"}`;
          if (onStatus && fallbackStatusText !== lastStatusText) {
            lastStatusText = fallbackStatusText;
            onStatus(fallbackStatusText);
          }
        }
        statusErrorCount = 0;
      } catch (e) {
        statusErrorCount += 1;
        if (statusErrorCount >= 3) {
          finish(() => reject(e));
        }
      }
    };

    const statusTimer = setInterval(() => {
      void checkStatus();
    }, 1000);
    void checkStatus();

    source.onmessage = (evt) => {
      hasMessage = true;
      let payload;
      try {
        payload = JSON.parse(evt.data);
      } catch (_error) {
        return;
      }
      const pct = _toProgressPercent(payload?.progress);
      if (pct !== null && onProgress) onProgress(pct, payload);
      const nextStatusText = _eventStatusText(payload);
      if (
        onStatus &&
        nextStatusText &&
        nextStatusText !== lastStatusText
      ) {
        lastStatusText = nextStatusText;
        onStatus(nextStatusText, payload);
      }
    };

    source.onerror = () => {
      if (!done && !hasMessage) {
        finish(() => reject(new Error("sse-unavailable")));
      }
    };
  });
}

async function waitForJob(jobId, onProgress, onStatus) {
  try {
    return await _waitForJobViaSse(jobId, onProgress, onStatus);
  } catch (_sseError) {
    return _waitForJobByPolling(jobId, onProgress, onStatus);
  }
}

function schedulePostSavePipeline(docId, contentChanged = true) {
  if (!docId || !state.projectId || !contentChanged) return;
  state.postSavePipelinePendingDocId = docId;
  if (state.postSavePipelineTimer) clearTimeout(state.postSavePipelineTimer);
  state.postSavePipelineTimer = setTimeout(() => {
    state.postSavePipelineTimer = null;
    const pendingDocId = state.postSavePipelinePendingDocId;
    state.postSavePipelinePendingDocId = null;
    if (pendingDocId) {
      void runPostSavePipeline(pendingDocId);
    }
  }, 1400);
}

async function runPostSavePipeline(docId) {
  if (!state.projectId || !docId) return false;
  if (state.postSavePipelineRunning) {
    state.postSavePipelinePendingDocId = docId;
    return false;
  }
  state.postSavePipelineRunning = true;
  try {
    const ingest = await api("/jobs", "POST", {
      type: "INGEST",
      project_id: state.projectId,
      inputs: { doc_id: docId },
    });
    await waitForJob(ingest.job.job_id);
    const indexFts = await api("/jobs", "POST", {
      type: "INDEX_FTS",
      project_id: state.projectId,
      inputs: { scope: docId },
    });
    await waitForJob(indexFts.job.job_id);
    scheduleBackgroundConsistencyCheck(docId);
    return true;
  } catch (e) {
    console.error("post-save pipeline failed", e);
    return false;
  } finally {
    state.postSavePipelineRunning = false;
    const pendingDocId = state.postSavePipelinePendingDocId;
    state.postSavePipelinePendingDocId = null;
    if (pendingDocId) {
      schedulePostSavePipeline(pendingDocId, true);
    }
  }
}

function scheduleBackgroundConsistencyCheck(docId) {
  if (!docId || !state.projectId) return;
  if (
    !Array.isArray(state.pendingConsistencySegments) ||
    state.pendingConsistencySegments.length === 0
  )
    return;
  if (state.backgroundConsistencyTimer)
    clearTimeout(state.backgroundConsistencyTimer);
  state.backgroundConsistencyTimer = setTimeout(() => {
    void runBackgroundConsistencyCheck(docId);
  }, 2000);
}

async function runBackgroundConsistencyCheck(docId) {
  if (!state.projectId || !docId || state.backgroundConsistencyRunning)
    return;
  const queued = (
    Array.isArray(state.pendingConsistencySegments)
      ? state.pendingConsistencySegments
      : []
  ).filter(
    (item) =>
      item &&
      Number.isInteger(item.start) &&
      Number.isInteger(item.end) &&
      item.end > item.start,
  );
  const pending = _mergeConsistencySegments(queued).slice(0, 8);
  if (pending.length === 0) return;
  const waitingCount = Math.max(0, queued.length - pending.length);
  state.backgroundConsistencyRunning = true;

  const cStatusBadgeText = document.getElementById(
    "consistency-status-text",
  );
  const cStatusBadge = document.getElementById("consistency-badge");
  const cQueuedCount = document.getElementById(
    "consistency-queued-count",
  );

  const renderBackgroundStatus = (current, total, message = "") => {
    if (!cStatusBadgeText) return;
    cStatusBadgeText.innerText = `검토 중 ${Math.max(0, current)}/${Math.max(1, total)}`;
    cStatusBadge.classList.add("active");
    if (cQueuedCount) cQueuedCount.innerText = waitingCount;
  };
  if (cStatusBadgeText) {
    renderBackgroundStatus(0, pending.length);
  }

  try {
    for (let idx = 0; idx < pending.length; idx += 1) {
      const segment = pending[idx];
      renderBackgroundStatus(idx + 1, pending.length);
      const payload = _buildConsistencyJobPayload(
        docId,
        { start: segment.start, end: segment.end },
        {
          ensure_ingest: false,
          ensure_index_fts: false,
          schema_scope: "explicit_only",
        },
      );
      const res = await api("/jobs", "POST", payload);
      await waitForJob(res.job.job_id, undefined, (statusText) => {
        renderBackgroundStatus(idx + 1, pending.length, statusText);
      });
    }

    const vRes = await api("/query/verdicts", "POST", {
      project_id: state.projectId,
      input_doc_id: docId,
    });
    const verdicts = Array.isArray(vRes.verdicts) ? vRes.verdicts : [];
    const filtered = verdicts.filter((item) => {
      const span =
        item && typeof item.segment_span === "object"
          ? item.segment_span
          : {};
      const start = Number.isInteger(span.start) ? span.start : null;
      const end = Number.isInteger(span.end) ? span.end : null;
      if (start === null || end === null || end <= start) return false;
      return pending.some((segment) =>
        _spanOverlaps(start, end, segment.start, segment.end),
      );
    });
    if (filtered.length > 0) {
      renderVerdicts(filtered, { background: true });
    }
  } catch (e) {
    console.error("background consistency failed", e);
    if (cStatusBadgeText) {
      cStatusBadgeText.innerText = `검토 실패`;
      cStatusBadge.classList.remove("active");
      cStatusBadge.classList.add("warning");
    }
  } finally {
    state.backgroundConsistencyRunning = false;
    const remainingQueue = Array.isArray(state.pendingConsistencySegments)
      ? state.pendingConsistencySegments
      : [];
    state.pendingConsistencySegments = remainingQueue.filter((item) => {
      if (
        !item ||
        !Number.isInteger(item.start) ||
        !Number.isInteger(item.end)
      )
        return false;
      return !pending.some((segment) =>
        _spanOverlaps(item.start, item.end, segment.start, segment.end),
      );
    });

    if (document.getElementById("consistency-last-time")) {
      document.getElementById("consistency-last-time").innerText =
        new Date().toLocaleTimeString();
    }

    if (state.pendingConsistencySegments.length > 0) {
      if (cStatusBadgeText) {
        cStatusBadgeText.innerText = `대기 ${state.pendingConsistencySegments.length}건`;
        cStatusBadge.classList.remove("active");
      }
      if (cQueuedCount)
        cQueuedCount.innerText = state.pendingConsistencySegments.length;
      scheduleBackgroundConsistencyCheck(docId);
    } else if (cStatusBadgeText) {
      cStatusBadgeText.innerText = "상시 검토 중";
      cStatusBadge.classList.remove("active");
      cStatusBadge.classList.remove("warning");
      if (cQueuedCount) cQueuedCount.innerText = 0;
    }
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function verdictLabel(verdict) {
  if (verdict === "VIOLATE") return "설정 충돌";
  if (verdict === "OK") return "정합성 양호";
  return "사실 확인 필요";
}

async function runAssistantAction() {
  if (!state.currentDocId) return alert("문서를 먼저 여세요");

  const mode = state.assistantMode || "CHECK";
  const contentPanel = document.getElementById("assistant-content");

  if (mode === "SEARCH") {
    contentPanel.innerHTML =
      '<div style="text-align:center; padding:20px; color:#666;"><img src="/assets/img.gif" width="30"> 관련 내용을 검색 중입니다...</div>';
    try {
      const editor = document.getElementById("editor");
      const editorText = typeof getEditorText === "function"
        ? getEditorText()
        : (editor?.innerText || "");
      const query = editorText.substring(0, 500) || "내용 없음"; // Contextual search

      // Try Sync Retrieval (FTS)
      const res = await api("/query/retrieval", "POST", {
        project_id: state.projectId,
        query: query,
        k: 5,
      });

      if (!res.results || res.results.length === 0) {
        contentPanel.innerHTML =
          '<div style="padding:20px; text-align:center;">관련된 내용을 찾지 못했습니다.</div>';
        return;
      }

      let html =
        '<div style="padding:10px;"><strong>검색 결과</strong></div>';
      res.results.forEach((r) => {
        const evidence =
          r && typeof r === "object" && typeof r.evidence === "object"
            ? r.evidence
            : {};
        const docId = evidence.doc_id || r.doc_id || "";
        const snippet =
          evidence.snippet_text || r.snippet || "(본문 발췌 없음)";
        const title =
          docId && state.docs[docId] && state.docs[docId].title
            ? state.docs[docId].title
            : docId || "문서";
        const score = Number(r.score || 0);
        html += `
                    <div class="analysis-card info" style="cursor:pointer;" data-doc-id="${escapeHtml(docId)}">
                        <div style="font-weight:600; font-size:0.9rem;">${escapeHtml(title)}</div>
                        <div style="font-size:0.8rem; color:#666; margin-top:5px;">
                            ${escapeHtml(snippet)}
                        </div>
                        <div style="font-size:0.75rem; color:#999; margin-top:5px;">점수: ${Number.isFinite(score) ? score.toFixed(3) : "-"}</div>
                    </div>
                `;
      });
      contentPanel.innerHTML = html;
      contentPanel.querySelectorAll("[data-doc-id]").forEach((node) => {
        node.addEventListener("click", () => {
          const docId = node.getAttribute("data-doc-id") || "";
          if (docId) loadDoc(docId);
        });
      });
    } catch (e) {
      console.error(e);
      contentPanel.innerHTML = `<div style="text-align:center; padding:20px; color:red;">검색 실패<br>${e.message}</div>`;
    }
    return;
  }

  if (mode === "PROPOSE") {
    contentPanel.innerHTML =
      '<div style="text-align:center; padding:20px;"><img src="/assets/img.gif" width="30" alt="loading"><br>문장 제안을 생성 중입니다...</div>';
    try {
      const editor = document.getElementById("editor");
      const selectedText = window.getSelection
        ? String(window.getSelection().toString() || "").trim()
        : "";
      const editorText = typeof getEditorText === "function"
        ? getEditorText()
        : (editor?.innerText || "");
      const sourceText = (selectedText || editorText || "").trim();
      if (!sourceText) {
        contentPanel.innerHTML =
          '<div style="padding:20px; text-align:center;">제안할 문장이 없습니다.</div>';
        return;
      }

      const levelInput = document.querySelector(
        'input[name="propose-level"]:checked',
      );
      const level =
        levelInput && typeof levelInput.value === "string"
          ? levelInput.value
          : "spell";
      let suggestMode = "LOCAL_RULE";
      if (level === "smooth" || level === "dramatic") {
        suggestMode = "LOCAL_GEN";
      }

      const suggestJob = await api("/jobs", "POST", {
        type: "SUGGEST",
        project_id: state.projectId,
        inputs: {
          mode: suggestMode,
          claim_text: sourceText.slice(0, 2000),
          include_citations: true,
          range: { doc_id: state.currentDocId },
          k: 5,
        },
      });
      const jobId = suggestJob?.job?.job_id;
      if (!jobId) throw new Error("suggest job id missing");
      await waitForJob(jobId);

      const jobRes = await api(`/jobs/${jobId}`);
      const result =
        jobRes &&
          jobRes.job &&
          typeof jobRes.job.result === "object" &&
          jobRes.job.result
          ? jobRes.job.result
          : {};
      const suggestedText =
        typeof result.text === "string" ? result.text : "";
      const citations = Array.isArray(result.citations)
        ? result.citations
        : [];
      if (!suggestedText) {
        contentPanel.innerHTML =
          '<div style="padding:20px; text-align:center;">제안 결과가 비어 있습니다.</div>';
        return;
      }

      let html = `
              <div class="analysis-card info">
                <div style="font-weight:700; margin-bottom:8px;">제안 결과</div>
                <div style="white-space:pre-wrap; line-height:1.6;">${escapeHtml(suggestedText)}</div>
              </div>
            `;
      if (citations.length > 0) {
        html += `<div class="analysis-card" style="margin-top:10px;"><div style="font-weight:600; margin-bottom:6px;">근거</div>`;
        citations.slice(0, 5).forEach((citation) => {
          const docId = citation?.doc_id || "";
          const title =
            docId && state.docs[docId] && state.docs[docId].title
              ? state.docs[docId].title
              : docId || "문서";
          const snippet = citation?.snippet_text || "";
          html += `
                  <div style="padding:8px 0; border-top:1px dashed #e2e8f0;">
                    <div style="font-size:0.82rem; font-weight:600;">${escapeHtml(title)}</div>
                    <div style="font-size:0.8rem; color:#64748b; margin-top:4px;">${escapeHtml(snippet)}</div>
                  </div>
                `;
        });
        html += "</div>";
      }
      contentPanel.innerHTML = html;
    } catch (e) {
      console.error(e);
      contentPanel.innerHTML = `<div style="color:red; padding:20px;">제안 생성 실패: ${e.message}</div>`;
    }
    return;
  }

  // CHECK Mode
  contentPanel.innerHTML =
    '<div style="text-align:center; padding:20px;"><img src="/assets/img.gif" width="40" alt="loading"><br>AI가 분석 중입니다... <span id="check-progress">0%</span></div>';

  try {
    // 1. Submit Job
    const payload = _buildConsistencyJobPayload(
      state.currentDocId,
      {
        start: 0,
        end: Math.max(
          1,
          (typeof getEditorText === "function"
            ? getEditorText()
            : (document.getElementById("editor")?.innerText || "")).length,
        ),
      },
      {
        ensure_ingest: true,
        ensure_index_fts: true,
        schema_scope: "explicit_only",
      },
    );
    const res = await api("/jobs", "POST", payload);

    const jobId = res.job.job_id;

    // 2. Poll for completion
    await waitForJob(
      jobId,
      (pct) => {
        const el = document.getElementById("check-progress");
        if (el) el.innerText = `${pct}%`;
      },
      (statusText) => {
        const el = document.getElementById("check-progress");
        if (!el) return;
        const base =
          el.innerText && el.innerText.includes("%")
            ? el.innerText.split("%")[0]
            : "";
        const pctText = base ? `${base}%` : el.innerText;
        el.innerText = statusText
          ? `${pctText} | ${statusText}`
          : pctText;
      },
    );

    // 3. Fetch Verdicts
    // Note: Currently calling POST /query/verdicts is the way to list verdicts for a doc
    const vRes = await api("/query/verdicts", "POST", {
      project_id: state.projectId,
      input_doc_id: state.currentDocId,
    });

    renderVerdicts(vRes.verdicts || []);
    showSuccess("점검이 완료되었습니다.");
  } catch (e) {
    console.error(e);
    contentPanel.innerHTML = `<div style="color:red; padding:20px;">분석 실패: ${e.message}</div>`;
  }
}

function renderVerdicts(verdicts, options = {}) {
  const contentPanel = document.getElementById("assistant-content");
  const rows = Array.isArray(verdicts) ? verdicts : [];
  state.lastVerdicts = rows;

  const showOk = Boolean(state.showOkVerdicts);
  const visible = showOk
    ? rows
    : rows.filter((item) => String(item?.verdict || "UNKNOWN") !== "OK");
  if (visible.length === 0) {
    clearInlineVerdictHighlights();
    contentPanel.innerHTML = showOk
      ? '<div style="padding:20px; text-align:center;">정합성 판정 결과가 없습니다.</div>'
      : '<div style="padding:20px; text-align:center;">충돌 또는 확인 필요 항목이 없습니다.</div>';
    return;
  }

  let html = "";
  if (options && options.background) {
    html +=
      '<div style="padding:8px 10px; font-size:0.8rem; color:#64748b;">백그라운드 점검으로 변경 구간 결과가 갱신되었습니다.</div>';
  }
  visible.forEach((v, idx) => {
    const verdict = String(v.verdict || "UNKNOWN");
    const severityClass =
      verdict === "VIOLATE"
        ? "error"
        : verdict === "UNKNOWN"
          ? "unknown"
          : "info";
    const title = verdictLabel(verdict);
    const claimText =
      typeof v.claim_text === "string" && v.claim_text.trim()
        ? v.claim_text
        : "내용 없음";
    const unknownReasonsRaw = Array.isArray(v.unknown_reasons)
      ? v.unknown_reasons
      : [];
    const unknownReasons = unknownReasonsRaw
      .map((item) => String(item || "").trim())
      .filter((item) => item.length > 0);
    const unknownReasonText =
      unknownReasons.length > 0
        ? unknownReasons.join(", ")
        : "근거가 부족하거나 의미가 모호합니다.";
    const reliability = Number(v.reliability_overall || 0);
    const segmentSpan =
      v && typeof v.segment_span === "object" ? v.segment_span : {};
    const spanStart = Number.isInteger(segmentSpan.start)
      ? segmentSpan.start
      : null;
    const spanEnd = Number.isInteger(segmentSpan.end)
      ? segmentSpan.end
      : null;
    const spanLabel =
      spanStart !== null && spanEnd !== null
        ? `${spanStart} ~ ${spanEnd}`
        : "-";
    const detailId = `verdict-detail-${idx}`;
    const vid = typeof v.vid === "string" ? v.vid : "";
    const previewItems = Array.isArray(v.tag_path_preview_items)
      ? v.tag_path_preview_items
        .map((item) => String(item || "").trim())
        .filter((item) => item.length > 0)
      : [];
    const previewPrimary =
      typeof v.tag_path_preview === "string" && v.tag_path_preview.trim()
        ? v.tag_path_preview.trim()
        : previewItems[0] || "";

    html += `
                <div class="analysis-card ${severityClass}">
                    <div class="card-header">
                       <span class="card-title ${severityClass}">
                         ${verdict === "VIOLATE" ? "❌" : verdict === "UNKNOWN" ? "❓" : "✅"}
                         ${escapeHtml(title)}
                       </span>
                    </div>
                    <div class="claim-box">"${escapeHtml(claimText)}"</div>
                    
                    <div style="font-size:0.75rem; color:#64748b; margin-bottom:8px;">
                      <span style="margin-right:8px;">신뢰도: ${Number.isFinite(reliability) ? reliability.toFixed(2) : "-"}</span>
                    </div>
                    
                    <details style="margin-bottom:8px; font-size:0.8rem;">
                       <summary style="cursor:pointer; color:#475569; font-weight:600;">상세 정보 접기/펴기</summary>
                       <div style="margin-top:6px; padding:6px; background:#f8fafc; border-radius:4px; border:1px solid #e2e8f0;">
                          ${previewPrimary ? `<div style="margin-bottom:4px;"><strong>근거:</strong> ${escapeHtml(previewPrimary)}</div>` : ""}
                          ${verdict === "UNKNOWN" ? `<div style="margin-bottom:4px;"><strong>사유:</strong> ${escapeHtml(unknownReasonText)}</div>` : ""}
                          <div><strong>분석 범위:</strong> ${escapeHtml(spanLabel)}</div>
                       </div>
                    </details>
                    
                    <div class="card-actions">
                      <button class="btn btn-primary jump-claim" data-claim="${escapeHtml(claimText)}" data-span-start="${spanStart !== null ? spanStart : ""}" data-span-end="${spanEnd !== null ? spanEnd : ""}">🔍 본문에서 보기</button>
                      <button class="btn btn-secondary load-verdict-detail" data-vid="${escapeHtml(vid)}" data-target="${escapeHtml(detailId)}" ${vid ? "" : "disabled"}>상세 근거</button>
                      <button class="btn btn-secondary verdict-whitelist" data-claim="${escapeHtml(claimText)}" title="이 내용은 허용합니다">✔️ 예외 처리</button>
                      <button class="btn btn-secondary verdict-ignore" data-claim="${escapeHtml(claimText)}" title="이 경고를 무시합니다">숨기기</button>
                    </div>
                    <div id="${escapeHtml(detailId)}" style="font-size:0.8rem; color:#555; margin-top:8px;"></div>
                </div>
            `;
  });

  contentPanel.innerHTML = html;
  renderInlineVerdictHighlights(visible);
  contentPanel.querySelectorAll(".jump-claim").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      const quote = node.getAttribute("data-claim") || "";
      const rawStart = node.getAttribute("data-span-start");
      const rawEnd = node.getAttribute("data-span-end");
      const spanStart =
        rawStart !== null &&
          rawStart !== "" &&
          Number.isFinite(Number(rawStart))
          ? Number(rawStart)
          : null;
      const spanEnd =
        rawEnd !== null &&
          rawEnd !== "" &&
          Number.isFinite(Number(rawEnd))
          ? Number(rawEnd)
          : null;
      jumpToVerdictSegment(spanStart, spanEnd, quote);
    });
  });
  contentPanel
    .querySelectorAll(".load-verdict-detail")
    .forEach((node) => {
      node.addEventListener("click", async (event) => {
        event.stopPropagation();
        const vid = node.getAttribute("data-vid") || "";
        const targetId = node.getAttribute("data-target") || "";
        await loadVerdictDetail(vid, targetId);
      });
    });
  contentPanel.querySelectorAll(".verdict-whitelist").forEach((node) => {
    node.addEventListener("click", async (event) => {
      event.stopPropagation();
      const claimText = node.getAttribute("data-claim") || "";
      await markVerdictAsWhitelisted(claimText);
    });
  });
  contentPanel.querySelectorAll(".verdict-ignore").forEach((node) => {
    node.addEventListener("click", async (event) => {
      event.stopPropagation();
      const claimText = node.getAttribute("data-claim") || "";
      await markVerdictAsIgnored(claimText);
    });
  });
}

async function refreshVerdictsForCurrentDoc(options = {}) {
  if (!state.projectId || !state.currentDocId) return;
  const res = await api("/query/verdicts", "POST", {
    project_id: state.projectId,
    input_doc_id: state.currentDocId,
  });
  renderVerdicts(
    Array.isArray(res.verdicts) ? res.verdicts : [],
    options,
  );
}

async function markVerdictAsWhitelisted(claimText) {
  if (!state.projectId || !state.currentDocId || !claimText) return;
  try {
    await api(
      `/projects/${encodeURIComponent(state.projectId)}/whitelist`,
      "POST",
      {
        claim_text: claimText,
        scope: state.currentDocId,
        note: "user_ui_verdict_action",
      },
    );
    await refreshVerdictsForCurrentDoc();
  } catch (e) {
    console.error("failed to whitelist verdict", e);
    alert(`허용 목록 추가 실패: ${e.message}`);
  }
}

async function markVerdictAsIgnored(claimText) {
  if (!state.projectId || !state.currentDocId || !claimText) return;
  try {
    await api(
      `/projects/${encodeURIComponent(state.projectId)}/ignore`,
      "POST",
      {
        claim_text: claimText,
        scope: state.currentDocId,
        kind: "CONSISTENCY",
        note: "user_ui_verdict_action",
      },
    );
    await refreshVerdictsForCurrentDoc();
  } catch (e) {
    console.error("failed to ignore verdict", e);
    alert(`무시 처리 실패: ${e.message}`);
  }
}

async function loadVerdictDetail(vid, targetId) {
  const target = document.getElementById(targetId);
  if (!target || !vid || !state.projectId) return;
  target.innerHTML =
    '<span style="color:#888;">근거를 불러오는 중...</span>';
  try {
    const res = await api(
      `/query/verdicts/${encodeURIComponent(vid)}?project_id=${encodeURIComponent(state.projectId)}`,
    );
    const evidenceItemsRaw = Array.isArray(res.evidence)
      ? res.evidence
      : [];
    const evidenceItems = [...evidenceItemsRaw].sort((lhs, rhs) => {
      const leftRole = String(lhs?.role || "");
      const rightRole = String(rhs?.role || "");
      const leftRank = leftRole === "CONTRADICT" ? 0 : 1;
      const rightRank = rightRole === "CONTRADICT" ? 0 : 1;
      if (leftRank !== rightRank) return leftRank - rightRank;
      return leftRole.localeCompare(rightRole);
    });
    const claimFingerprint =
      typeof res.claim_fingerprint === "string"
        ? res.claim_fingerprint
        : "-";
    const whitelisted = Boolean(res.whitelisted);
    const ignored = Boolean(res.ignored);
    const unknownReasons = Array.isArray(res.unknown_reasons)
      ? res.unknown_reasons
        .map((item) => String(item || "").trim())
        .filter((item) => item.length > 0)
      : [];
    const factPaths = Array.isArray(res.fact_paths) ? res.fact_paths : [];
    const contradictCount = evidenceItems.filter(
      (item) => String(item?.role || "") === "CONTRADICT",
    ).length;
    const verdictInfo =
      res && typeof res.verdict === "object" ? res.verdict : {};
    const verdictType = String(verdictInfo.verdict || "UNKNOWN");

    let html = `
          <div style="margin-bottom:8px; padding:8px; background:#f8fafc; border-radius:6px;">
            <div><strong>허용 목록 포함:</strong> ${whitelisted}</div>
            <div><strong>무시 처리:</strong> ${ignored}</div>
            <div><strong>판정:</strong> ${escapeHtml(verdictType)}</div>
            <div><strong>클레임 식별값:</strong> ${escapeHtml(claimFingerprint)}</div>
            <div><strong>확인 필요 사유:</strong> ${escapeHtml(unknownReasons.length > 0 ? unknownReasons.join(", ") : "-")}</div>
            <div><strong>반박 근거 수:</strong> ${contradictCount}</div>
          </div>
        `;
    if (verdictType === "VIOLATE" && contradictCount <= 0) {
      html += `
            <div style="margin-bottom:8px; padding:8px; border-radius:6px; background:#fff7ed; color:#9a3412;">
              반박(CONTRADICT) 근거 연결이 없어 엔진 정책에 따라 판정이 UNKNOWN으로 하향될 수 있습니다.
            </div>
          `;
    }

    if (factPaths.length > 0) {
      html +=
        '<div style="margin-bottom:8px;"><strong>연관 사실 경로</strong></div>';
      factPaths.forEach((pathItem) => {
        const role = String(pathItem?.role || "-");
        const tagPath = String(pathItem?.tag_path || "-");
        const entityId = String(pathItem?.entity_id || "-");
        html += `
              <div style="margin-bottom:6px; padding:6px 8px; background:#eff6ff; border-radius:6px;">
                <div style="font-weight:600;">${escapeHtml(role)}</div>
                <div>태그 경로: ${escapeHtml(tagPath)}</div>
                <div>엔티티 ID: ${escapeHtml(entityId)}</div>
              </div>
            `;
      });
    }

    if (evidenceItems.length === 0) {
      target.innerHTML = `${html}<span style="color:#888;">연결된 근거가 없습니다.</span>`;
      return;
    }
    evidenceItems.forEach((item) => {
      const ev =
        item && typeof item.evidence === "object" ? item.evidence : {};
      const role = String(item.role || "-");
      const docId = String(ev.doc_id || "-");
      const tagPath = String(ev.tag_path || "-");
      const snippet = String(ev.snippet_text || "(본문 발췌 없음)");
      html += `
            <div style="margin-bottom:6px; padding:6px 8px; background:#f8fafc; border-radius:6px;">
              <div style="font-weight:600;">${escapeHtml(role)}</div>
              <div>문서: ${escapeHtml(docId)}</div>
              <div>태그: ${escapeHtml(tagPath)}</div>
              <div style="color:#666;">${escapeHtml(snippet)}</div>
            </div>
          `;
    });
    target.innerHTML = html;
  } catch (e) {
    target.innerHTML = `<span style="color:red;">근거 불러오기에 실패했습니다: ${escapeHtml(e.message || String(e))}</span>`;
  }
}

function _collectEditorTextNodes(editor) {
  const walker = document.createTreeWalker(
    editor,
    NodeFilter.SHOW_TEXT,
    null,
  );
  const nodes = [];
  let node = walker.nextNode();
  while (node) {
    const value = node.nodeValue || "";
    if (value.length > 0) {
      nodes.push(node);
    }
    node = walker.nextNode();
  }
  return nodes;
}

function _positionForOffset(textNodes, absoluteOffset) {
  if (!textNodes.length) return null;
  let consumed = 0;
  for (const node of textNodes) {
    const value = node.nodeValue || "";
    const nextConsumed = consumed + value.length;
    if (absoluteOffset <= nextConsumed) {
      return {
        node,
        offset: Math.max(
          0,
          Math.min(value.length, absoluteOffset - consumed),
        ),
      };
    }
    consumed = nextConsumed;
  }
  const tail = textNodes[textNodes.length - 1];
  return { node: tail, offset: (tail.nodeValue || "").length };
}

function highlightSpan(spanStart, spanEnd) {
  const editor = document.getElementById("editor");
  if (!editor) return false;
  if (!Number.isInteger(spanStart) || !Number.isInteger(spanEnd))
    return false;
  if (spanStart < 0 || spanEnd <= spanStart) return false;

  const text = editor.textContent || "";
  if (spanStart >= text.length) return false;
  const clampedEnd = Math.min(spanEnd, text.length);
  if (clampedEnd <= spanStart) return false;

  const textNodes = _collectEditorTextNodes(editor);
  if (!textNodes.length) return false;
  const startPos = _positionForOffset(textNodes, spanStart);
  const endPos = _positionForOffset(textNodes, clampedEnd);
  if (!startPos || !endPos) return false;

  const range = document.createRange();
  range.setStart(startPos.node, startPos.offset);
  range.setEnd(endPos.node, endPos.offset);

  const sel = window.getSelection();
  if (!sel) return false;
  sel.removeAllRanges();
  sel.addRange(range);

  const anchor = startPos.node.parentElement || editor;
  if (anchor && typeof anchor.scrollIntoView === "function") {
    anchor.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // Visual pulse feedback
  try {
    const pulseSpan = document.createElement("span");
    pulseSpan.className = "pulse-animation";
    range.surroundContents(pulseSpan);
    setTimeout(() => {
      if (pulseSpan.parentNode) {
        const parent = pulseSpan.parentNode;
        while (pulseSpan.firstChild) {
          parent.insertBefore(pulseSpan.firstChild, pulseSpan);
        }
        parent.removeChild(pulseSpan);
        if (editor) editor.normalize();
      }
    }, 2000);
  } catch (e) {
    // Range crosses node boundaries, animation skipped
  }

  editor.focus();
  return true;
}

function jumpToVerdictSegment(spanStart, spanEnd, quote) {
  if (highlightSpan(spanStart, spanEnd)) {
    return true;
  }
  return highlightText(quote);
}

function highlightText(quote) {
  if (!quote) return false;
  const editor = document.getElementById("editor");
  if (!editor) return false;
  const text = editor.textContent || "";
  const idx = text.indexOf(quote);
  if (idx < 0) {
    return false;
  }
  return highlightSpan(idx, idx + quote.length);
}

let actionPopoverFrame = null;

function _clearActionPopoverState() {
  state.activePopoverVerdict = null;
  state.actionPopoverAnchorRange = null;
  state.actionPopoverAnchorTarget = null;
}

function _positionActionPopoverAtRect(popover, rect) {
  if (!popover || !rect) return false;
  if (typeof positionPopoverInMainContent === "function") {
    return positionPopoverInMainContent(popover, rect, {
      align: "center",
      vertical: "below",
      gap: 10,
      margin: 8,
    });
  }
  popover.style.left = `${rect.left + window.scrollX}px`;
  popover.style.top = `${rect.bottom + window.scrollY + 10}px`;
  popover.style.transform = "translate(-50%, 0)";
  return true;
}

function repositionActionPopover() {
  const popover = document.getElementById("action-popover");
  if (!popover || popover.style.display !== "block") return false;

  let rect = null;
  if (state.actionPopoverAnchorRange && typeof state.actionPopoverAnchorRange.getBoundingClientRect === "function") {
    rect = state.actionPopoverAnchorRange.getBoundingClientRect();
  }
  if (
    (!rect || (!rect.width && !rect.height)) &&
    state.actionPopoverAnchorTarget &&
    typeof state.actionPopoverAnchorTarget.getBoundingClientRect === "function"
  ) {
    rect = state.actionPopoverAnchorTarget.getBoundingClientRect();
  }
  if (!rect || (!rect.width && !rect.height)) return false;

  return _positionActionPopoverAtRect(popover, rect);
}

function _scheduleActionPopoverReposition() {
  if (actionPopoverFrame !== null) return;
  actionPopoverFrame = requestAnimationFrame(() => {
    actionPopoverFrame = null;
    repositionActionPopover();
  });
}

window.repositionActionPopover = repositionActionPopover;

// --- Action Popover Logic ---
document.addEventListener("DOMContentLoaded", () => {
  // Consistency Level warning toggle
  const levelRadios = document.getElementsByName("consistency-level");
  const warningDiv = document.getElementById("intensity-warning");
  if (levelRadios && warningDiv) {
    levelRadios.forEach((r) => {
      r.addEventListener("change", (e) => {
        if (e.target.value === "strict" && e.target.checked) {
          warningDiv.style.display = "block";
          warningDiv.style.opacity = "0";
          setTimeout(() => {
            warningDiv.style.opacity = "1";
          }, 10);
        } else {
          warningDiv.style.opacity = "0";
          setTimeout(() => {
            warningDiv.style.display = "none";
          }, 300);
        }
      });
    });
  }

  const editor = document.getElementById("editor");
  if (editor) {
    editor.addEventListener("click", (e) => {
      const selection = window.getSelection();
      if (!selection || !selection.isCollapsed) return;

      const textNodes = _collectEditorTextNodes(editor);
      const pos = _getOffsetFromCaret(
        selection.anchorNode,
        selection.anchorOffset,
        textNodes,
      );
      if (pos === null) return;

      const verdicts = Array.isArray(state.lastVerdicts) ? state.lastVerdicts : [];
      const clickedVerdict = verdicts.find((v) => {
        const s = v.segment_span?.start;
        const end = v.segment_span?.end;
        return Number.isInteger(s) &&
          Number.isInteger(end) &&
          pos >= s &&
          pos <= end &&
          (v.verdict === "VIOLATE" || v.verdict === "UNKNOWN");
      });

      const popover = document.getElementById("action-popover");
      if (!popover) return;

      if (clickedVerdict) {
        if (selection.rangeCount <= 0) return;
        const range = selection.getRangeAt(0).cloneRange();
        state.actionPopoverAnchorRange = range;
        state.actionPopoverAnchorTarget =
          e.target instanceof Element ? e.target : null;

        popover.style.display = "block";
        repositionActionPopover();

        const titleEl = document.getElementById("popover-title");
        if (titleEl) titleEl.innerText = verdictLabel(clickedVerdict.verdict);

        const descEl = document.getElementById("popover-desc");
        const claim = clickedVerdict.claim_text || "내용 없음";
        if (descEl) {
          descEl.innerText =
            claim.length > 30 ? `${claim.substring(0, 30)}...` : claim;
        }

        state.activePopoverVerdict = clickedVerdict;
        return;
      }

      popover.style.display = "none";
      _clearActionPopoverState();
    });
  }

  const editorContainer = document.querySelector(".editor-container");
  if (editorContainer) {
    editorContainer.addEventListener(
      "scroll",
      () => {
        _scheduleActionPopoverReposition();
      },
      { passive: true },
    );
  }

  window.addEventListener("resize", _scheduleActionPopoverReposition);
  window.addEventListener("nf:layout-changed", _scheduleActionPopoverReposition);
});

function _getOffsetFromCaret(node, offset, textNodes) {
  let total = 0;
  for (const tn of textNodes) {
    if (tn === node) {
      return total + offset;
    }
    total += tn.nodeValue.length;
  }
  return null;
}

window.handlePopoverAction = async function (action) {
  const v = state.activePopoverVerdict;
  if (!v) return;
  const claim = v.claim_text;
  if (action === "whitelist") {
    await markVerdictAsWhitelisted(claim);
  } else if (action === "ignore") {
    await markVerdictAsIgnored(claim);
  }
  const popover = document.getElementById("action-popover");
  if (popover) popover.style.display = "none";
  _clearActionPopoverState();
};

document.addEventListener("mousedown", (e) => {
  const popover = document.getElementById("action-popover");
  const editor = document.getElementById("editor");
  if (popover && popover.style.display === "block") {
    if (!popover.contains(e.target) && (!editor || !editor.contains(e.target))) {
      popover.style.display = "none";
      _clearActionPopoverState();
    }
  }
});
