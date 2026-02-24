      document.addEventListener("DOMContentLoaded", () => {
        loadTokens();
        loadLayoutStyle();
        el("save-tokens").addEventListener("click", () => {
          try {
            saveTokens();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("load-config").addEventListener("click", loadConfig);
        el("config-refresh").addEventListener("click", loadConfig);
        el("status-refresh").addEventListener("click", () => {
          refreshStatus().catch((err) => setStatus(err.message));
        });
        el("projects-refresh").addEventListener("click", refreshProjects);
        el("project-create").addEventListener("click", () => {
          createProject().catch((err) => setStatus(err.message));
        });
        el("project-settings-insert").addEventListener("click", () => {
          try {
            insertProjectSettingsTemplate();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("project-select").addEventListener("change", (evt) => {
          state.activeProjectId = evt.target.value;
          el("job-project").value = state.activeProjectId;
          el("policy-project-id").value = state.activeProjectId;
          el("active-project").textContent = state.activeProjectId || "없음";
          setStatus("활성 프로젝트: " + state.activeProjectId);
        });
        el("docs-refresh").addEventListener("click", () => {
          refreshDocs().catch((err) => setStatus(err.message));
        });
        el("doc-create").addEventListener("click", () => {
          createDoc().catch((err) => setStatus(err.message));
        });
        el("doc-template-insert").addEventListener("click", () => {
          try {
            insertDocTemplate();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("tags-refresh").addEventListener("click", () => {
          refreshTags().catch((err) => setStatus(err.message));
        });
        el("tag-create").addEventListener("click", () => {
          createTag().catch((err) => setStatus(err.message));
        });
        el("tag-constraints-insert").addEventListener("click", () => {
          try {
            insertTagConstraintsTemplate();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("policy-load").addEventListener("click", () => {
          loadPolicySettings().catch((err) => setStatus(err.message));
        });
        el("policy-apply").addEventListener("click", () => {
          applyPolicySettings().catch((err) => setStatus(err.message));
        });
        el("job-submit").addEventListener("click", () => {
          submitJob().catch((err) => setStatus(err.message));
        });
        el("job-poll").addEventListener("click", () => {
          pollJob().catch((err) => setStatus(err.message));
        });
        el("job-cancel").addEventListener("click", () => {
          cancelJob().catch((err) => setStatus(err.message));
        });
        el("job-template-insert").addEventListener("click", () => {
          try {
            insertJobTemplate();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("job-template-clear").addEventListener("click", clearJobJSON);
        el("sse-connect").addEventListener("click", () => {
          try {
            connectSSE();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("sse-reconnect").addEventListener("click", () => {
          try {
            reconnectSSE();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("sse-disconnect").addEventListener("click", disconnectSSE);
        el("sse-copy").addEventListener("click", () => {
          if (!state.lastPayload) {
            setStatus("복사할 페이로드가 없습니다.");
            return;
          }
          const text = JSON.stringify(state.lastPayload, null, 2);
          navigator.clipboard.writeText(text).then(
            () => setStatus("페이로드를 복사했습니다."),
            () => setStatus("복사에 실패했습니다.")
          );
        });
        el("retrieval-run").addEventListener("click", () => {
          runRetrieval().catch((err) => setStatus(err.message));
        });
        el("retrieval-filters-insert").addEventListener("click", () => {
          try {
            insertRetrievalFiltersTemplate();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("retrieval-vector").addEventListener("click", () => {
          runVectorRetrieval().catch((err) => setStatus(err.message));
        });
        el("retrieval-vector-stop").addEventListener("click", stopVectorStream);
        el("grouping-time").addEventListener("click", () => {
          submitGrouping("time").catch((err) => setStatus(err.message));
        });
        el("grouping-entity").addEventListener("click", () => {
          submitGrouping("entity").catch((err) => setStatus(err.message));
        });
        el("grouping-both").addEventListener("click", () => {
          submitGrouping("both").catch((err) => setStatus(err.message));
        });
        el("consistency-submit").addEventListener("click", () => {
          submitConsistency().catch((err) => setStatus(err.message));
        });
        el("consistency-verdicts").addEventListener("click", () => {
          loadVerdicts().catch((err) => setStatus(err.message));
        });
        el("whitelist-add").addEventListener("click", () => {
          addWhitelist().catch((err) => setStatus(err.message));
        });
        el("facts-load").addEventListener("click", () => {
          loadFacts().catch((err) => setStatus(err.message));
        });
        el("mentions-load").addEventListener("click", () => {
          loadMentions().catch((err) => setStatus(err.message));
        });
        el("anchors-load").addEventListener("click", () => {
          loadAnchors().catch((err) => setStatus(err.message));
        });
        el("timeline-load").addEventListener("click", () => {
          loadTimelineEvents().catch((err) => setStatus(err.message));
        });
        el("suggest-submit").addEventListener("click", () => {
          submitSuggest().catch((err) => setStatus(err.message));
        });
        el("suggest-claim-insert").addEventListener("click", () => {
          try {
            insertSuggestClaimTemplate();
          } catch (err) {
            setStatus(err.message);
          }
        });
        el("layout-letter").addEventListener("input", onLayoutStyleChanged);
        el("layout-line").addEventListener("input", onLayoutStyleChanged);
        el("layout-font-size").addEventListener("input", onLayoutStyleChanged);
        el("layout-padding-x").addEventListener("input", onLayoutStyleChanged);
        el("layout-bg").addEventListener("input", onLayoutStyleChanged);
        el("layout-font-preset").addEventListener("change", onLayoutStyleChanged);
        el("layout-font-custom").addEventListener("input", onLayoutStyleChanged);
        el("layout-style-reset").addEventListener("click", resetLayoutStyle);
        el("layout-text").addEventListener("input", renderPreview);
        el("proofread-submit").addEventListener("click", () => {
          submitProofread().catch((err) => setStatus(err.message));
        });
        el("export-submit").addEventListener("click", () => {
          submitExport().catch((err) => setStatus(err.message));
        });
        el("preset-ingest").addEventListener("click", () => {
          runPresetIngest().catch((err) => setStatus(err.message));
        });
        el("preset-retrieval").addEventListener("click", () => {
          runPresetRetrieval().catch((err) => setStatus(err.message));
        });
        el("log-copy-curl").addEventListener("click", () => {
          if (!state.lastRequest) {
            setStatus("기록된 요청이 없습니다.");
            return;
          }
          const curl = buildCurl(state.lastRequest);
          navigator.clipboard.writeText(curl).then(
            () => setStatus("cURL을 복사했습니다."),
            () => setStatus("복사에 실패했습니다.")
          );
        });
        el("log-download").addEventListener("click", downloadLog);
        el("log-clear").addEventListener("click", () => {
          state.requestLog = [];
          state.lastRequest = null;
          renderRequestLog();
          setStatus("요청 로그를 비웠습니다.");
        });
        el("toggles-apply").addEventListener("click", () => {
          applyToggles().catch((err) => setStatus(err.message));
        });
        el("toggles-refresh").addEventListener("click", () => {
          refreshToggles().catch((err) => setStatus(err.message));
        });
        el("fixture-run").addEventListener("click", () => {
          runFixtures().catch((err) => setStatus(err.message));
        });
        el("reset-run").addEventListener("click", () => {
          runReset().catch((err) => setStatus(err.message));
        });
        renderPreview();
      });
