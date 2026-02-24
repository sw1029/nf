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
      function showLoading(msg = "처리 중입니다...", blocking = false) {
        if (blocking || !state.projectId) {
          document.getElementById("loading-text").innerText = msg;
          document.getElementById("loading-overlay").classList.add("active");
        } else {
          const el = document.getElementById("save-status");
          if (el) {
            el.innerText = msg;
            el.style.color = "#3498db";
          }
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
          el.innerText = "준비됨";
          el.style.color = "#aaa";
        }
      }

      function showSuccess(msg = "완료되었습니다.") {
        const el = document.getElementById("save-status");
        if (el) {
          el.innerText = msg;
          el.style.color = "#2ecc71";
          setTimeout(() => {
            if (el.innerText === msg) {
              el.innerText = "준비됨";
              el.style.color = "#aaa";
            }
          }, 3000);
        }
      }

      function closeSuccessPopup() {
        document.getElementById("success-popup").classList.remove("active");
      }

      function toggleConfigPanel() {
        document.getElementById("config-panel").classList.toggle("active");
      }

      function toggleRightSidebar() {
        const sb = document.getElementById("assistant-sidebar");
        sb.style.display = sb.style.display === "none" ? "flex" : "none";
      }
