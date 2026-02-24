      // --- Project Management ---
      async function init() {
        loadEditorConfig();
        try {
          const data = await api("/projects");
          const select = document.getElementById("project-select");
          const showOkToggle = document.getElementById("toggle-show-ok");
          if (showOkToggle) {
            showOkToggle.checked = Boolean(state.showOkVerdicts);
            showOkToggle.addEventListener("change", () => {
              state.showOkVerdicts = Boolean(showOkToggle.checked);
              renderVerdicts(state.lastVerdicts || []);
            });
          }
          const entityFilterInput = document.getElementById(
            "consistency-filter-entity",
          );
          if (entityFilterInput && typeof entityFilterInput.value === "string")
            entityFilterInput.value =
              state.consistencyOptions.filters.entity_id || "";
          const timeFilterInput = document.getElementById(
            "consistency-filter-time",
          );
          if (timeFilterInput && typeof timeFilterInput.value === "string")
            timeFilterInput.value =
              state.consistencyOptions.filters.time_key || "";
          const timelineFilterInput = document.getElementById(
            "consistency-filter-timeline",
          );
          if (
            timelineFilterInput &&
            typeof timelineFilterInput.value === "string"
          ) {
            timelineFilterInput.value =
              state.consistencyOptions.filters.timeline_idx || "";
          }
          const graphModeInput = document.getElementById(
            "consistency-graph-mode",
          );
          if (graphModeInput)
            graphModeInput.value = _normalizeGraphMode(
              state.consistencyOptions.graph_mode || "off",
            );
          const layer3Input = document.getElementById(
            "consistency-layer3-promotion",
          );
          if (layer3Input)
            layer3Input.checked = Boolean(
              state.consistencyOptions.layer3_promotion,
            );
          const verifierInput = document.getElementById(
            "consistency-verifier-mode",
          );
          if (verifierInput)
            verifierInput.value = _normalizeVerifierMode(
              state.consistencyOptions.verifier_mode || "off",
            );
          const triageInput = document.getElementById(
            "consistency-triage-mode",
          );
          if (triageInput)
            triageInput.value = _normalizeTriageMode(
              state.consistencyOptions.triage_mode || "off",
            );
          const loopInput = document.getElementById("consistency-loop-enabled");
          if (loopInput)
            loopInput.checked = Boolean(
              state.consistencyOptions.verification_loop,
            );

          if (data.projects && Object.keys(data.projects).length > 0) {
            select.innerHTML = '<option value="">선택하세요</option>';
            Object.values(data.projects).forEach((p) => {
              const opt = document.createElement("option");
              opt.value = p.project_id;
              opt.textContent = p.name;
              select.appendChild(opt);
            });
          } else {
            select.innerHTML = '<option value="">프로젝트가 없습니다</option>';
          }
        } catch (e) {
          console.error("Init Error", e);
        }
      }

      async function handleCreateProject() {
        const name = document.getElementById("new-project-name").value;
        if (!name) return alert("이름을 입력해주세요");

        showLoading("프로젝트 생성 중...");
        try {
          const res = await api("/projects", "POST", {
            name,
            settings: { mode: "dev" },
          });
          hideLoading();
          loadProject(res.project.project_id, res.project.name);
          document.getElementById("setup-modal").classList.remove("active");
        } catch (e) {
          hideLoading();
          console.error("Create Project Error", e);
          alert("생성 실패: " + e.message);
        }
      }

      async function handleLoadProject() {
        const pid = document.getElementById("project-select").value;
        if (!pid) return alert("선택해주세요");
        const name = document.querySelector(
          `#project-select option[value="${pid}"]`,
        ).textContent;
        loadProject(pid, name);
        document.getElementById("setup-modal").classList.remove("active");
      }

      function loadProject(pid, name) {
        state.projectId = pid;
        state.projectName = name;
        document.getElementById("current-project-label").textContent = name;
        localStorage.setItem("last_project_id", pid);
        localStorage.setItem("last_project_name", name);
        refreshDocList();
      }

      function exitProject() {
        localStorage.removeItem("last_project_id");
        localStorage.removeItem("last_project_name");
        location.reload();
      }

      // --- Doc Management ---
      async function refreshDocList() {
        const list = document.getElementById("doc-list");
        list.innerHTML =
          '<div style="text-align:center; padding:20px; color:#aaa;">로딩 중...</div>';

        try {
          const res = await api(`/projects/${state.projectId}/documents`);
          // Ensure state.docs is a Map (ID -> Doc)
          const docsMap = {};
          const list = Array.isArray(res.documents)
            ? res.documents
            : typeof res.documents === "object"
              ? Object.values(res.documents)
              : [];

          list.forEach((d) => {
            if (d && d.doc_id) docsMap[d.doc_id] = d;
          });
          state.docs = docsMap;
          renderDocList();
        } catch (e) {
          list.innerHTML =
            '<div style="text-align:center; color:red;">로드 실패</div>';
        }
      }

      function switchNavTab(type) {
        state.currentNavTab = type;

        // Update tab styling
        document
          .querySelectorAll(".tab-btn")
          .forEach((b) => b.classList.remove("active"));
        event.target.classList.add("active");

        if (type === "TIMELINE") {
          renderTimeline();
        } else {
          renderDocList();
        }
      }

      async function renderTimeline() {
        // Structure View (Git-like Vertical Graph)
        // Uses state.docs to render chapters and episodes in linear order
        const list = document.getElementById("doc-list");
        list.innerHTML = "";

        const docs = Object.values(state.docs).filter(
          (d) => d.type === "EPISODE",
        );

        // Group by 'metadata.group'
        const groups = {};
        const noGroup = [];

        docs.forEach((d) => {
          const gName = (d.metadata && d.metadata.group) || "";
          if (!gName || gName === "미분류") {
            noGroup.push(d);
          } else {
            if (!groups[gName]) groups[gName] = [];
            groups[gName].push(d);
          }
        });

        // Sort Groups (by order of first doc? or just alphanumeric?)
        // We need a stable order. Let's sort keys for now.
        // Ideally we should have a 'Chapter' entity with order.
        // For now, heuristic: use the order of the first document in the group to sort groups.
        const sortedGroupNames = Object.keys(groups).sort((a, b) => {
          const docA = groups[a][0];
          const docB = groups[b][0];
          return (docA.metadata?.order || 0) - (docB.metadata?.order || 0);
        });

        let html = '<div class="structure-graph" style="padding: 20px 10px;">';

        // Render Groups
        sortedGroupNames.forEach((gName, gIdx) => {
          const gDocs = groups[gName].sort(
            (a, b) => (a.metadata?.order || 0) - (b.metadata?.order || 0),
          );

          // Group Node (Big Circle)
          html += `
            <div class="struct-node group-node" draggable="true" ondragstart="handleDragStart(event, null, '${gName}')" 
                 oncontextmenu="openGroupCtxMenu(event, '${gName}')">
                <div class="node-circle big"></div>
                <div class="node-label"><strong>${gName}</strong></div>
            </div>
            <div class="struct-line"></div>
          `;

          // Episodes
          gDocs.forEach((doc, dIdx) => {
            const actsAsLast =
              dIdx === gDocs.length - 1 &&
              gIdx === sortedGroupNames.length - 1 &&
              noGroup.length === 0;

            html += `
                <div class="struct-node doc-node" onclick="loadDoc('${doc.doc_id}')" draggable="true" 
                     ondragstart="handleDragStart(event, '${doc.doc_id}')" ondrop="handleDropOnItem(event, '${doc.doc_id}', '${gName}')" ondragover="handleDragOver(event)">
                    <div class="node-circle small ${state.currentDocId === doc.doc_id ? "active" : ""}"></div>
                    <div class="node-label">${doc.title}</div>
                </div>
                ${!actsAsLast ? '<div class="struct-line"></div>' : ""}
              `;
          });
        });

        // Unclassified
        if (noGroup.length > 0) {
          noGroup.sort(
            (a, b) => (a.metadata?.order || 0) - (b.metadata?.order || 0),
          );
          html += `
            <div class="struct-node group-node">
                <div class="node-circle big"></div>
                <div class="node-label" style="opacity:0.7">미분류</div>
            </div>
            <div class="struct-line"></div>
          `;
          noGroup.forEach((doc, dIdx) => {
            const isLast = dIdx === noGroup.length - 1;
            html += `
                <div class="struct-node doc-node" onclick="loadDoc('${doc.doc_id}')" draggable="true"
                     ondragstart="handleDragStart(event, '${doc.doc_id}')" ondrop="handleDropOnItem(event, '${doc.doc_id}', '')" ondragover="handleDragOver(event)">
                    <div class="node-circle small ${state.currentDocId === doc.doc_id ? "active" : ""}"></div>
                    <div class="node-label">${doc.title}</div>
                </div>
                ${!isLast ? '<div class="struct-line"></div>' : ""}
              `;
          });
        }

        html += "</div>";

        // Inject CSS for graph if not exists
        if (!document.getElementById("graph-css")) {
          const style = document.createElement("style");
          style.id = "graph-css";
          style.innerHTML = `
            .structure-graph { position: relative; }
            .struct-node { display: flex; align-items: center; position: relative; z-index: 2; padding: 5px 0; cursor: pointer; }
            .struct-node:hover .node-label { color: var(--primary-color); }
            .node-circle { border: 2px solid #555; background: white; border-radius: 50%; z-index: 2; }
            .node-circle.big { width: 16px; height: 16px; border-width: 3px; margin-left: 2px; }
            .node-circle.small { width: 10px; height: 10px; margin-left: 5px; background: #eee; }
            .node-circle.small.active { background: var(--primary-color); border-color: var(--primary-color); }
            .node-label { margin-left: 15px; font-size: 0.9rem; }
            .struct-line { width: 2px; background: #ddd; margin-left: 9px; height: 20px; z-index: 1; }
          `;
          document.head.appendChild(style);
        }

        list.innerHTML = html;
      }

      function renderDocList() {
        // Logic split: If EPISODE tab, use Tree View. Others, use List View.
        if (state.currentNavTab === "EPISODE") {
          renderDocTree();
        } else {
          renderFlatList();
        }
      }

      function renderFlatList() {
        const list = document.getElementById("doc-list");
        list.innerHTML = "";
        const typeFilter = state.currentNavTab;
        const relevantDocs = Object.values(state.docs).filter((d) => {
          if (typeFilter === "SETTING")
            return ["SETTING", "CHAR"].includes(d.type);
          if (typeFilter === "PLOT") return ["PLOT", "NOTE"].includes(d.type);
          return false;
        });

        if (relevantDocs.length === 0) {
          let emptyMessage = "아직 문서가 없습니다.";
          if (typeFilter === "SETTING") {
            emptyMessage =
              "작품의 세계관, 등장인물 설정을 여기에 추가하면 AI가 설정을 기반으로 오류를 잡아냅니다.";
          } else if (typeFilter === "PLOT") {
            emptyMessage =
              "소설의 전체적인 줄거리와 요약을 이곳에 정리해두세요.";
          } else if (typeFilter === "TIMELINE") {
            emptyMessage =
              "작품 내 주요 사건들을 시간순으로 기록하는 타임라인 문서입니다.";
          }

          list.innerHTML = `<div style="text-align:center; padding:20px 15px; color:#94a3b8; font-size:0.9rem; line-height:1.5; background:#f8fafc; border-radius:8px; margin-top:10px;">
          ${emptyMessage}
        </div>`;
          return;
        }

        relevantDocs.forEach((doc) => {
          const item = document.createElement("div");
          item.className =
            "list-item" + (state.currentDocId === doc.doc_id ? " active" : "");
          item.onclick = () => loadDoc(doc.doc_id);
          item.innerHTML = `
          < div >
                   <div style="font-weight:600;">${doc.title}</div>
                   <div class="meta">${new Date(doc.updated_at).toLocaleString()}</div>
                </div >
          <div style="font-size:0.8rem; background:#eee; padding:2px 6px; border-radius:4px;">${doc.type}</div>
        `;
          list.appendChild(item);
        });
      }

      // --- Tree View Implementation ---
      function renderDocTree() {
        const list = document.getElementById("doc-list");
        list.innerHTML = "";

        const docs = Object.values(state.docs).filter(
          (d) => d.type === "EPISODE",
        );
        if (docs.length === 0) {
          list.innerHTML =
            '<div style="text-align:center; padding:20px; color:#ccc;">에피소드가 없습니다.</div>';
          return;
        }

        // Grouping
        const groups = {
          미분류: [],
        };
        docs.forEach((d) => {
          const gName =
            d.metadata && d.metadata.group ? d.metadata.group : "미분류";
          if (!groups[gName]) groups[gName] = [];
          groups[gName].push(d);
        });

        // Sorting: Groups then items within groups
        const sortedGroupNames = Object.keys(groups).sort((a, b) => {
          if (a === "미분류") return 1;
          if (b === "미분류") return -1;
          return a.localeCompare(b);
        });

        sortedGroupNames.forEach((gName) => {
          const groupDocs = groups[gName];
          // Sort docs by metadata.order -> metadata.episode_no -> created_at
          groupDocs.sort((a, b) => {
            const ordA = (a.metadata && a.metadata.order) || 9999;
            const ordB = (b.metadata && b.metadata.order) || 9999;
            if (ordA !== ordB) return ordA - ordB;
            return new Date(a.created_at) - new Date(b.created_at);
          });

          const details = document.createElement("details");
          details.open = true; // Default open
          details.style.marginBottom = "10px";

          const summary = document.createElement("summary");
          summary.style.cursor = "pointer";
          summary.style.fontWeight = "bold";
          summary.style.padding = "5px";
          summary.style.color = "#34495e";
          summary.innerText = gName;
          // Context menu for Group
          summary.oncontextmenu = (e) => openGroupCtxMenu(e, gName);

          details.appendChild(summary);

          const folderContent = document.createElement("div");
          folderContent.style.paddingLeft = "15px";

          groupDocs.forEach((doc) => {
            const item = document.createElement("div");
            item.className =
              "list-item" +
              (state.currentDocId === doc.doc_id ? " active" : "");
            item.style.padding = "8px 10px";

            // Drag & Drop Attributes
            item.draggable = true;
            item.ondragstart = (e) => handleDragStart(e, doc.doc_id);
            item.ondragover = (e) => handleDragOver(e);
            item.ondrop = (e) => handleDropOnItem(e, doc.doc_id, gName);

            // Label construction: "N화 제목" 또는 "제목"
            let label = doc.title;
            if (doc.metadata && doc.metadata.episode_no) {
              label = `<span style="color:#e67e22; font-weight:bold; margin-right:5px;">${doc.metadata.episode_no}화</span> ${doc.title}`;
            }

            item.innerHTML = `
          <div style="width:100%; display:flex; justify-content:space-between; align-items:center;">
                  <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; pointer-events:none;">${label}</span>
                  <div class="menu-btn" onclick="openDocCtxMenu(event, '${doc.doc_id}')">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <circle cx="12" cy="12" r="1"></circle>
                      <circle cx="12" cy="5" r="1"></circle>
                      <circle cx="12" cy="19" r="1"></circle>
                    </svg>
                  </div>
              </div >
          `;
            item.onclick = (e) => {
              loadDoc(doc.doc_id); // openDocCtxMenu stops propagation, so this is safe
            };
            folderContent.appendChild(item);
          });

          // Drop zone for Group
          details.ondragover = (e) => handleDragOver(e);
          details.ondrop = (e) => handleDropOnGroup(e, gName);

          details.appendChild(folderContent);
          list.appendChild(details);
        });
      }

      // --- Drag & Drop Handlers ---
      function handleDragStart(e, docId, groupName = null) {
        if (groupName) {
          state.draggedGroup = groupName;
          state.draggedDocId = null;
          e.dataTransfer.effectAllowed = "move";
        } else {
          state.draggedDocId = docId;
          state.draggedGroup = null;
          e.dataTransfer.effectAllowed = "move";
        }
      }

      function handleDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
      }

      async function handleDropOnItem(e, targetDocId, targetGroupName) {
        e.preventDefault();
        e.stopPropagation();

        if (state.draggedGroup) return; // Ignore group drop on item for now

        if (!state.draggedDocId || state.draggedDocId === targetDocId) return;

        const sourceDoc = state.docs[state.draggedDocId];
        const targetDoc = state.docs[targetDocId];

        let targetGroup = targetGroupName;
        if (!targetGroup) {
          targetGroup =
            (targetDoc.metadata && targetDoc.metadata.group) || "미분류";
        }

        // Flexible Sorting: Check Drop Position (Before or After)
        // e.offsetY relative to e.target (the list item)
        // If offsetY > target.offsetHeight / 2 -> After

        // Note: e.target might be a child of the list item. We need the list item's height.
        const rect = e.currentTarget.getBoundingClientRect();
        const offsetY = e.clientY - rect.top;
        const isAfter = offsetY > rect.height / 2;

        // Get Group Docs sorted
        const groupDocs = Object.values(state.docs)
          .filter((d) => {
            const g = (d.metadata && d.metadata.group) || "미분류";
            return g === targetGroup;
          })
          .sort((a, b) => (a.metadata?.order || 0) - (b.metadata?.order || 0));

        const targetIdx = groupDocs.findIndex((d) => d.doc_id === targetDocId);
        let newOrder = 0;
        const targetOrder = groupDocs[targetIdx]?.metadata?.order || 0;

        if (isAfter) {
          // Insert After
          const nextDoc = groupDocs[targetIdx + 1];
          if (nextDoc) {
            newOrder = (targetOrder + (nextDoc.metadata?.order || 0)) / 2;
          } else {
            newOrder = targetOrder + 10;
          }
        } else {
          // Insert Before
          if (targetIdx === 0) {
            newOrder = targetOrder - 10;
          } else {
            const prevDoc = groupDocs[targetIdx - 1];
            newOrder = ((prevDoc.metadata?.order || 0) + targetOrder) / 2;
          }
        }

        // Optimistic Update? Too risky for order?
        // Let's stick to API then refresh for safety in ordering.
        await api(
          `/projects/${state.projectId}/documents/${state.draggedDocId}`,
          "PATCH",
          {
            metadata: {
              ...sourceDoc.metadata,
              group: targetGroup,
              order: newOrder,
            },
          },
        );

        state.draggedDocId = null;
        refreshDocList();
      }

      async function handleDropOnGroup(e, targetGroupName) {
        e.preventDefault();
        e.stopPropagation();

        if (state.draggedGroup) {
          // Reordering Groups?
          // If dragging Group A onto Group B...
          // Not implemented yet.
          return;
        }

        if (!state.draggedDocId) return;

        const sourceDoc = state.docs[state.draggedDocId];
        // Move to this group, append to end (order = max + 10)

        const groupDocs = Object.values(state.docs).filter((d) => {
          const g = (d.metadata && d.metadata.group) || "미분류";
          return g === targetGroupName;
        });

        const maxOrder = groupDocs.reduce(
          (max, d) => Math.max(max, d.metadata?.order || 0),
          0,
        );
        const newOrder = maxOrder + 10;

        await api(
          `/projects/${state.projectId}/documents/${state.draggedDocId}`,
          "PATCH",
          {
            metadata: {
              ...sourceDoc.metadata,
              group: targetGroupName,
              order: newOrder,
            },
          },
        );

        state.draggedDocId = null;
        refreshDocList();
      }

      // --- Context Menu UI ---
      function getCtxMenuEl() {
        let el = document.getElementById("ctx-menu");
        if (!el) {
          el = document.createElement("div");
          el.id = "ctx-menu";
          el.style.position = "fixed";
          el.style.background = "white";
          el.style.border = "1px solid #ddd";
          el.style.boxShadow = "0 2px 10px rgba(0,0,0,0.1)";
          el.style.zIndex = "1000";
          el.style.display = "none";
          el.style.borderRadius = "4px";
          el.style.overflow = "hidden";
          el.style.minWidth = "150px";
          document.body.appendChild(el);

          // Close on outside click is handled by global click listener usually, but simple way here:
          document.addEventListener(
            "click",
            (e) => {
              if (!el.contains(e.target)) el.style.display = "none";
            },
            { capture: true },
          );
        }
        return el;
      }

      function showCtxMenu(x, y, options) {
        const menu = getCtxMenuEl();
        menu.innerHTML = "";
        menu.style.left = x + "px";
        menu.style.top = y + "px";
        menu.style.display = "block";

        options.forEach((opt) => {
          const item = document.createElement("div");
          item.innerText = opt.label;
          item.style.padding = "10px 15px";
          item.style.cursor = "pointer";
          item.style.fontSize = "0.9rem";
          item.style.color = opt.color || "#333";
          item.onmouseover = () => (item.style.background = "#f5f5f5");
          item.onmouseout = () => (item.style.background = "white");
          item.onclick = (e) => {
            e.stopPropagation(); // prevent document click closing immediately if needed?
            menu.style.display = "none";
            opt.action();
          };
          menu.appendChild(item);
        });
      }

      // Updated Context Menu Logic
      function openDocCtxMenu(e, docId) {
        e.stopPropagation();
        e.preventDefault();

        const options = [
          { label: "이름 변경", action: () => promptRenameDoc(docId) },
          { label: "챕터 이동", action: () => promptMoveGroup(docId) },
          { label: "회차 번호 설정", action: () => promptEpisodeNo(docId) },
          {
            label: "삭제",
            action: () => confirmDeleteDoc(docId),
            color: "#e74c3c",
          },
        ];

        showCtxMenu(e.clientX, e.clientY, options);
      }

      function promptRenameDoc(docId) {
        const doc = state.docs[docId];
        const newTitle = prompt("새 제목을 입력하세요:", doc.title);
        if (newTitle && newTitle !== doc.title) {
          // Optimistic Update
          state.docs[docId].title = newTitle;
          if (state.currentNavTab === "TIMELINE") renderTimeline();
          else renderDocList();

          // If current doc, update input
          if (state.currentDocId === docId) {
            document.getElementById("doc-title-input").value = newTitle;
          }

          api(`/projects/${state.projectId}/documents/${docId}`, "PATCH", {
            title: newTitle,
          }).catch((e) => {
            alert("이름 변경에 실패했습니다.");
            console.error(e);
            // Rollback? Simplified for now.
          });
        }
      }

      function promptMoveGroup(docId) {
        const doc = state.docs[docId];
        const currentGroup = (doc.metadata && doc.metadata.group) || "";
        const newGroup = prompt(
          "이동할 챕터 이름을 입력하세요 (비워 두면 '미분류'):",
          currentGroup,
        );
        if (newGroup !== null) {
          const meta = doc.metadata || {};
          meta.group = newGroup;
          api(`/projects/${state.projectId}/documents/${docId}`, "PATCH", {
            metadata: meta,
          }).then(() => {
            state.docs[docId].metadata = meta; // local update
            refreshDocList();
          });
        }
      }

      function promptEpisodeNo(docId) {
        const doc = state.docs[docId];
        const currentNo = (doc.metadata && doc.metadata.episode_no) || "";
        const num = prompt("회차 번호를 입력하세요 (숫자만):", currentNo);
        if (num !== null) {
          const intNum = parseInt(num, 10);
          if (isNaN(intNum)) return alert("유효한 숫자를 입력해주세요.");

          const meta = doc.metadata || {};
          meta.episode_no = intNum;
          api(`/projects/${state.projectId}/documents/${docId}`, "PATCH", {
            metadata: meta,
          }).then(() => {
            state.docs[docId].metadata = meta;
            refreshDocList();
          });
        }
      }

      function confirmDeleteDoc(docId) {
        if (confirm("정말 이 문서를 삭제하시겠습니까?")) {
          api(`/projects/${state.projectId}/documents/${docId}`, "DELETE").then(
            () => {
              delete state.docs[docId];
              if (state.currentDocId === docId) {
                state.currentDocId = null;
                document.getElementById("editor").innerText = "";
                document.getElementById("doc-title-input").value = "";
              }
              refreshDocList();
            },
          );
        }
      }
      function openGroupCtxMenu(e, groupName) {
        e.stopPropagation();
        e.preventDefault();

        const options = [
          {
            label: "챕터 이름 변경",
            action: () => promptRenameGroup(groupName),
          },
        ];

        showCtxMenu(e.clientX, e.clientY, options);
      }

      async function promptRenameGroup(oldName) {
        const newName = prompt("새 챕터 이름을 입력하세요:", oldName);
        if (newName && newName !== oldName) {
          showLoading("챕터 이름 변경 중...");

          const groupDocs = Object.values(state.docs).filter((d) => {
            const g =
              d.metadata && d.metadata.group ? d.metadata.group : "미분류";
            return g === oldName;
          });

          const updates = groupDocs.map((d) => ({
            doc_id: d.doc_id,
            group: newName,
            order: d.metadata?.order,
            episode_no: d.metadata?.episode_no,
          }));

          try {
            await api(
              `/projects/${state.projectId}/documents/reorder`,
              "POST",
              { updates },
            );
            updates.forEach((u) => {
              if (state.docs[u.doc_id].metadata) {
                state.docs[u.doc_id].metadata.group = newName;
              }
            });
            refreshDocList();
          } catch (err) {
            alert("챕터 이름 변경에 실패했습니다.");
            console.error(err);
          } finally {
            hideLoading();
          }
        }
      }

      async function createNewDoc() {
        const title = "제목 없음";

        // Type based on current tab
        let type = state.currentNavTab;
        if (type === "TIMELINE") {
          type = "EPISODE";
        }
        if (!["EPISODE", "SETTING", "CHAR", "PLOT", "NOTE"].includes(type)) {
          type = "EPISODE";
        }

        showLoading("문서 생성 중...");
        try {
          const res = await api(
            `/projects/${state.projectId}/documents`,
            "POST",
            {
              title,
              type,
              content: "",
            },
          );
          hideLoading();
          await refreshDocList();
          loadDoc(res.document.doc_id);
        } catch (e) {
          hideLoading();
          alert("문서 생성에 실패했습니다.");
        }
      }

      async function loadDoc(did) {
        // Safe Context Switch
        if (state.currentDocId && state.isDirty) {
          await saveDoc(true); // Wait for save to complete
        }

        state.currentDocId = did;
        const doc = state.docs[did];

        // UI Feedback
        document.getElementById("empty-state").style.display = "none";
        if (
          document
            .getElementById("loading-overlay")
            .classList.contains("active") === false
        ) {
          // Only show local loading if not blocked by something else
          // showLoading("문서 로딩 중..."); // Might be too intrusive?
          // Let's just use the editor placeholder or opacity?
          document.getElementById("editor").style.opacity = "0.5";
        }

        try {
          const res = await api(
            `/projects/${state.projectId}/documents/${did}`,
          );
          const fullDoc = res.document;

          document.getElementById("doc-title-input").value =
            fullDoc.title || "";
          const loadedContent = fullDoc.content || "";
          document.getElementById("editor").innerText = loadedContent;
          document.getElementById("editor").style.opacity = "1";

          // Reset dirty state after load
          state.isDirty = false;
          state.pendingConsistencySegments = [];
          state.lastSegmentFingerprints =
            _segmentTextForConsistency(loadedContent);
          state.lastVerdicts = [];
          clearInlineVerdictHighlights();
          document.getElementById("save-status").innerText = "저장됨";
          document.getElementById("save-status").style.color = "#aaa";

          document.getElementById("doc-type-badge").innerText =
            fullDoc.type || "UNKNOWN";

          state.currentDocType = fullDoc.type;

          renderDocList();
          // hideLoading();
        } catch (e) {
          console.error("Load Doc Error", e);
          document.getElementById("editor").innerText = "로드 실패";
          document.getElementById("editor").style.opacity = "1";
        }
      }

      // --- Export ---
      function openExportModal() {
        document.getElementById("export-modal").classList.add("active");
      }
      function closeExportModal() {
        document.getElementById("export-modal").classList.remove("active");
      }
      async function handleExport() {
        if (!state.currentDocId) return alert("문서를 열어주세요");
        const format = document.querySelector(
          'input[name="export-fmt"]:checked',
        ).value;

        showLoading("파일 준비 중...");
        try {
          const res = await api("/jobs", "POST", {
            type: "EXPORT",
            project_id: state.projectId,
            inputs: {
              range: { doc_id: state.currentDocId }, // Export current doc only
              format: format,
            },
          });

          const jobId = res?.job?.job_id;
          if (!jobId) throw new Error("export job id missing");
          await waitForJob(jobId);

          const downloadPath = `/jobs/${encodeURIComponent(jobId)}/artifact`;
          const link = document.createElement("a");
          link.href = downloadPath;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);

          hideLoading();
          closeExportModal();
        } catch (e) {
          hideLoading();
          console.error(e);
          alert("내보내기 실패: " + e.message);
        }
      }

      async function createNewChapter() {
        const chapterName = prompt("새 챕터(그룹) 이름을 입력하세요");
        if (!chapterName) return;

        showLoading("챕터 생성 중...");
        try {
          // Create a placeholder doc for this chapter
          const res = await api(
            `/projects/${state.projectId}/documents`,
            "POST",
            {
              title: `${chapterName} - 서막`,
              type: "EPISODE",
              content: "",
              metadata: { group: chapterName, order: 0, episode_no: 1 },
            },
          );
          hideLoading();
          await refreshDocList();
          loadDoc(res.document.doc_id);
        } catch (e) {
          hideLoading();
          alert("챕터 생성에 실패했습니다.");
          console.error(e);
        }
      }

      async function exitProject() {
        if (state.currentDocId && state.isDirty) {
          await saveDoc(true);
        }

        // Reset State
        state.projectId = null;
        state.projectName = "";
        state.currentDocId = null;
        state.docs = {};

        // Clear UI
        document.getElementById("doc-list").innerHTML = "";
        document.getElementById("editor").innerText = "";
        document.getElementById("doc-title-input").value = "";
        document.getElementById("current-project-label").innerText = "-";
        document.getElementById("empty-state").style.display = "flex"; // Reset Placeholder

        // Show Modal
        document.getElementById("setup-modal").classList.add("active");

        // Clear LocalStorage Navigation
        localStorage.removeItem("last_project_id");
        localStorage.removeItem("last_project_name");
      }
