      // --- UI Helpers & Init ---
      function updateIcons() {
        if (window.lucide) {
          requestAnimationFrame(() => lucide.createIcons());
        }
      }

      function handleExport() {
        if (!state.currentDocId) {
          alert("먼저 문서를 열어주세요.");
          return closeExportModal();
        }
        const format = document.querySelector('input[name="export-fmt"]:checked').value;
        const title = document.getElementById("doc-title-input").value || "export";
        const contentText = document.getElementById("editor").innerText;
        
        if (format === 'txt') {
          const blob = new Blob([contentText], { type: "text/plain;charset=utf-8" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = title + ".txt";
          a.click();
          URL.revokeObjectURL(url);
        } else if (format === 'docx') {
          const preHtml = "<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'><head><meta charset='utf-8'><title>Export HTML To Doc</title></head><body>";
          const postHtml = "</body></html>";
          const html = preHtml + document.getElementById("editor").innerHTML + postHtml;
          const blob = new Blob(['\ufeff', html], { type: 'application/msword' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = title + ".doc";
          a.click();
          URL.revokeObjectURL(url);
        }
        closeExportModal();
      }

      function execCmd(command, value = null) {
        document.execCommand(command, false, value);
        document.getElementById("editor").focus();
        handleInput(); 
      }

      document.addEventListener("DOMContentLoaded", () => {
        updateIcons();
        const observer = new MutationObserver(() => updateIcons());
        observer.observe(document.body, { childList: true, subtree: true });
      });

      // --- Auto Save & Hotkeys ---
      document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "s") {
          e.preventDefault();
          saveDoc(true); // Immediate save
        }
      });

      // Auto-save Interval
      setInterval(() => {
        if (state.currentDocId && state.isDirty) {
          saveDoc(false); // Background save
        }
      }, 5000); // Check every 5 seconds

      // --- Editor Input Handler ---
      function handleInput() {
        state.isDirty = true;
        clearInlineVerdictHighlights();
        document.getElementById("save-status").innerText = "저장되지 않음";
        document.getElementById("save-status").style.color = "#e67e22";

        // Debounce still useful for stopping typing updates
        if (state.saveTimeout) clearTimeout(state.saveTimeout);
        state.saveTimeout = setTimeout(() => saveDoc(false), 2000);
      }

      async function saveDoc(immediate = false) {
        if (!state.currentDocId || (!state.isDirty && !immediate)) return;

        const content = document.getElementById("editor").innerText;
        const title = document.getElementById("doc-title-input").value; // Always get fresh title

        // Visual Feedback
        if (immediate) showLoading("저장 중...");
        else document.getElementById("save-status").innerText = "저장 중...";

        // Optimistic Update (Immediate UI Sync)
        if (state.docs[state.currentDocId]) {
          state.docs[state.currentDocId].title = title;
          state.docs[state.currentDocId].updated_at = new Date().toISOString();

          // Render based on current tab
          if (state.currentNavTab === "TIMELINE") {
            renderTimeline();
          } else {
            renderDocList();
          }
        }

        try {
          await api(
            `/projects/${state.projectId}/documents/${state.currentDocId}`,
            "PATCH",
            {
              title,
              content,
            },
          );
          const nextSegments = _segmentTextForConsistency(content);
          state.pendingConsistencySegments = _collectChangedSegments(
            state.lastSegmentFingerprints,
            nextSegments,
          );
          state.lastSegmentFingerprints = nextSegments;

          state.isDirty = false;
          document.getElementById("save-status").innerText = "저장됨";
          document.getElementById("save-status").style.color = "#aaa";
          if (immediate) hideLoading();
          schedulePostSavePipeline(state.currentDocId);

          // No need to render again unless we want to confirm from server
        } catch (e) {
          document.getElementById("save-status").innerText = "저장 실패";
          document.getElementById("save-status").style.color = "red";
          if (immediate) hideLoading();
          console.error(e);
        }
      }

      // --- Config Management ---
      function updateEditorConfig(key, value) {
        state.editorConfig[key] = value;
        const root = document.querySelector(":root");

        if (key === "fontSize")
          root.style.setProperty("--editor-font-size", value);
        if (key === "lineHeight")
          root.style.setProperty("--editor-line-height", value);
        if (key === "letterSpacing")
          root.style.setProperty("--editor-letter-spacing", value);
        if (key === "fontFamily")
          root.style.setProperty("--editor-font-family", value);

        localStorage.setItem(
          "nf_editor_config",
          JSON.stringify(state.editorConfig),
        );
      }

      function loadEditorConfig() {
        const saved = localStorage.getItem("nf_editor_config");
        if (saved) {
          const config = JSON.parse(saved);
          Object.keys(config).forEach((k) => updateEditorConfig(k, config[k]));
        }
      }
