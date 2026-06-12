(function () {
  "use strict";

  const TYPE_META = {
    Work: { label: "작품", color: "#0f766e", radius: 18 },
    TextUnit: { label: "문서", color: "#64748b", radius: 12 },
    Character: { label: "인물", color: "#2563eb", radius: 13 },
    Place: { label: "장소", color: "#16a34a", radius: 12 },
    Event: { label: "사건", color: "#dc2626", radius: 13 },
    TimeCue: { label: "시간", color: "#ca8a04", radius: 11 },
    Fact: { label: "설정", color: "#7c3aed", radius: 11 },
    Evidence: { label: "근거", color: "#0891b2", radius: 10 },
    NarrativeCue: { label: "구상", color: "#db2777", radius: 12 },
    ContradictionCandidate: { label: "점검", color: "#ea580c", radius: 13 },
  };

  const DIMENSION_META = {
    story: { label: "이야기 흐름", color: "#2563eb", x: 0.28, y: 0.36 },
    setting: { label: "세계관 설정", color: "#7c3aed", x: 0.72, y: 0.34 },
    time: { label: "시간 순서", color: "#ca8a04", x: 0.5, y: 0.74 },
    entity: { label: "인물/장소", color: "#16a34a", x: 0.22, y: 0.68 },
    source: { label: "원문 근거", color: "#0891b2", x: 0.78, y: 0.7 },
    review: { label: "점검 필요", color: "#ea580c", x: 0.5, y: 0.23 },
  };

  const graphState = {
    open: false,
    stale: true,
    mode: "2d",
    clusterEnabled: false,
    clusterDistance: 128,
    showLabels: true,
    activeTypes: new Set(Object.keys(TYPE_META)),
    activeDimensions: new Set(["story", "setting", "time", "entity", "source"]),
    searchText: "",
    nodes: [],
    edges: [],
    nodeById: new Map(),
    selectedNodeId: null,
    hoverNodeId: null,
    panX: 0,
    panY: 0,
    zoom: 1,
    rotation: 0,
    fetchToken: 0,
    animationFrame: null,
    pointer: {
      dragging: false,
      moved: false,
      lastX: 0,
      lastY: 0,
    },
  };

  let canvas = null;
  let ctx = null;
  let canvasWidth = 0;
  let canvasHeight = 0;

  function $(id) {
    return document.getElementById(id);
  }

  function getAppState() {
    return window.state || {};
  }

  function safeText(value, fallback = "") {
    if (value === null || value === undefined) return fallback;
    const text = String(value).trim();
    return text || fallback;
  }

  function escapeHTML(value) {
    return safeText(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function shortText(value, max = 80) {
    const text = safeText(value);
    if (text.length <= max) return text;
    return `${text.slice(0, Math.max(0, max - 1))}...`;
  }

  function valueLabel(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return String(value);
    }
  }

  function hashText(value) {
    const text = safeText(value);
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function docTypeLabel(type) {
    const value = safeText(type).toUpperCase();
    if (value === "EPISODE") return "본문";
    if (value === "SETTING" || value === "CHAR") return "설정";
    if (value === "PLOT") return "구상";
    if (value === "NOTE") return "메모";
    return value || "문서";
  }

  function inferDocType(doc) {
    const type = safeText(doc?.type).toUpperCase();
    if (type === "SETTING" || type === "CHAR") return "Fact";
    if (type === "PLOT") return "NarrativeCue";
    return "TextUnit";
  }

  function inferDocDimensions(doc) {
    const type = safeText(doc?.type).toUpperCase();
    const meta = doc?.metadata || {};
    const dims = new Set(["source"]);
    if (type === "SETTING" || type === "CHAR") dims.add("setting");
    else dims.add("story");
    if (type === "PLOT") dims.add("story");
    if (meta.time_key || Number.isFinite(Number(meta.timeline_idx))) dims.add("time");
    if (meta.needs_review || meta.consistency_warning) dims.add("review");
    return Array.from(dims);
  }

  function entityType(kind) {
    const value = safeText(kind).toUpperCase();
    if (value === "CHAR") return "Character";
    if (value === "LOC") return "Place";
    if (value === "EVENT") return "Event";
    return "Fact";
  }

  function entityKindLabel(kind) {
    const value = safeText(kind).toUpperCase();
    if (value === "CHAR") return "인물";
    if (value === "LOC") return "장소";
    if (value === "ORG") return "조직";
    if (value === "OBJ") return "물건";
    if (value === "EVENT") return "사건";
    return "설정";
  }

  function entityDimensions(kind) {
    const value = safeText(kind).toUpperCase();
    if (value === "EVENT") return ["story", "entity"];
    if (value === "LOC" || value === "CHAR" || value === "ORG" || value === "OBJ") {
      return ["setting", "entity"];
    }
    return ["setting"];
  }

  function timelineValue(doc) {
    const meta = doc?.metadata || {};
    const candidates = [meta.timeline_idx, meta.order, meta.episode_no];
    for (const candidate of candidates) {
      const parsed = Number(candidate);
      if (Number.isFinite(parsed)) return parsed;
    }
    return Number.MAX_SAFE_INTEGER;
  }

  function groupLabel(doc) {
    return safeText(doc?.metadata?.group, "");
  }

  function sortedDocs() {
    const docs = Object.values(getAppState().docs || {}).filter(Boolean);
    return docs.sort((a, b) => {
      const groupA = groupLabel(a);
      const groupB = groupLabel(b);
      if (groupA !== groupB) return groupA.localeCompare(groupB, "ko");
      const timelineA = timelineValue(a);
      const timelineB = timelineValue(b);
      if (timelineA !== timelineB) return timelineA - timelineB;
      return safeText(a.title).localeCompare(safeText(b.title), "ko");
    });
  }

  function nodeTitleForDoc(doc) {
    return safeText(doc?.title, "제목 없는 문서");
  }

  function addNode(map, node) {
    if (!node || !node.id) return null;
    const existing = map.get(node.id);
    if (existing) {
      existing.weight += node.weight || 1;
      existing.dimensions = Array.from(new Set([...(existing.dimensions || []), ...(node.dimensions || [])]));
      if (!existing.docId && node.docId) existing.docId = node.docId;
      if (!existing.description && node.description) existing.description = node.description;
      return existing;
    }
    const meta = TYPE_META[node.type] || TYPE_META.TextUnit;
    const created = {
      id: node.id,
      label: safeText(node.label, "이름 없음"),
      type: node.type || "TextUnit",
      dimensions: Array.isArray(node.dimensions) && node.dimensions.length ? node.dimensions : ["story"],
      subtitle: safeText(node.subtitle),
      description: safeText(node.description),
      sourceKind: safeText(node.sourceKind, "문서"),
      docId: node.docId || null,
      docType: node.docType || null,
      routeLabel: safeText(node.routeLabel, node.docId ? "원문으로 이동" : "목록에서 보기"),
      data: node.data || {},
      weight: node.weight || 1,
      radius: node.radius || meta.radius,
      color: node.color || meta.color,
      x: 0,
      y: 0,
      z: 0,
      tx: 0,
      ty: 0,
      tz: 0,
      screenX: 0,
      screenY: 0,
      screenRadius: meta.radius,
      alpha: 1,
    };
    map.set(created.id, created);
    return created;
  }

  function addEdge(edgeMap, edge) {
    if (!edge || !edge.source || !edge.target || edge.source === edge.target) return;
    const type = edge.type || "RELATED";
    const key = `${edge.source}|${edge.target}|${type}`;
    const existing = edgeMap.get(key);
    if (existing) {
      existing.weight += edge.weight || 1;
      return;
    }
    edgeMap.set(key, {
      source: edge.source,
      target: edge.target,
      type,
      label: safeText(edge.label, "연결"),
      weight: edge.weight || 1,
      color: edge.color || "#94a3b8",
      dashed: Boolean(edge.dashed),
    });
  }

  function buildGraphData(kgContext) {
    const appState = getAppState();
    const nodeMap = new Map();
    const edgeMap = new Map();
    const docs = sortedDocs();
    const projectName = safeText(appState.projectName, "현재 작품");
    const docTitleById = new Map(docs.map((doc) => [doc.doc_id, nodeTitleForDoc(doc)]));

    addNode(nodeMap, {
      id: "work:current",
      label: projectName,
      type: "Work",
      dimensions: ["story", "setting", "source"],
      subtitle: "현재 프로젝트",
      description: "작품 전체를 기준으로 문서, 설정, 사건을 연결합니다.",
      sourceKind: "프로젝트",
      radius: 19,
      weight: 8,
    });

    const groupIds = new Map();
    docs.forEach((doc) => {
      const meta = doc.metadata || {};
      const title = nodeTitleForDoc(doc);
      const typeLabel = docTypeLabel(doc.type);
      const group = safeText(meta.group, "");
      const time = safeText(meta.time_key, "");
      const timeline = Number.isFinite(Number(meta.timeline_idx)) ? `순서 ${meta.timeline_idx}` : "";
      const subtitleParts = [typeLabel, group, time || timeline].filter(Boolean);

      addNode(nodeMap, {
        id: `doc:${doc.doc_id}`,
        label: title,
        type: inferDocType(doc),
        dimensions: inferDocDimensions(doc),
        subtitle: subtitleParts.join(" · "),
        description: "작품 안에 저장된 문서입니다. 클릭하면 해당 원문으로 이동할 수 있습니다.",
        sourceKind: "문서",
        docId: doc.doc_id,
        docType: doc.type,
        routeLabel: "원문으로 이동",
        data: { doc },
      });
      addEdge(edgeMap, {
        source: "work:current",
        target: `doc:${doc.doc_id}`,
        label: "포함",
        type: "CONTAINS_TEXT_UNIT",
        weight: 1.2,
      });

      if (group && group !== "미분류") {
        const groupId = `group:${group}`;
        groupIds.set(group, groupId);
        addNode(nodeMap, {
          id: groupId,
          label: group,
          type: "NarrativeCue",
          dimensions: ["story"],
          subtitle: "챕터 묶음",
          description: "같은 챕터로 묶인 문서를 모아 보여줍니다.",
          sourceKind: "문서 목록",
          radius: 12,
        });
        addEdge(edgeMap, {
          source: "work:current",
          target: groupId,
          label: "챕터",
          type: "HAS_GROUP",
          weight: 1,
        });
        addEdge(edgeMap, {
          source: groupId,
          target: `doc:${doc.doc_id}`,
          label: "문서",
          type: "GROUP_CONTAINS",
          weight: 0.9,
        });
      }
    });

    const timelineDocs = docs
      .filter((doc) => Number.isFinite(Number(doc?.metadata?.timeline_idx)) || Number.isFinite(Number(doc?.metadata?.order)))
      .sort((a, b) => timelineValue(a) - timelineValue(b));
    for (let i = 1; i < timelineDocs.length; i += 1) {
      addEdge(edgeMap, {
        source: `doc:${timelineDocs[i - 1].doc_id}`,
        target: `doc:${timelineDocs[i].doc_id}`,
        label: "다음",
        type: "TIMELINE_NEXT",
        weight: 0.8,
        dashed: true,
      });
    }

    const context = kgContext || {};
    const entities = Array.isArray(context.entities) ? context.entities : [];
    const facts = Array.isArray(context.facts) ? context.facts : [];
    const mentions = Array.isArray(context.mentions) ? context.mentions : [];
    const anchors = Array.isArray(context.anchors) ? context.anchors : [];
    const events = Array.isArray(context.events) ? context.events : [];

    entities.forEach((entity) => {
      const nodeType = entityType(entity.kind);
      addNode(nodeMap, {
        id: `entity:${entity.entity_id}`,
        label: safeText(entity.canonical_name, "이름 없는 설정"),
        type: nodeType,
        dimensions: entityDimensions(entity.kind),
        subtitle: entityKindLabel(entity.kind),
        description: "작품 설정으로 등록된 이름입니다. 본문에서 언급되면 문서와 연결됩니다.",
        sourceKind: "설정",
        data: { entity },
      });
      addEdge(edgeMap, {
        source: "work:current",
        target: `entity:${entity.entity_id}`,
        label: entityKindLabel(entity.kind),
        type: "HAS_ENTITY",
        weight: 1,
      });
    });

    mentions.forEach((mention) => {
      const entityId = `entity:${mention.entity_id}`;
      const docId = `doc:${mention.doc_id}`;
      if (!nodeMap.has(entityId) || !nodeMap.has(docId)) return;
      addEdge(edgeMap, {
        source: entityId,
        target: docId,
        label: "언급",
        type: "MENTIONED_IN",
        weight: 1.6,
        color: "#0891b2",
      });
    });

    anchors.forEach((anchor) => {
      const timeKey = safeText(anchor.time_key, "시간 정보");
      const timeId = `time:${timeKey}`;
      addNode(nodeMap, {
        id: timeId,
        label: timeKey,
        type: "TimeCue",
        dimensions: ["time"],
        subtitle: Number.isFinite(Number(anchor.timeline_idx)) ? `순서 ${anchor.timeline_idx}` : "시간 표시",
        description: "본문에서 잡힌 시간 단서입니다.",
        sourceKind: "시간 표시",
        docId: anchor.doc_id || null,
        data: { anchor },
      });
      if (anchor.doc_id && nodeMap.has(`doc:${anchor.doc_id}`)) {
        addEdge(edgeMap, {
          source: timeId,
          target: `doc:${anchor.doc_id}`,
          label: "나온 곳",
          type: "TIME_IN_DOC",
          weight: 1.1,
          color: "#ca8a04",
        });
      }
    });

    const sortedEvents = events
      .slice()
      .sort((a, b) => Number(a.timeline_idx || 0) - Number(b.timeline_idx || 0));
    sortedEvents.forEach((event) => {
      const eventId = `event:${event.timeline_event_id}`;
      const sourceTitle = docTitleById.get(event.source_doc_id) || "원문";
      addNode(nodeMap, {
        id: eventId,
        label: safeText(event.label, "사건"),
        type: "Event",
        dimensions: ["story", "time", "source"],
        subtitle: safeText(event.time_key, `순서 ${event.timeline_idx}`),
        description: `타임라인에서 확인된 사건입니다. 나온 곳: ${sourceTitle}`,
        sourceKind: "타임라인",
        docId: event.source_doc_id || null,
        data: { event },
      });
      addEdge(edgeMap, {
        source: "work:current",
        target: eventId,
        label: "사건",
        type: "HAS_EVENT",
        weight: 1.1,
      });
      if (event.source_doc_id && nodeMap.has(`doc:${event.source_doc_id}`)) {
        addEdge(edgeMap, {
          source: eventId,
          target: `doc:${event.source_doc_id}`,
          label: "원문",
          type: "EVENT_SOURCE",
          weight: 1.8,
          color: "#dc2626",
        });
      }
      if (event.time_key) {
        const timeId = `time:${event.time_key}`;
        addNode(nodeMap, {
          id: timeId,
          label: event.time_key,
          type: "TimeCue",
          dimensions: ["time"],
          subtitle: "시간 표시",
          sourceKind: "타임라인",
        });
        addEdge(edgeMap, {
          source: timeId,
          target: eventId,
          label: "시간",
          type: "EVENT_TIME",
          weight: 1.1,
          color: "#ca8a04",
        });
      }
    });
    for (let i = 1; i < sortedEvents.length; i += 1) {
      addEdge(edgeMap, {
        source: `event:${sortedEvents[i - 1].timeline_event_id}`,
        target: `event:${sortedEvents[i].timeline_event_id}`,
        label: "다음 사건",
        type: "EVENT_NEXT",
        weight: 0.85,
        dashed: true,
        color: "#ca8a04",
      });
    }

    facts.forEach((fact) => {
      const labelValue = valueLabel(fact.value);
      const label = shortText(labelValue || safeText(fact.tag_path, "설정"), 42);
      const factId = `fact:${fact.fact_id}`;
      const dims = ["setting"];
      if (fact.evidence_eid) dims.push("source");
      if (safeText(fact.status) !== "APPROVED") dims.push("review");
      addNode(nodeMap, {
        id: factId,
        label,
        type: safeText(fact.status) === "REJECTED" ? "ContradictionCandidate" : "Fact",
        dimensions: dims,
        subtitle: safeText(fact.tag_path, "설정값"),
        description: "설정으로 정리된 값입니다. 나중에 KG 추출기가 붙으면 이 계층이 더 촘촘해집니다.",
        sourceKind: "추출된 설정",
        data: { fact },
        radius: 10,
      });
      addEdge(edgeMap, {
        source: "work:current",
        target: factId,
        label: "설정",
        type: "HAS_FACT",
        weight: 0.75,
      });
      if (fact.entity_id && nodeMap.has(`entity:${fact.entity_id}`)) {
        addEdge(edgeMap, {
          source: `entity:${fact.entity_id}`,
          target: factId,
          label: "설정값",
          type: "ENTITY_FACT",
          weight: 1.2,
          color: "#7c3aed",
        });
      }
    });

    const nodes = Array.from(nodeMap.values());
    const edges = Array.from(edgeMap.values()).filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target));
    return { nodes, edges };
  }

  async function optionalGet(path) {
    if (typeof window.api !== "function") return null;
    try {
      return await window.api(path);
    } catch (_error) {
      return null;
    }
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  async function loadKgContext(projectId) {
    const pid = encodeURIComponent(projectId);
    const [schemaRes, factsRes, entitiesRes, mentionsRes, anchorsRes, eventsRes] = await Promise.all([
      optionalGet(`/projects/${pid}/schema`),
      optionalGet(`/projects/${pid}/schema/facts`),
      optionalGet(`/projects/${pid}/entities`),
      optionalGet(`/projects/${pid}/entity-mentions`),
      optionalGet(`/projects/${pid}/time-anchors`),
      optionalGet(`/projects/${pid}/timeline-events`),
    ]);
    const schemaFacts = asArray(schemaRes?.schema?.facts);
    const listedFacts = asArray(factsRes?.facts);
    return {
      facts: listedFacts.length ? listedFacts : schemaFacts,
      entities: asArray(entitiesRes?.entities),
      mentions: asArray(mentionsRes?.mentions),
      anchors: asArray(anchorsRes?.anchors),
      events: asArray(eventsRes?.events),
    };
  }

  function kgContextCount(context) {
    if (!context) return 0;
    return (
      asArray(context.facts).length +
      asArray(context.entities).length +
      asArray(context.mentions).length +
      asArray(context.anchors).length +
      asArray(context.events).length
    );
  }

  function visibleNodes() {
    const query = graphState.searchText.toLowerCase();
    return graphState.nodes.filter((node) => {
      if (!graphState.activeTypes.has(node.type)) return false;
      const dims = node.dimensions || [];
      if (dims.length && !dims.some((dim) => graphState.activeDimensions.has(dim))) return false;
      if (!query) return true;
      return `${node.label} ${node.subtitle} ${node.description}`.toLowerCase().includes(query);
    });
  }

  function visibleNodeSet() {
    return new Set(visibleNodes().map((node) => node.id));
  }

  function visibleEdges(idSet) {
    return graphState.edges.filter((edge) => idSet.has(edge.source) && idSet.has(edge.target));
  }

  function setSourceStatus(text) {
    const el = $("graph-view-source-status");
    if (el) el.textContent = text;
  }

  function updateStats() {
    const ids = visibleNodeSet();
    const nodeCount = $("graph-view-node-count");
    const edgeCount = $("graph-view-edge-count");
    if (nodeCount) nodeCount.textContent = String(ids.size);
    if (edgeCount) edgeCount.textContent = String(visibleEdges(ids).length);
    const empty = $("graph-view-empty");
    if (empty) empty.classList.toggle("active", ids.size === 0);
  }

  function renderTypeFilters() {
    const list = $("graph-view-type-list");
    if (!list) return;
    list.innerHTML = Object.entries(TYPE_META)
      .map(([type, meta]) => {
        const checked = graphState.activeTypes.has(type) ? "checked" : "";
        return `
          <label class="graph-view-check-item">
            <input type="checkbox" data-graph-view-type="${escapeHTML(type)}" ${checked} />
            <span class="graph-view-check-dot" style="--graph-color:${meta.color}"></span>
            <span>${escapeHTML(meta.label)}</span>
          </label>`;
      })
      .join("");
  }

  function renderDimensionFilters() {
    const list = $("graph-view-dimension-list");
    if (!list) return;
    list.innerHTML = Object.entries(DIMENSION_META)
      .map(([dim, meta]) => {
        const checked = graphState.activeDimensions.has(dim) ? "checked" : "";
        return `
          <label class="graph-view-check-item">
            <input type="checkbox" data-graph-view-dimension="${escapeHTML(dim)}" ${checked} />
            <span class="graph-view-check-dot" style="--graph-color:${meta.color}"></span>
            <span>${escapeHTML(meta.label)}</span>
          </label>`;
      })
      .join("");
  }

  function updateModeButtons() {
    document.querySelectorAll("[data-graph-view-mode]").forEach((button) => {
      button.classList.toggle("active", button.dataset.graphViewMode === graphState.mode);
    });
    const toggle = $("graph-view-cluster-toggle");
    if (toggle) {
      toggle.classList.toggle("active", graphState.clusterEnabled);
      toggle.setAttribute("aria-pressed", graphState.clusterEnabled ? "true" : "false");
    }
    const labelToggle = $("graph-view-label-toggle");
    if (labelToggle) labelToggle.classList.toggle("active", graphState.showLabels);
  }

  function preserveNodePositions(newNodes) {
    const old = graphState.nodeById;
    newNodes.forEach((node, index) => {
      const prev = old.get(node.id);
      if (prev) {
        node.x = prev.x;
        node.y = prev.y;
        node.z = prev.z;
        node.tx = prev.tx;
        node.ty = prev.ty;
        node.tz = prev.tz;
      } else {
        const hash = hashText(node.id);
        const angle = ((hash % 360) * Math.PI) / 180;
        const radius = 80 + (index % 9) * 18;
        node.x = canvasWidth / 2 + Math.cos(angle) * radius;
        node.y = canvasHeight / 2 + Math.sin(angle) * radius;
        node.z = ((hash % 200) - 100) / 100;
        node.tx = node.x;
        node.ty = node.y;
        node.tz = node.z;
      }
    });
  }

  function setGraphData(graphData) {
    const nodes = Array.isArray(graphData?.nodes) ? graphData.nodes : [];
    const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];
    preserveNodePositions(nodes);
    graphState.nodes = nodes;
    graphState.edges = edges;
    graphState.nodeById = new Map(nodes.map((node) => [node.id, node]));
    if (graphState.selectedNodeId && !graphState.nodeById.has(graphState.selectedNodeId)) {
      graphState.selectedNodeId = null;
    }
    assignTargets();
    updateStats();
    renderInspector();
  }

  function refreshGraphView(options = {}) {
    if (!graphState.open && !options.force) {
      graphState.stale = true;
      return Promise.resolve();
    }
    graphState.stale = false;
    const appState = getAppState();
    const docs = Object.values(appState.docs || {});
    const baseData = buildGraphData(null);
    setGraphData(baseData);
    if (!appState.projectId) {
      setSourceStatus(docs.length ? "문서 목록만으로 만든 임시 관계도입니다." : "프로젝트를 불러오면 관계도를 볼 수 있습니다.");
      return Promise.resolve();
    }

    const token = graphState.fetchToken + 1;
    graphState.fetchToken = token;
    setSourceStatus("문서와 설정 정보를 함께 읽는 중입니다...");
    return loadKgContext(appState.projectId).then((context) => {
      if (token !== graphState.fetchToken) return;
      const count = kgContextCount(context);
      setGraphData(buildGraphData(count ? context : null));
      if (count) {
        setSourceStatus("문서, 설정, 인물/장소, 시간 정보를 함께 보여줍니다.");
      } else {
        setSourceStatus("아직 추출된 설정이 없어 문서 목록을 중심으로 보여줍니다.");
      }
    });
  }

  function primaryDimension(node) {
    const dims = node.dimensions || [];
    return dims.find((dim) => graphState.activeDimensions.has(dim)) || dims[0] || "story";
  }

  function typeIndex(node) {
    return Object.keys(TYPE_META).indexOf(node.type);
  }

  function dimensionCenter(dim, width, height) {
    const meta = DIMENSION_META[dim] || DIMENSION_META.story;
    return {
      x: width * meta.x,
      y: height * meta.y,
    };
  }

  function assignTargets() {
    if (!canvasWidth || !canvasHeight) return;
    const nodes = visibleNodes();
    const ids = new Set(nodes.map((node) => node.id));
    const nonWork = nodes.filter((node) => node.id !== "work:current");
    const centerX = canvasWidth / 2;
    const centerY = canvasHeight / 2;
    const distanceScale = graphState.clusterDistance / 128;
    const useClusters = graphState.clusterEnabled || graphState.mode === "nd";

    graphState.nodes.forEach((node) => {
      if (!ids.has(node.id)) return;
      if (node.id === "work:current") {
        node.tx = centerX;
        node.ty = centerY;
        node.tz = 0;
        return;
      }
      const hash = hashText(node.id);
      const index = Math.max(0, nonWork.findIndex((item) => item.id === node.id));
      const dim = primaryDimension(node);
      const jitterAngle = ((hash % 360) * Math.PI) / 180;
      const jitter = 22 + (hash % 37);

      if (graphState.mode === "3d") {
        const dimCenter = dimensionCenter(dim, 2.2, 1.7);
        const baseAngle = (index / Math.max(1, nonWork.length)) * Math.PI * 2;
        const clusterPull = useClusters ? distanceScale : 0.35;
        node.tx = (Math.cos(baseAngle) * 0.95 + (dimCenter.x - 1.1) * clusterPull) * 170;
        node.ty = (Math.sin(baseAngle * 0.83) * 0.72 + (dimCenter.y - 0.85) * clusterPull) * 150;
        node.tz = Math.sin(baseAngle + (hash % 31)) * 130 + (typeIndex(node) % 5) * 22;
        return;
      }

      if (useClusters) {
        const center = dimensionCenter(dim, canvasWidth, canvasHeight);
        const pull = graphState.clusterEnabled ? distanceScale : 0.55;
        node.tx = centerX + (center.x - centerX) * pull + Math.cos(jitterAngle) * jitter;
        node.ty = centerY + (center.y - centerY) * pull + Math.sin(jitterAngle) * jitter;
      } else {
        const radius = Math.min(canvasWidth, canvasHeight) * (0.25 + (typeIndex(node) % 4) * 0.045);
        const angle = (index / Math.max(1, nonWork.length)) * Math.PI * 2 - Math.PI / 2;
        node.tx = centerX + Math.cos(angle) * radius + Math.cos(jitterAngle) * 12;
        node.ty = centerY + Math.sin(angle) * radius * 0.72 + Math.sin(jitterAngle) * 12;
      }
      node.tz = 0;
    });
  }

  function resizeCanvas() {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    canvasWidth = Math.max(320, rect.width || 0);
    canvasHeight = Math.max(280, rect.height || 0);
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(canvasWidth * ratio);
    canvas.height = Math.round(canvasHeight * ratio);
    if (ctx) ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    assignTargets();
  }

  function lerp(current, target, speed) {
    if (!Number.isFinite(current)) return target;
    return current + (target - current) * speed;
  }

  function projectNode(node) {
    if (graphState.mode === "3d") {
      const angle = graphState.rotation;
      const cos = Math.cos(angle);
      const sin = Math.sin(angle);
      const x = node.x * cos - node.z * sin;
      const z = node.x * sin + node.z * cos;
      const perspective = 560 / (560 + z);
      node.screenX = canvasWidth / 2 + x * perspective * graphState.zoom + graphState.panX;
      node.screenY = canvasHeight / 2 + node.y * perspective * graphState.zoom + graphState.panY;
      node.screenRadius = Math.max(5, (node.radius + Math.min(8, node.weight)) * perspective * graphState.zoom);
      node.alpha = Math.max(0.28, Math.min(1, 0.74 + z / 520));
      return;
    }
    node.screenX = canvasWidth / 2 + (node.x - canvasWidth / 2) * graphState.zoom + graphState.panX;
    node.screenY = canvasHeight / 2 + (node.y - canvasHeight / 2) * graphState.zoom + graphState.panY;
    node.screenRadius = Math.max(5, (node.radius + Math.min(7, node.weight * 0.55)) * graphState.zoom);
    node.alpha = 1;
  }

  function updatePhysics() {
    if (graphState.mode === "3d") {
      graphState.rotation += graphState.clusterEnabled ? 0.0025 : 0.0015;
    }
    const ids = visibleNodeSet();
    graphState.nodes.forEach((node) => {
      if (!ids.has(node.id)) return;
      node.x = lerp(node.x, node.tx, 0.08);
      node.y = lerp(node.y, node.ty, 0.08);
      node.z = lerp(node.z, node.tz, 0.08);
      projectNode(node);
    });
  }

  function drawClusterHints(ids) {
    if (!(graphState.clusterEnabled || graphState.mode === "nd") || graphState.mode === "3d") return;
    const presentDims = new Set();
    graphState.nodes.forEach((node) => {
      if (!ids.has(node.id)) return;
      (node.dimensions || []).forEach((dim) => {
        if (graphState.activeDimensions.has(dim)) presentDims.add(dim);
      });
    });
    ctx.save();
    presentDims.forEach((dim) => {
      const meta = DIMENSION_META[dim];
      if (!meta) return;
      const center = dimensionCenter(dim, canvasWidth, canvasHeight);
      const radius = Math.max(56, Math.min(canvasWidth, canvasHeight) * 0.13 * (graphState.clusterDistance / 128));
      ctx.beginPath();
      ctx.fillStyle = `${meta.color}12`;
      ctx.strokeStyle = `${meta.color}45`;
      ctx.lineWidth = 1;
      ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = meta.color;
      ctx.font = "700 12px 'Noto Sans KR', sans-serif";
      ctx.fillText(meta.label, center.x - radius + 10, center.y - radius + 20);
    });
    ctx.restore();
  }

  function drawEdge(edge) {
    const source = graphState.nodeById.get(edge.source);
    const target = graphState.nodeById.get(edge.target);
    if (!source || !target) return;
    const selected = graphState.selectedNodeId && (edge.source === graphState.selectedNodeId || edge.target === graphState.selectedNodeId);
    const alpha = selected ? 0.85 : 0.24 + Math.min(0.22, edge.weight * 0.035);
    ctx.save();
    ctx.globalAlpha = alpha * Math.min(source.alpha, target.alpha);
    ctx.strokeStyle = selected ? "#0f766e" : edge.color;
    ctx.lineWidth = selected ? 2.2 : Math.max(1, Math.min(3, edge.weight * 0.55));
    if (edge.dashed) ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(source.screenX, source.screenY);
    ctx.lineTo(target.screenX, target.screenY);
    ctx.stroke();
    ctx.restore();
  }

  function drawNode(node) {
    const selected = graphState.selectedNodeId === node.id;
    const hovered = graphState.hoverNodeId === node.id;
    const radius = node.screenRadius + (selected ? 3 : hovered ? 2 : 0);
    ctx.save();
    ctx.globalAlpha = node.alpha;
    ctx.beginPath();
    ctx.fillStyle = node.color;
    ctx.arc(node.screenX, node.screenY, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = selected ? 3 : 1.5;
    ctx.strokeStyle = selected ? "#0f172a" : "rgba(255, 255, 255, 0.95)";
    ctx.stroke();

    if (selected || hovered) {
      ctx.beginPath();
      ctx.strokeStyle = `${node.color}55`;
      ctx.lineWidth = 7;
      ctx.arc(node.screenX, node.screenY, radius + 4, 0, Math.PI * 2);
      ctx.stroke();
    }

    if (graphState.showLabels && (selected || hovered || node.type === "Work" || radius > 10)) {
      const label = shortText(node.label, selected || hovered ? 24 : 16);
      ctx.font = `${selected ? "700" : "600"} 12px 'Noto Sans KR', sans-serif`;
      const width = ctx.measureText(label).width;
      const x = node.screenX - width / 2;
      const y = node.screenY + radius + 16;
      ctx.fillStyle = "rgba(255, 255, 255, 0.92)";
      ctx.strokeStyle = "rgba(203, 213, 225, 0.95)";
      roundRect(ctx, x - 6, y - 13, width + 12, 19, 6);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = selected ? "#0f172a" : "#334155";
      ctx.fillText(label, x, y);
    }
    ctx.restore();
  }

  function roundRect(context, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    context.beginPath();
    context.moveTo(x + r, y);
    context.arcTo(x + width, y, x + width, y + height, r);
    context.arcTo(x + width, y + height, x, y + height, r);
    context.arcTo(x, y + height, x, y, r);
    context.arcTo(x, y, x + width, y, r);
    context.closePath();
  }

  function drawGraph() {
    if (!ctx || !canvasWidth || !canvasHeight) return;
    ctx.clearRect(0, 0, canvasWidth, canvasHeight);
    const ids = visibleNodeSet();
    drawClusterHints(ids);
    visibleEdges(ids).forEach(drawEdge);
    visibleNodes()
      .slice()
      .sort((a, b) => a.alpha - b.alpha)
      .forEach(drawNode);
  }

  function renderLoop() {
    if (!graphState.open) return;
    updatePhysics();
    drawGraph();
    graphState.animationFrame = window.requestAnimationFrame(renderLoop);
  }

  function startRenderLoop() {
    if (graphState.animationFrame) window.cancelAnimationFrame(graphState.animationFrame);
    graphState.animationFrame = window.requestAnimationFrame(renderLoop);
  }

  function stopRenderLoop() {
    if (graphState.animationFrame) window.cancelAnimationFrame(graphState.animationFrame);
    graphState.animationFrame = null;
  }

  function hitTest(x, y) {
    const nodes = visibleNodes().slice().reverse();
    return nodes.find((node) => {
      const dx = x - node.screenX;
      const dy = y - node.screenY;
      return Math.sqrt(dx * dx + dy * dy) <= node.screenRadius + 7;
    });
  }

  function pointerPosition(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  function selectNode(nodeId) {
    graphState.selectedNodeId = nodeId || null;
    renderInspector();
  }

  function renderInspector() {
    const box = $("graph-view-inspector-content");
    const primary = $("graph-view-route-primary");
    const secondary = $("graph-view-route-secondary");
    const node = graphState.selectedNodeId ? graphState.nodeById.get(graphState.selectedNodeId) : null;
    if (!box) return;
    if (!node) {
      box.innerHTML = '<div class="graph-view-inspector-empty">그래프에서 인물, 장소, 사건, 문서를 클릭해보세요.</div>';
      if (primary) primary.disabled = true;
      if (secondary) secondary.disabled = true;
      return;
    }
    const typeMeta = TYPE_META[node.type] || TYPE_META.TextUnit;
    const dimensionBadges = (node.dimensions || [])
      .map((dim) => DIMENSION_META[dim]?.label)
      .filter(Boolean)
      .map((label) => `<span class="graph-view-pill">${escapeHTML(label)}</span>`)
      .join("");
    const docTitle = node.docId ? nodeTitleForDoc(getAppState().docs?.[node.docId]) : "";
    const status = safeText(node.data?.fact?.status || node.data?.event?.status || "");
    box.innerHTML = `
      <div class="graph-view-inspector-card">
        <div class="graph-view-inspector-badges">
          <span class="graph-view-pill" style="color:${typeMeta.color}; border-color:${typeMeta.color}55; background:${typeMeta.color}12">${escapeHTML(typeMeta.label)}</span>
          ${dimensionBadges}
        </div>
        <h3>${escapeHTML(node.label)}</h3>
        <p>${escapeHTML(node.description || node.subtitle || "작품 안에서 연결된 요소입니다.")}</p>
        <div class="graph-view-detail-list">
          <div class="graph-view-detail-row">
            <span>나온 곳</span>
            <strong>${escapeHTML(node.sourceKind || "문서")}</strong>
          </div>
          <div class="graph-view-detail-row">
            <span>연결된 문서</span>
            <strong>${escapeHTML(docTitle || "연결된 원문 없음")}</strong>
          </div>
          <div class="graph-view-detail-row">
            <span>메모</span>
            <strong>${escapeHTML(status ? `상태: ${status}` : node.subtitle || "클릭한 요소와 가까운 선을 따라 관련 항목을 확인하세요.")}</strong>
          </div>
        </div>
      </div>`;
    if (primary) {
      primary.disabled = !node.docId;
      primary.textContent = node.docId ? "원문으로 이동" : "연결된 원문 없음";
    }
    if (secondary) {
      secondary.disabled = !(node.docId || node.type === "Character" || node.type === "Place" || node.type === "Fact");
      secondary.textContent = node.docId ? "문서 목록에서 보기" : "설정 목록에서 보기";
    }
  }

  function centerOnNode(nodeId) {
    const node = graphState.nodeById.get(nodeId);
    if (!node) return;
    projectNode(node);
    graphState.panX += canvasWidth / 2 - node.screenX;
    graphState.panY += canvasHeight / 2 - node.screenY;
  }

  async function routeSelected(preferList) {
    const node = graphState.selectedNodeId ? graphState.nodeById.get(graphState.selectedNodeId) : null;
    if (!node) return;
    if (node.docId && typeof window.loadDoc === "function") {
      if (preferList && node.docType && typeof window.switchNavTab === "function") {
        window.switchNavTab(node.docType);
      }
      await window.loadDoc(node.docId);
      closeGraphView();
      return;
    }
    if ((node.type === "Character" || node.type === "Place" || node.type === "Fact") && typeof window.switchNavTab === "function") {
      window.switchNavTab("SETTING");
      closeGraphView();
    }
  }

  function focusCurrentDoc() {
    const currentDocId = getAppState().currentDocId;
    if (!currentDocId) return;
    const nodeId = `doc:${currentDocId}`;
    if (!graphState.nodeById.has(nodeId)) {
      refreshGraphView({ force: true }).then(() => {
        if (graphState.nodeById.has(nodeId)) {
          selectNode(nodeId);
          centerOnNode(nodeId);
        }
      });
      return;
    }
    selectNode(nodeId);
    centerOnNode(nodeId);
  }

  function resetView() {
    graphState.zoom = 1;
    graphState.panX = 0;
    graphState.panY = 0;
    graphState.rotation = 0;
    assignTargets();
  }

  function openGraphView() {
    const panel = $("graph-view-panel");
    if (!panel) return;
    graphState.open = true;
    panel.classList.add("is-open");
    panel.inert = false;
    panel.setAttribute("aria-hidden", "false");
    $("graph-view-open-btn")?.classList.add("active");
    $("graph-view-sidebar-btn")?.classList.add("active");
    if (typeof window.closeRightSidebar === "function") window.closeRightSidebar();
    if (typeof window.closeLeftSidebar === "function") window.closeLeftSidebar();
    resizeCanvas();
    updateModeButtons();
    startRenderLoop();
    refreshGraphView({ force: true }).then(() => {
      resizeCanvas();
      if (getAppState().currentDocId && !graphState.selectedNodeId) {
        const nodeId = `doc:${getAppState().currentDocId}`;
        if (graphState.nodeById.has(nodeId)) selectNode(nodeId);
      }
    });
  }

  function closeGraphView() {
    const panel = $("graph-view-panel");
    if (!panel) return;
    graphState.open = false;
    panel.classList.remove("is-open");
    panel.inert = true;
    panel.setAttribute("aria-hidden", "true");
    $("graph-view-open-btn")?.classList.remove("active");
    $("graph-view-sidebar-btn")?.classList.remove("active");
    stopRenderLoop();
  }

  function toggleGraphView() {
    if (graphState.open) closeGraphView();
    else openGraphView();
  }

  function syncGraphViewSelection(docId) {
    const nodeId = docId ? `doc:${docId}` : null;
    if (!nodeId) return;
    if (graphState.nodeById.has(nodeId)) {
      selectNode(nodeId);
      if (graphState.open) centerOnNode(nodeId);
    }
  }

  function bindEvents() {
    canvas = $("graph-view-canvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");
    resizeCanvas();
    renderTypeFilters();
    renderDimensionFilters();
    updateModeButtons();

    document.querySelectorAll("[data-graph-view-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        graphState.mode = button.dataset.graphViewMode || "2d";
        updateModeButtons();
        assignTargets();
      });
    });

    $("graph-view-refresh")?.addEventListener("click", () => refreshGraphView({ force: true }));
    $("graph-view-cluster-toggle")?.addEventListener("click", () => {
      graphState.clusterEnabled = !graphState.clusterEnabled;
      updateModeButtons();
      assignTargets();
    });
    $("graph-view-distance")?.addEventListener("input", (event) => {
      graphState.clusterDistance = Number(event.target.value) || 128;
      assignTargets();
    });
    $("graph-view-search")?.addEventListener("input", (event) => {
      graphState.searchText = safeText(event.target.value).toLowerCase();
      assignTargets();
      updateStats();
    });
    $("graph-view-reset")?.addEventListener("click", resetView);
    $("graph-view-label-toggle")?.addEventListener("click", () => {
      graphState.showLabels = !graphState.showLabels;
      updateModeButtons();
    });
    $("graph-view-focus-current")?.addEventListener("click", focusCurrentDoc);
    $("graph-view-route-primary")?.addEventListener("click", () => routeSelected(false));
    $("graph-view-route-secondary")?.addEventListener("click", () => routeSelected(true));

    $("graph-view-type-list")?.addEventListener("change", (event) => {
      const type = event.target?.dataset?.graphViewType;
      if (!type) return;
      if (event.target.checked) graphState.activeTypes.add(type);
      else graphState.activeTypes.delete(type);
      assignTargets();
      updateStats();
      renderInspector();
    });

    $("graph-view-dimension-list")?.addEventListener("change", (event) => {
      const dim = event.target?.dataset?.graphViewDimension;
      if (!dim) return;
      if (event.target.checked) graphState.activeDimensions.add(dim);
      else graphState.activeDimensions.delete(dim);
      if (graphState.activeDimensions.size === 0) graphState.activeDimensions.add("story");
      assignTargets();
      updateStats();
      renderInspector();
    });

    canvas.addEventListener("pointerdown", (event) => {
      canvas.setPointerCapture(event.pointerId);
      graphState.pointer.dragging = true;
      graphState.pointer.moved = false;
      graphState.pointer.lastX = event.clientX;
      graphState.pointer.lastY = event.clientY;
      canvas.classList.add("dragging");
    });

    canvas.addEventListener("pointermove", (event) => {
      const pos = pointerPosition(event);
      if (graphState.pointer.dragging) {
        const dx = event.clientX - graphState.pointer.lastX;
        const dy = event.clientY - graphState.pointer.lastY;
        if (Math.abs(dx) + Math.abs(dy) > 2) graphState.pointer.moved = true;
        graphState.panX += dx;
        graphState.panY += dy;
        graphState.pointer.lastX = event.clientX;
        graphState.pointer.lastY = event.clientY;
        return;
      }
      const hit = hitTest(pos.x, pos.y);
      graphState.hoverNodeId = hit ? hit.id : null;
    });

    canvas.addEventListener("pointerup", (event) => {
      const pos = pointerPosition(event);
      graphState.pointer.dragging = false;
      canvas.classList.remove("dragging");
      if (!graphState.pointer.moved) {
        const hit = hitTest(pos.x, pos.y);
        selectNode(hit ? hit.id : null);
      }
    });

    canvas.addEventListener("pointerleave", () => {
      graphState.hoverNodeId = null;
      graphState.pointer.dragging = false;
      canvas.classList.remove("dragging");
    });

    canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const next = graphState.zoom * (event.deltaY > 0 ? 0.92 : 1.08);
        graphState.zoom = Math.max(0.45, Math.min(2.2, next));
      },
      { passive: false },
    );

    window.addEventListener("resize", () => {
      if (graphState.open) resizeCanvas();
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && graphState.open) closeGraphView();
    });
  }

  window.openGraphView = openGraphView;
  window.closeGraphView = closeGraphView;
  window.toggleGraphView = toggleGraphView;
  window.refreshGraphView = refreshGraphView;
  window.syncGraphViewSelection = syncGraphViewSelection;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindEvents);
  } else {
    bindEvents();
  }
})();
