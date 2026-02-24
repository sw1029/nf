      function connectSSE(afterId) {
        const jobId = el("sse-job-id").value.trim();
        if (!jobId) {
          throw new Error("작업 ID를 입력하세요.");
        }
        disconnectSSE();
        const params = new URLSearchParams();
        if (state.apiToken) {
          params.set("token", state.apiToken);
        }
        if (afterId) {
          params.set("after", String(afterId));
        }
        const url = `/jobs/${jobId}/events` + (params.toString() ? "?" + params.toString() : "");
        const es = new EventSource(url);
        state.sse = es;
        el("sse-events").innerHTML = "";
        es.onmessage = (evt) => {
          const data = JSON.parse(evt.data);
          if (evt.lastEventId) {
            state.lastEventId = parseInt(evt.lastEventId, 10) || 0;
            el("sse-last-id").value = state.lastEventId;
          }
          const line = document.createElement("div");
          line.className = "console-line";
          line.textContent = data.ts + " [" + data.level + "] " + data.message;
          el("sse-events").prepend(line);
          if (typeof data.progress === "number") {
            el("sse-progress").style.width = Math.round(data.progress * 100) + "%";
          }
          state.lastPayload = data.payload || null;
          if (data.payload) {
            el("sse-payload").textContent = JSON.stringify(data.payload, null, 2);
            logJSON("이벤트 페이로드", data.payload);
          }
        };
        es.onerror = () => {
          logLine("SSE 오류 또는 연결 종료.");
        };
        logLine("SSE 연결됨.");
      }
      function disconnectSSE() {
        if (state.sse) {
          state.sse.close();
          state.sse = null;
          logLine("SSE 연결 해제됨.");
        }
      }
      function reconnectSSE() {
        const lastIdRaw = el("sse-last-id").value.trim();
        const afterId = parseInt(lastIdRaw, 10) || state.lastEventId || 0;
        connectSSE(afterId);
      }
      function stopVectorStream() {
        if (state.vectorSse) {
          state.vectorSse.close();
          state.vectorSse = null;
          logLine("벡터 스트림을 중지했습니다.");
        }
      }
      function connectVectorStream(jobId) {
        stopVectorStream();
        const params = new URLSearchParams();
        if (state.apiToken) {
          params.set("token", state.apiToken);
        }
        const url = `/jobs/${jobId}/events` + (params.toString() ? "?" + params.toString() : "");
        const es = new EventSource(url);
        state.vectorSse = es;
        const resultsEl = el("vector-results");
        resultsEl.innerHTML = "";
        es.onmessage = (evt) => {
          const data = JSON.parse(evt.data);
          const payload = data.payload || {};
          const results = payload.results || [];
          results.forEach((res) => {
            const card = document.createElement("div");
            card.className = "result-card";
            const title = document.createElement("div");
            title.textContent = res.section_path || res.doc_id || "벡터";
            const snippet = document.createElement("div");
            snippet.textContent = res.snippet || "";
            const meta = document.createElement("div");
            meta.className = "small mono";
            meta.textContent = JSON.stringify(res.evidence || {});
            card.appendChild(title);
            card.appendChild(snippet);
            card.appendChild(meta);
            resultsEl.appendChild(card);
          });
        };
        es.onerror = () => {
          logLine("벡터 스트림 오류 또는 연결 종료.");
        };
      }
      function stopSuggestStream() {
        if (state.suggestSse) {
          state.suggestSse.close();
          state.suggestSse = null;
        }
      }
      function connectSuggestStream(jobId) {
        stopSuggestStream();
        const params = new URLSearchParams();
        if (state.apiToken) {
          params.set("token", state.apiToken);
        }
        const url = `/jobs/${jobId}/events` + (params.toString() ? "?" + params.toString() : "");
        const es = new EventSource(url);
        state.suggestSse = es;
        es.onmessage = (evt) => {
          const data = JSON.parse(evt.data);
          const payload = data.payload || {};
          if (payload.text) {
            el("suggest-output").textContent = payload.text;
          }
          const citations = payload.citations || [];
          const list = el("suggest-citations");
          list.innerHTML = "";
          citations.forEach((c) => {
            const card = document.createElement("div");
            card.className = "result-card";
            card.textContent = c.tag_path + " " + c.section_path + " " + c.snippet_text;
            list.appendChild(card);
          });
        };
        es.onerror = () => {
          logLine("제안 스트림 오류 또는 연결 종료.");
        };
      }
      function stopProofreadStream() {
        if (state.proofreadSse) {
          state.proofreadSse.close();
          state.proofreadSse = null;
        }
      }
      function connectProofreadStream(jobId) {
        stopProofreadStream();
        const params = new URLSearchParams();
        if (state.apiToken) {
          params.set("token", state.apiToken);
        }
        const url = `/jobs/${jobId}/events` + (params.toString() ? "?" + params.toString() : "");
        const es = new EventSource(url);
        state.proofreadSse = es;
        es.onmessage = (evt) => {
          const data = JSON.parse(evt.data);
          const payload = data.payload || {};
          if (payload.lint_items) {
            state.lintItems = payload.lint_items;
            renderLintItems(payload.lint_items);
            renderPreview();
          }
        };
        es.onerror = () => {
          logLine("교정 스트림 오류 또는 연결 종료.");
        };
      }
      function stopExportStream() {
        if (state.exportSse) {
          state.exportSse.close();
          state.exportSse = null;
        }
      }
      function connectExportStream(jobId) {
        stopExportStream();
        const params = new URLSearchParams();
        if (state.apiToken) {
          params.set("token", state.apiToken);
        }
        const url = `/jobs/${jobId}/events` + (params.toString() ? "?" + params.toString() : "");
        const es = new EventSource(url);
        state.exportSse = es;
        es.onmessage = (evt) => {
          const data = JSON.parse(evt.data);
          const payload = data.payload || {};
          if (payload.artifact_path) {
            el("export-output").textContent = JSON.stringify(payload, null, 2);
          }
        };
        es.onerror = () => {
          logLine("내보내기 스트림 오류 또는 연결 종료.");
        };
      }
