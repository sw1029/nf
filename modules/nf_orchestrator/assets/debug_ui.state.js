
      const state = {
        debugToken: "",
        apiToken: "",
        activeProjectId: "",
        lastDocId: "",
        lastSnapshotId: "",
        lastJobId: "",
        lastEventId: 0,
        sse: null,
        lastPayload: null,
        vectorSse: null,
        suggestSse: null,
        proofreadSse: null,
        exportSse: null,
        lintItems: [],
        requestLog: [],
        lastRequest: null,
        projectSettings: {},
        serverConfig: null,
      };

      const el = (id) => document.getElementById(id);

      const statusLine = el("status-line");
      const debugTokenInput = el("debug-token");
      const apiTokenInput = el("api-token");
      const configOutput = el("config-output");
      const consoleLog = el("console-log");

      function setStatus(text) {
        statusLine.textContent = text;
      }
      function logLine(text) {
        const line = document.createElement("div");
        line.className = "console-line";
        line.textContent = text;
        consoleLog.prepend(line);
      }
      function logJSON(label, data) {
        logLine(label + ": " + JSON.stringify(data));
      }
      function escapeHtml(value) {
        return value
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
      }
      function saveTokens() {
        state.debugToken = debugTokenInput.value.trim();
        state.apiToken = apiTokenInput.value.trim();
        localStorage.setItem("nf_debug_token", state.debugToken);
        localStorage.setItem("nf_api_token", state.apiToken);
        setStatus("토큰을 업데이트했습니다.");
      }
      function loadTokens() {
        const debugToken = new URLSearchParams(window.location.search).get("debug_token");
        const savedDebug = localStorage.getItem("nf_debug_token") || "";
        const savedApi = localStorage.getItem("nf_api_token") || "";
        state.debugToken = debugToken || savedDebug;
        state.apiToken = savedApi;
        debugTokenInput.value = state.debugToken;
        apiTokenInput.value = state.apiToken;
      }
