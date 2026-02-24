      function recordRequest(entry) {
        state.lastRequest = entry;
        state.requestLog.unshift(entry);
        if (state.requestLog.length > 20) {
          state.requestLog.pop();
        }
        renderRequestLog();
      }
      function buildCurl(entry) {
        const origin = window.location.origin || "http://127.0.0.1:8080";
        const parts = ["curl -s", "-X", entry.method];
        Object.entries(entry.headers || {}).forEach(([key, value]) => {
          parts.push("-H");
          parts.push(`'${key}: ${value}'`);
        });
        if (entry.bodyText) {
          const body = entry.bodyText.replace(/'/g, "'\\''");
          parts.push("-d");
          parts.push(`'${body}'`);
        }
        parts.push(origin + entry.path);
        return parts.join(" ");
      }
      function renderRequestLog() {
        const logList = el("log-list");
        if (!logList) {
          return;
        }
        logList.innerHTML = "";
        state.requestLog.slice(0, 8).forEach((entry) => {
          const card = document.createElement("div");
          card.className = "log-item";
          const headline = document.createElement("div");
          headline.textContent =
            entry.method + " " + entry.path + " (" + entry.status + ")";
          const meta = document.createElement("div");
          meta.className = "small mono";
          meta.textContent = entry.ts;
          card.appendChild(headline);
          card.appendChild(meta);
          logList.appendChild(card);
        });
      }
      function downloadLog() {
        const blob = new Blob([JSON.stringify(state.requestLog, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "nf_debug_requests.json";
        link.click();
        URL.revokeObjectURL(url);
      }
      function readJSON(text, fallback) {
        if (!text || !text.trim()) {
          return fallback;
        }
        try {
          return JSON.parse(text);
        } catch (err) {
          throw new Error("유효하지 않은 JSON: " + err.message);
        }
      }
      function formatJSON(value) {
        return JSON.stringify(value, null, 2);
      }
      function setTextareaJSON(textareaId, value) {
        const textarea = el(textareaId);
        if (!textarea) {
          throw new Error("textarea not found: " + textareaId);
        }
        textarea.value = formatJSON(value);
      }
