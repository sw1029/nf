
// --- API Helper ---
async function api(path, method = "GET", body = null) {
  try {
    const headers = { "Content-Type": "application/json" };
    const apiKey = localStorage.getItem("nf_api_key");
    if (apiKey) headers["Authorization"] = "Bearer " + apiKey;
    const localModel = localStorage.getItem("nf_api_model");
    if (localModel) headers["X-NF-Model"] = localModel;

    const options = {
      method,
      headers,
    };
    if (body) options.body = JSON.stringify(body);

    const res = await fetch(path, options);
    if (!res.ok) {
      const errBody = await res.text();
      console.error("API Error Body:", errBody);
      throw new Error(res.statusText + " " + errBody);
    }
    return await res.json();
  } catch (e) {
    console.error("API Error", e);
    throw e;
  }
}

// --- Loading & Success UI ---
function _setStatusLabels(text, color) {
  const toolbar = document.getElementById("save-status");
  if (toolbar) {
    toolbar.innerText = text;
    if (color) toolbar.style.color = color;
  }
  const bar = document.getElementById("save-status-text");
  if (bar) {
    bar.innerText = text;
    if (color) bar.style.color = color;
  }
}

function showLoading(msg = "처리 중입니다...", blocking = false) {
  if (blocking || !state.projectId) {
    document.getElementById("loading-text").innerText = msg;
    document.getElementById("loading-overlay").classList.add("active");
  } else {
    _setStatusLabels(msg, "#3498db");
  }
}

function hideLoading() {
  document.getElementById("loading-overlay").classList.remove("active");
  const el = document.getElementById("save-status");
  if (
    el &&
    (el.style.color === "rgb(52, 152, 219)" ||
      el.style.color === "#3498db")
  ) {
    // Only clear if we set it
    _setStatusLabels("준비됨", "#aaa");
  }
}

function showSuccess(msg = "완료되었습니다.") {
  const el = document.getElementById("save-status");
  if (!el) return;
  _setStatusLabels(msg, "#2ecc71");
  setTimeout(() => {
    if (el.innerText === msg) {
      _setStatusLabels("준비됨", "#aaa");
    }
  }, 3000);
}

function closeSuccessPopup() {
  document.getElementById("success-popup").classList.remove("active");
}

function toggleConfigPanel() {
  document.getElementById("config-panel").classList.toggle("active");
}

function _notifyLayoutDependents() {
  requestAnimationFrame(() => {
    if (typeof layoutMemoSidebar === "function") layoutMemoSidebar();
    if (typeof renderMemos === "function") renderMemos();
    if (typeof schedulePageGuideRender === "function")
      schedulePageGuideRender();
    if (typeof repositionInlineTagWidget === "function")
      repositionInlineTagWidget();
    if (typeof repositionTagRemovePopover === "function")
      repositionTagRemovePopover();
    if (typeof repositionActionPopover === "function")
      repositionActionPopover();
    window.dispatchEvent(new Event("nf:layout-changed"));
  });
}

function _readAnchorRect(anchorRect) {
  if (!anchorRect || typeof anchorRect !== "object") return null;
  const left = Number(anchorRect.left);
  const top = Number(anchorRect.top);
  const right = Number(anchorRect.right);
  const bottom = Number(anchorRect.bottom);
  if (
    !Number.isFinite(left) ||
    !Number.isFinite(top) ||
    !Number.isFinite(right) ||
    !Number.isFinite(bottom)
  ) {
    return null;
  }
  const widthRaw = Number(anchorRect.width);
  const heightRaw = Number(anchorRect.height);
  return {
    left,
    top,
    right,
    bottom,
    width: Number.isFinite(widthRaw) ? widthRaw : Math.max(0, right - left),
    height: Number.isFinite(heightRaw) ? heightRaw : Math.max(0, bottom - top),
  };
}

function positionPopoverInMainContent(popover, anchorRect, opts = {}) {
  if (!popover || !anchorRect) return false;
  const mainContent = document.querySelector(".main-content");
  if (!mainContent) return false;
  const rect = _readAnchorRect(anchorRect);
  if (!rect) return false;

  const mainRect = mainContent.getBoundingClientRect();
  const align = opts.align === "start" || opts.align === "end"
    ? opts.align
    : "center";
  const vertical = opts.vertical === "below" ? "below" : "above";
  const gap = Number.isFinite(Number(opts.gap)) ? Number(opts.gap) : 8;
  const margin = Number.isFinite(Number(opts.margin)) ? Number(opts.margin) : 8;
  const allowFlip = opts.allowFlip !== false;

  const localRect = {
    left: rect.left - mainRect.left,
    right: rect.right - mainRect.left,
    top: rect.top - mainRect.top,
    bottom: rect.bottom - mainRect.top,
    width: rect.width,
    height: rect.height,
  };

  const prevDisplay = popover.style.display;
  const prevVisibility = popover.style.visibility;
  let measuredHidden = false;
  if (
    prevDisplay === "none" ||
    window.getComputedStyle(popover).display === "none"
  ) {
    measuredHidden = true;
    popover.style.visibility = "hidden";
    popover.style.display = "block";
  }

  const popoverWidth = Math.max(0, popover.offsetWidth || 0);
  const popoverHeight = Math.max(0, popover.offsetHeight || 0);
  const maxLeft = Math.max(margin, mainContent.clientWidth - popoverWidth - margin);
  const maxTop = Math.max(margin, mainContent.clientHeight - popoverHeight - margin);

  let left = localRect.left;
  if (align === "center") {
    left = localRect.left + localRect.width / 2 - popoverWidth / 2;
  } else if (align === "end") {
    left = localRect.right - popoverWidth;
  }

  let top =
    vertical === "below"
      ? localRect.bottom + gap
      : localRect.top - popoverHeight - gap;
  if (allowFlip && vertical === "above" && top < margin) {
    top = localRect.bottom + gap;
  } else if (allowFlip && vertical === "below" && top > maxTop) {
    top = localRect.top - popoverHeight - gap;
  }

  left = Math.max(margin, Math.min(maxLeft, left));
  top = Math.max(margin, Math.min(maxTop, top));

  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;
  popover.style.transform = "none";

  if (measuredHidden) {
    popover.style.display = prevDisplay;
    popover.style.visibility = prevVisibility;
  }

  return true;
}

function openRightSidebar() {
  const sb = document.getElementById("assistant-sidebar");
  if (!sb) return;
  if (!sb.classList.contains("is-open")) sb.classList.add("is-open");
  _notifyLayoutDependents();
}

function closeRightSidebar() {
  const sb = document.getElementById("assistant-sidebar");
  if (!sb) return;
  if (sb.classList.contains("is-open")) sb.classList.remove("is-open");
  _notifyLayoutDependents();
}

function toggleRightSidebar() {
  const sb = document.getElementById("assistant-sidebar");
  if (!sb) return;
  sb.classList.toggle("is-open");
  _notifyLayoutDependents();
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const sb = document.getElementById("assistant-sidebar");
  if (!sb || !sb.classList.contains("is-open")) return;
  closeRightSidebar();
});
