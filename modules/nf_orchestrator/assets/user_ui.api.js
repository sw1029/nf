      // --- API Helper ---
      async function api(path, method = "GET", body = null) {
        try {
          const options = {
            method,
            headers: { "Content-Type": "application/json" },
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

      function toggleRightSidebar() {
        const sb = document.getElementById("assistant-sidebar");
        if (!sb) return;
        sb.classList.toggle("is-open");
        requestAnimationFrame(() => {
          if (typeof layoutMemoSidebar === "function") layoutMemoSidebar();
          if (typeof renderMemos === "function") renderMemos();
          if (typeof schedulePageGuideRender === "function")
            schedulePageGuideRender();
        });
      }
