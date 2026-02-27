// --- UI/Widget Toggles ---
function toggleLeftSidebar() {
  document.getElementById("nav-sidebar").classList.toggle("mobile-open");
  if (typeof _notifyLayoutDependents === "function") {
    _notifyLayoutDependents();
  } else {
    window.dispatchEvent(new Event("nf:layout-changed"));
  }
}

function toggleJobsPanel() {
  const panel = document.getElementById("jobs-panel");
  const badge = document.getElementById("jobs-status-badge");
  panel.classList.toggle("active");
  if (panel.classList.contains("active")) {
    badge.classList.add("active");
    fetchRecentJobs();
  } else {
    badge.classList.remove("active");
  }
}

function toggleConsistencyPanel() {
  const panel = document.getElementById("consistency-panel");
  panel.classList.toggle("active");
}

async function fetchRecentJobs() {
  const listContainer = document.getElementById("jobs-list-content");
  listContainer.innerHTML =
    '<div style="text-align:center; color:#94a3b8; font-size:0.85rem; padding:10px;">불러오는 중...</div>';
  if (!state.projectId) {
    listContainer.innerHTML =
      '<div style="text-align:center; color:#94a3b8; font-size:0.85rem; padding:10px;">프로젝트를 먼저 선택하세요.</div>';
    return;
  }
  try {
    const res = await api(
      `/jobs?project_id=${encodeURIComponent(state.projectId)}&limit=5`,
    );
    const jobs = res.jobs || [];
    if (jobs.length === 0) {
      listContainer.innerHTML =
        '<div style="text-align:center; color:#94a3b8; font-size:0.85rem; padding:10px;">진행 중이거나 최근 작업이 없습니다.</div>';
      document.getElementById("jobs-status-text").innerText = "작업 대기";
      return;
    }

    let activeCount = 0;
    let html = "";
    jobs.forEach((job) => {
      if (["QUEUED", "RUNNING"].includes(job.status)) activeCount++;

      let statusColor = "#64748b";
      let pgColor = "#e2e8f0";
      let progress =
        typeof job.progress === "number" ? job.progress : 0;
      let itemClass = "job-item";

      if (job.status === "SUCCEEDED") {
        statusColor = "#16a34a";
        progress = 100;
        pgColor = "#22c55e";
        itemClass += " completed";
      } else if (job.status === "FAILED") {
        statusColor = "#dc2626";
        progress = 100;
        pgColor = "#ef4444";
        itemClass += " failed";
      } else if (job.status === "RUNNING") {
        statusColor = "#2563eb";
        progress = Math.max(25, progress || 0);
        pgColor = "#3b82f6";
        itemClass += " running";
      } else if (job.status === "QUEUED") {
        statusColor = "#2563eb";
        progress = Math.max(8, progress || 0);
      } else if (job.status === "CANCELED") {
        statusColor = "#d97706";
        progress = 100;
      }

      let retryButton = "";
      if (job.status === "FAILED" || job.status === "CANCELED") {
        retryButton = `<button class="retry-job-btn" onclick="retryJob('${job.job_id}')" title="재시도">🔄 재시도</button>`;
      }

      html += `
            <div class="${itemClass}">
              <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                <strong>${escapeHtml(job.type)}</strong>
                <span style="color:${statusColor}; font-weight:600; font-size:0.75rem;">${escapeHtml(job.status)}</span>
              </div>
              <div style="font-size:0.75rem; color:#64748b;">ID: ${escapeHtml(job.job_id.split("-")[0])}... | ${new Date(job.created_at).toLocaleTimeString()}</div>
              <div class="job-progress-bar">
                <div class="job-progress-fill" style="width:${progress}%; background:${pgColor};"></div>
              </div>
              ${retryButton}
            </div>
          `;
    });

    listContainer.innerHTML = html;
    if (activeCount > 0) {
      document.getElementById("jobs-status-text").innerText =
        `작업 중(${activeCount})`;
      document
        .getElementById("jobs-status-badge")
        .classList.add("warning");
    } else {
      document.getElementById("jobs-status-text").innerText = "작업 휴식";
      document
        .getElementById("jobs-status-badge")
        .classList.remove("warning");
    }
  } catch (e) {
    listContainer.innerHTML = `<div style="text-align:center; color:#dc2626; font-size:0.85rem; padding:10px;">로드 실패</div>`;
  }
}

window.retryJob = async function (jobId) {
  if (!state.projectId) return;
  try {
    const res = await api(`/jobs/${encodeURIComponent(jobId)}/retry`, "POST");
    const nextJobId = res?.job?.job_id;
    if (typeof showSuccess === "function") {
      const preview =
        typeof nextJobId === "string" && nextJobId
          ? `${nextJobId.split("-")[0]}...`
          : "";
      showSuccess(preview ? `재시도 작업 생성: ${preview}` : "재시도 작업 생성");
    }
    await fetchRecentJobs();
  } catch (e) {
    alert("재시도 실패: " + e.message);
  }
}

