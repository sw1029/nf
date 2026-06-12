(function () {
  "use strict";

  const TYPE_META = {
    Work: { label: "작품", color: "#0f766e", radius: 18 },
    TextUnit: { label: "본문 위치", color: "#64748b", radius: 12 },
    Character: { label: "인물", color: "#2563eb", radius: 13 },
    Place: { label: "장소", color: "#16a34a", radius: 12 },
    Event: { label: "사건", color: "#dc2626", radius: 13 },
    TimeCue: { label: "시간", color: "#ca8a04", radius: 11 },
    Fact: { label: "설정", color: "#7c3aed", radius: 11 },
    Evidence: { label: "관련 문장", color: "#0891b2", radius: 10 },
    NarrativeCue: { label: "복선", color: "#db2777", radius: 12 },
    ContradictionCandidate: { label: "확인 필요", color: "#ea580c", radius: 13 },
  };

  const DIMENSION_META = {
    story: { label: "이야기 흐름", color: "#2563eb", x: 0.28, y: 0.36 },
    setting: { label: "세계관 설정", color: "#7c3aed", x: 0.72, y: 0.34 },
    time: { label: "시간 순서", color: "#ca8a04", x: 0.5, y: 0.74 },
    entity: { label: "인물/장소", color: "#16a34a", x: 0.22, y: 0.68 },
    source: { label: "관련 문장", color: "#0891b2", x: 0.78, y: 0.7 },
    review: { label: "확인 필요", color: "#ea580c", x: 0.5, y: 0.23 },
  };

  const DIMENSION_COLOR_STORAGE_KEY = "nf.graphView.dimensionColors";
  const RELATION_LABELS = {
    SAME_ENTITY: "같은 인물/대상",
    SAME_WORLD: "같은 장소/세계관",
    SIMILAR_EVENT: "닮은 사건",
    NARRATIVE_HINT: "힌트/복선",
    CONTRASTS_WITH: "대비/충돌",
    CUSTOM: "직접 입력",
  };

  const graphState = {
    open: false,
    stale: true,
    mode: "2d",
    clusterEnabled: false,
    clusterDistance: 128,
    showClusterClouds: true,
    showLabels: true,
    activeTypes: new Set(Object.keys(TYPE_META)),
    activeDimensions: new Set(["story", "setting", "time", "entity", "source"]),
    favoriteOnly: false,
    searchText: "",
    nodes: [],
    edges: [],
    nodeById: new Map(),
    externalGraph: { sources: [], nodes: [], edges: [], links: [], favorites: [] },
    favorites: new Set(),
    externalDrawerOpen: false,
    externalProjects: [],
    linkMode: false,
    linkDraft: null,
    selectedNodeId: null,
    hoverNodeId: null,
    panX: 0,
    panY: 0,
    zoom: 1,
    rotation: 0,
    rotationX: -0.12,
    autoRotate: true,
    fetchToken: 0,
    animationFrame: null,
    pointer: {
      dragging: false,
      moved: false,
      lastX: 0,
      lastY: 0,
      mode: "pan",
      nodeId: null,
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

  function normalizeHexColor(value, fallback = "#0f766e") {
    const text = safeText(value).trim();
    if (/^#[0-9a-f]{6}$/i.test(text)) return text.toLowerCase();
    if (/^#[0-9a-f]{3}$/i.test(text)) {
      return `#${text[1]}${text[1]}${text[2]}${text[2]}${text[3]}${text[3]}`.toLowerCase();
    }
    return fallback;
  }

  function colorWithAlpha(value, alpha) {
    const hex = normalizeHexColor(value);
    const numeric = Number.parseInt(hex.slice(1), 16);
    const r = (numeric >> 16) & 255;
    const g = (numeric >> 8) & 255;
    const b = numeric & 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function externalSourceById(sourceId) {
    return (graphState.externalGraph.sources || []).find((source) => source.source_id === sourceId) || null;
  }

  function isExternalNodeId(nodeId) {
    return typeof nodeId === "string" && nodeId.startsWith("ext:");
  }

  function publicNodeType(value) {
    const type = safeText(value, "Fact");
    return TYPE_META[type] ? type : "Fact";
  }

  function relationLabel(value) {
    return RELATION_LABELS[value] || safeText(value, "연결");
  }

  function sourceColor(source, fallback = "#14b8a6") {
    return normalizeHexColor(source?.color, fallback);
  }

  function emptyExternalGraph() {
    return { sources: [], nodes: [], edges: [], links: [], favorites: [] };
  }

  function syncFavoriteSet() {
    graphState.favorites = new Set((graphState.externalGraph.favorites || []).map((item) => item.node_ref));
  }

  function favoriteCountForSource(sourceId) {
    return (graphState.externalGraph.favorites || []).filter((item) => item.source_id === sourceId).length;
  }

  function linkCountForSource(sourceId) {
    return (graphState.externalGraph.links || []).filter((item) => item.source_id === sourceId && (!item.status || item.status === "ACTIVE")).length;
  }

  function isFavorite(nodeId) {
    return graphState.favorites.has(nodeId);
  }

  function loadDimensionColors() {
    try {
      if (typeof localStorage === "undefined") return;
      const raw = localStorage.getItem(DIMENSION_COLOR_STORAGE_KEY);
      const saved = raw ? JSON.parse(raw) : {};
      Object.entries(saved).forEach(([dim, color]) => {
        if (DIMENSION_META[dim]) DIMENSION_META[dim].color = normalizeHexColor(color, DIMENSION_META[dim].color);
      });
    } catch (_error) {
      // Ignore unavailable storage or malformed user settings.
    }
  }

  function saveDimensionColors() {
    try {
      if (typeof localStorage === "undefined") return;
      const payload = {};
      Object.entries(DIMENSION_META).forEach(([dim, meta]) => {
        payload[dim] = normalizeHexColor(meta.color);
      });
      localStorage.setItem(DIMENSION_COLOR_STORAGE_KEY, JSON.stringify(payload));
    } catch (_error) {
      // Ignore unavailable storage.
    }
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

  function textToBytes(text) {
    return new TextEncoder().encode(text);
  }

  function bytesToText(bytes) {
    return new TextDecoder().decode(bytes);
  }

  function bytesToBase64Url(bytes) {
    let binary = "";
    bytes.forEach((value) => {
      binary += String.fromCharCode(value);
    });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function base64UrlToBytes(value) {
    const normalized = safeText(value).replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }

  function randomBytes(length) {
    const bytes = new Uint8Array(length);
    crypto.getRandomValues(bytes);
    return bytes;
  }

  async function deriveStoryPackageKey(password, salt, iterations) {
    const keyMaterial = await crypto.subtle.importKey(
      "raw",
      textToBytes(password),
      "PBKDF2",
      false,
      ["deriveKey"],
    );
    return crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
      keyMaterial,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"],
    );
  }

  async function protectStoryPackage(packageDraft, password = "") {
    const pkg = {
      format: "nf-story-package-v1",
      content_kind: "knowledge_graph",
      display_name: "작품 정리 파일",
      created_at: new Date().toISOString(),
      payload_encoding: "json-v1",
      security: { mode: "none" },
      ...packageDraft,
    };
    const payloadBytes = textToBytes(JSON.stringify(pkg.payload || {}));
    const cleanPassword = safeText(password);
    if (cleanPassword) {
      const salt = randomBytes(16);
      const iv = randomBytes(12);
      const iterations = 120000;
      const key = await deriveStoryPackageKey(cleanPassword, salt, iterations);
      const encrypted = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, payloadBytes));
      return {
        ...pkg,
        payload_encoding: "encrypted-aes-gcm-v1",
        security: {
          mode: "password",
          cipher: "AES-GCM",
          kdf: "PBKDF2-SHA256",
          iterations,
          salt: bytesToBase64Url(salt),
          iv: bytesToBase64Url(iv),
        },
        payload: bytesToBase64Url(encrypted),
      };
    }
    return {
      ...pkg,
      payload_encoding: "obfuscated-v1",
      security: { mode: "obfuscated" },
      payload: bytesToBase64Url(payloadBytes),
    };
  }

  async function openStoryPackage(rawText, password = "") {
    const pkg = JSON.parse(rawText);
    if (pkg.format !== "nf-story-package-v1") {
      if (pkg.nodes || pkg.edges || pkg.bundle) {
        return {
          format: "nf-story-package-v1",
          content_kind: "knowledge_graph",
          display_name: safeText(pkg.source_label, "가져온 작품"),
          created_at: new Date().toISOString(),
          payload_encoding: "json-v1",
          security: { mode: "legacy-json" },
          payload: pkg.bundle ? pkg : { bundle: pkg },
        };
      }
      throw new Error("작품 정리 파일 형식이 아닙니다.");
    }
    if (pkg.payload_encoding === "json-v1") return pkg;
    if (pkg.payload_encoding === "obfuscated-v1") {
      return {
        ...pkg,
        payload_encoding: "json-v1",
        security: { mode: "decoded-in-browser", original: "obfuscated" },
        payload: JSON.parse(bytesToText(base64UrlToBytes(pkg.payload))),
      };
    }
    if (pkg.payload_encoding === "encrypted-aes-gcm-v1") {
      const cleanPassword = safeText(password);
      if (!cleanPassword) throw new Error("비밀번호가 필요합니다.");
      const salt = base64UrlToBytes(pkg.security?.salt);
      const iv = base64UrlToBytes(pkg.security?.iv);
      const iterations = Number(pkg.security?.iterations) || 120000;
      const key = await deriveStoryPackageKey(cleanPassword, salt, iterations);
      const decrypted = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv },
        key,
        base64UrlToBytes(pkg.payload),
      );
      return {
        ...pkg,
        payload_encoding: "json-v1",
        security: { mode: "decoded-in-browser", original: "password" },
        payload: JSON.parse(bytesToText(new Uint8Array(decrypted))),
      };
    }
    throw new Error("지원하지 않는 작품 정리 파일입니다.");
  }

  function downloadJSONFile(filename, payload) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(link.href);
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
      routeLabel: safeText(node.routeLabel, node.docId ? "본문으로 이동" : "목록에서 보기"),
      origin: safeText(node.origin, "current"),
      sourceId: node.sourceId || null,
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
      origin: safeText(edge.origin, "current"),
      sourceId: edge.sourceId || null,
      linkId: edge.linkId || null,
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
        description: "작품 안에 저장된 본문 위치입니다. 클릭하면 해당 본문으로 이동할 수 있습니다.",
        sourceKind: "문서",
        docId: doc.doc_id,
        docType: doc.type,
        routeLabel: "본문으로 이동",
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
      const sourceTitle = docTitleById.get(event.source_doc_id) || "본문";
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
          label: "본문",
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
        description: "작품 설정으로 정리된 값입니다. 이후 자동 정리 기능이 고도화되면 더 촘촘하게 연결됩니다.",
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

    const externalGraph = context?.externalGraph || emptyExternalGraph();
    const sources = Array.isArray(externalGraph.sources) ? externalGraph.sources : [];
    const externalNodes = Array.isArray(externalGraph.nodes) ? externalGraph.nodes : [];
    const externalEdges = Array.isArray(externalGraph.edges) ? externalGraph.edges : [];
    const externalLinks = Array.isArray(externalGraph.links) ? externalGraph.links : [];
    const enabledSourceIds = new Set(sources.filter((source) => source.enabled !== false).map((source) => source.source_id));
    const sourceNodeIds = new Map();

    sources.forEach((source) => {
      if (!enabledSourceIds.has(source.source_id)) return;
      const sourceNodeId = `external-source:${source.source_id}`;
      sourceNodeIds.set(source.source_id, sourceNodeId);
      const color = sourceColor(source);
      addNode(nodeMap, {
        id: sourceNodeId,
        label: safeText(source.source_label, "가져온 작품"),
        type: "Work",
        dimensions: ["story", "source"],
        subtitle: source.source_kind === "nf_project" ? "내 프로젝트" : "작품 정리 파일",
        description: "가져온 작품의 작품 관계도입니다. 필요한 관계만 현재 작품과 연결합니다.",
        sourceKind: "가져온 작품",
        origin: "external",
        sourceId: source.source_id,
        radius: 17,
        weight: 5,
        color,
        data: { externalSource: source },
      });
      addEdge(edgeMap, {
        source: "work:current",
        target: sourceNodeId,
        label: "참고 작품",
        type: "EXTERNAL_SOURCE",
        weight: 0.8,
        color,
        dashed: true,
        origin: "external",
        sourceId: source.source_id,
      });
    });

    externalNodes.forEach((node) => {
      if (!enabledSourceIds.has(node.source_id)) return;
      const source = sources.find((item) => item.source_id === node.source_id);
      const type = publicNodeType(node.node_type);
      const color = sourceColor(source, TYPE_META[type]?.color || "#14b8a6");
      addNode(nodeMap, {
        id: node.node_ref,
        label: safeText(node.label, "가져온 요소"),
        type,
        dimensions: type === "Event" ? ["story", "source"] : type === "TimeCue" ? ["time", "source"] : ["setting", "source"],
        subtitle: safeText(source?.source_label, "가져온 작품"),
        description: "가져온 작품의 관계도에 있던 요소입니다. 원본은 바꾸지 않고 현재 그래프에만 함께 보여줍니다.",
        sourceKind: "가져온 작품",
        origin: "external",
        sourceId: node.source_id,
        color,
        data: { externalNode: node, externalSource: source },
      });
      const sourceNodeId = sourceNodeIds.get(node.source_id);
      if (sourceNodeId) {
        addEdge(edgeMap, {
          source: sourceNodeId,
          target: node.node_ref,
          label: "포함",
          type: "EXTERNAL_CONTAINS",
          weight: 0.45,
          color,
          dashed: true,
          origin: "external",
          sourceId: node.source_id,
        });
      }
    });

    externalEdges.forEach((edge) => {
      if (!enabledSourceIds.has(edge.source_id)) return;
      if (!nodeMap.has(edge.src_node_ref) || !nodeMap.has(edge.dst_node_ref)) return;
      const source = sources.find((item) => item.source_id === edge.source_id);
      addEdge(edgeMap, {
        source: edge.src_node_ref,
        target: edge.dst_node_ref,
        label: edge.label || edge.edge_type,
        type: `EXTERNAL_${edge.edge_type || "RELATED"}`,
        weight: 0.75,
        color: sourceColor(source),
        dashed: true,
        origin: "external",
        sourceId: edge.source_id,
      });
    });

    externalLinks.forEach((link) => {
      if (link.status && link.status !== "ACTIVE") return;
      if (!enabledSourceIds.has(link.source_id)) return;
      if (!nodeMap.has(link.src_node_ref) || !nodeMap.has(link.dst_node_ref)) return;
      const source = sources.find((item) => item.source_id === link.source_id);
      addEdge(edgeMap, {
        source: link.src_node_ref,
        target: link.dst_node_ref,
        label: link.label || relationLabel(link.relation_type),
        type: `MANUAL_${link.relation_type || "RELATED"}`,
        weight: 2.2,
        color: sourceColor(source, "#0f766e"),
        dashed: false,
        origin: "manual-external-link",
        sourceId: link.source_id,
        linkId: link.link_id,
      });
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
    const [schemaRes, factsRes, entitiesRes, mentionsRes, anchorsRes, eventsRes, graphRes] = await Promise.all([
      optionalGet(`/projects/${pid}/schema`),
      optionalGet(`/projects/${pid}/schema/facts`),
      optionalGet(`/projects/${pid}/entities`),
      optionalGet(`/projects/${pid}/entity-mentions`),
      optionalGet(`/projects/${pid}/time-anchors`),
      optionalGet(`/projects/${pid}/timeline-events`),
      optionalGet(`/projects/${pid}/graph/view`),
    ]);
    const schemaFacts = asArray(schemaRes?.schema?.facts);
    const listedFacts = asArray(factsRes?.facts);
    return {
      facts: listedFacts.length ? listedFacts : schemaFacts,
      entities: asArray(entitiesRes?.entities),
      mentions: asArray(mentionsRes?.mentions),
      anchors: asArray(anchorsRes?.anchors),
      events: asArray(eventsRes?.events),
      externalGraph: graphRes?.external_graph || emptyExternalGraph(),
    };
  }

  function kgContextCount(context) {
    if (!context) return 0;
    return (
      asArray(context.facts).length +
      asArray(context.entities).length +
      asArray(context.mentions).length +
      asArray(context.anchors).length +
      asArray(context.events).length +
      asArray(context.externalGraph?.nodes).length +
      asArray(context.externalGraph?.links).length
    );
  }

  function visibleNodes() {
    const query = graphState.searchText.toLowerCase();
    return graphState.nodes.filter((node) => {
      if (!graphState.activeTypes.has(node.type)) return false;
      const dims = node.dimensions || [];
      if (dims.length && !dims.some((dim) => graphState.activeDimensions.has(dim))) return false;
      if (graphState.favoriteOnly && !isFavorite(node.id)) return false;
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
        const color = normalizeHexColor(meta.color);
        return `
          <label class="graph-view-check-item graph-view-dimension-item" style="--graph-color:${escapeHTML(color)}">
            <input type="checkbox" data-graph-view-dimension="${escapeHTML(dim)}" ${checked} />
            <span class="graph-view-check-dot"></span>
            <span class="graph-view-check-label">${escapeHTML(meta.label)}</span>
            <input
              class="graph-view-color-input"
              type="color"
              value="${escapeHTML(color)}"
              data-graph-view-dimension-color="${escapeHTML(dim)}"
              aria-label="${escapeHTML(meta.label)} 색상"
              title="묶음 색상"
            />
          </label>`;
      })
      .join("");
  }

  function renderExternalProjects() {
    const select = $("graph-view-external-project");
    if (!select) return;
    const currentProjectId = getAppState().projectId;
    const options = (graphState.externalProjects || [])
      .filter((project) => project.project_id && project.project_id !== currentProjectId)
      .map((project) => `<option value="${escapeHTML(project.project_id)}">${escapeHTML(project.name || "이름 없는 프로젝트")}</option>`)
      .join("");
    select.innerHTML = options || '<option value="">불러올 다른 프로젝트가 없습니다</option>';
  }

  function renderExternalSources() {
    const list = $("graph-view-external-source-list");
    if (!list) return;
    const sources = graphState.externalGraph.sources || [];
    if (!sources.length) {
      list.innerHTML = '<div class="graph-view-external-empty">아직 연결된 작품이 없습니다.</div>';
      return;
    }
    list.innerHTML = sources
      .map((source) => {
        const checked = source.enabled !== false ? "checked" : "";
        const color = sourceColor(source);
        const kind = source.source_kind === "nf_project" ? "내 프로젝트" : "작품 정리 파일";
        const linkCount = linkCountForSource(source.source_id);
        const favCount = favoriteCountForSource(source.source_id);
        return `
          <div class="graph-view-source-row" data-source-id="${escapeHTML(source.source_id)}">
            <div class="graph-view-source-row-main">
              <div>
                <strong>${escapeHTML(source.source_label || "가져온 작품")}</strong>
                <small>${escapeHTML(kind)} · 연결 ${linkCount}개 · 즐겨찾기 ${favCount}개</small>
              </div>
              <div class="graph-view-source-actions">
                <input class="graph-view-source-color" type="color" value="${escapeHTML(color)}" data-external-source-color="${escapeHTML(source.source_id)}" title="작품 색상" />
                <button class="graph-view-mini-btn danger" type="button" data-delete-external-source="${escapeHTML(source.source_id)}">삭제</button>
              </div>
            </div>
            <label class="graph-view-check-item">
              <input type="checkbox" data-toggle-external-source="${escapeHTML(source.source_id)}" ${checked} />
              <span class="graph-view-check-dot" style="--graph-color:${escapeHTML(color)}"></span>
              <span>그래프에 표시</span>
            </label>
          </div>`;
      })
      .join("");
  }

  function nodeOptionLabel(node) {
    const source = node.sourceId ? externalSourceById(node.sourceId) : null;
    const prefix = node.origin === "external" ? `가져온 작품:${source?.source_label || "작품"}` : "현재 작품";
    return `${prefix} · ${node.label}`;
  }

  function renderLinkNodeSelects() {
    const sourceSelect = $("graph-view-link-source-select");
    const targetSelect = $("graph-view-link-target-select");
    if (!sourceSelect || !targetSelect) return;
    const nodes = graphState.nodes
      .filter((node) => node.id !== "work:current" && !String(node.id).startsWith("external-source:"))
      .sort((a, b) => nodeOptionLabel(a).localeCompare(nodeOptionLabel(b), "ko"));
    const options = nodes
      .map((node) => `<option value="${escapeHTML(node.id)}">${escapeHTML(nodeOptionLabel(node))}</option>`)
      .join("");
    sourceSelect.innerHTML = options || '<option value="">선택할 요소가 없습니다</option>';
    targetSelect.innerHTML = options || '<option value="">선택할 요소가 없습니다</option>';
    if (graphState.selectedNodeId && graphState.nodeById.has(graphState.selectedNodeId)) {
      if (isExternalNodeId(graphState.selectedNodeId)) targetSelect.value = graphState.selectedNodeId;
      else sourceSelect.value = graphState.selectedNodeId;
    }
  }

  function renderExternalLinks() {
    const list = $("graph-view-link-list");
    if (!list) return;
    const links = graphState.externalGraph.links || [];
    if (!links.length) {
      list.innerHTML = '<div class="graph-view-external-empty">아직 직접 추가한 관계가 없습니다.</div>';
      return;
    }
    list.innerHTML = links
      .filter((link) => !link.status || link.status === "ACTIVE")
      .map((link) => {
        const sourceNode = graphState.nodeById.get(link.src_node_ref);
        const targetNode = graphState.nodeById.get(link.dst_node_ref);
        return `
          <div class="graph-view-link-row" data-link-id="${escapeHTML(link.link_id)}">
            <div class="graph-view-link-row-main">
              <div>
                <strong>${escapeHTML(link.label || relationLabel(link.relation_type))}</strong>
                <small>${escapeHTML(sourceNode?.label || link.src_node_ref)} → ${escapeHTML(targetNode?.label || link.dst_node_ref)}</small>
              </div>
              <div class="graph-view-link-actions">
                <button class="graph-view-mini-btn danger" type="button" data-delete-external-link="${escapeHTML(link.link_id)}">삭제</button>
              </div>
            </div>
          </div>`;
      })
      .join("");
  }

  function renderExternalDrawer() {
    const drawer = $("graph-view-external-drawer");
    if (drawer) {
      drawer.classList.toggle("is-open", graphState.externalDrawerOpen);
      drawer.setAttribute("aria-hidden", graphState.externalDrawerOpen ? "false" : "true");
    }
    renderExternalProjects();
    renderExternalSources();
    renderLinkNodeSelects();
    renderExternalLinks();
    updateModeButtons();
  }

  async function loadExternalProjectChoices() {
    if (typeof window.api !== "function" || !getAppState().projectId) return;
    try {
      const res = await window.api("/projects");
      graphState.externalProjects = Array.isArray(res?.projects) ? res.projects : [];
      renderExternalProjects();
    } catch (_error) {
      graphState.externalProjects = [];
      renderExternalProjects();
    }
  }

  async function refreshExternalGraphOnly() {
    const projectId = getAppState().projectId;
    if (!projectId || typeof window.api !== "function") return;
    const pid = encodeURIComponent(projectId);
    const res = await window.api(`/projects/${pid}/graph/view`);
    graphState.externalGraph = res?.external_graph || emptyExternalGraph();
    syncFavoriteSet();
    setGraphData(buildGraphData({ externalGraph: graphState.externalGraph }));
    refreshGraphView({ force: true });
  }

  async function addExternalProjectSource() {
    const projectId = getAppState().projectId;
    const select = $("graph-view-external-project");
    if (!projectId || !select?.value || typeof window.api !== "function") return;
    const pid = encodeURIComponent(projectId);
    await window.api(`/projects/${pid}/graph/external-sources`, "POST", {
      source_kind: "nf_project",
      linked_project_id: select.value,
      color: "#14b8a6",
    });
    await refreshGraphView({ force: true });
  }

  async function importStoryPackageFile() {
    const projectId = getAppState().projectId;
    const input = $("graph-view-dataset-files");
    if (!projectId || !input?.files?.length || typeof window.api !== "function") return;
    const file = input.files[0];
    const password = safeText($("graph-view-story-password")?.value);
    const packagePayload = await openStoryPackage(await file.text(), password);
    const label = safeText($("graph-view-dataset-label")?.value, packagePayload.display_name || "가져온 작품");
    const pid = encodeURIComponent(projectId);
    await window.api(`/projects/${pid}/graph/story-package/import`, "POST", {
      source_label: label,
      package: packagePayload,
      color: "#8b5cf6",
    });
    input.value = "";
    if ($("graph-view-story-password")) $("graph-view-story-password").value = "";
    await refreshGraphView({ force: true });
  }

  async function exportCurrentStoryPackage() {
    const projectId = getAppState().projectId;
    if (!projectId || typeof window.api !== "function") return;
    const pid = encodeURIComponent(projectId);
    const res = await window.api(`/projects/${pid}/graph/story-package`);
    const password = safeText($("graph-view-story-password")?.value);
    const protectedPackage = await protectStoryPackage(res.package, password);
    const filename = safeText(res.filename, "story.nfstory").replace(/\.[^.]+$/, "") + ".nfstory";
    downloadJSONFile(filename, protectedPackage);
    setSourceStatus(password ? "비밀번호로 잠근 작품 정리 파일을 저장했습니다." : "난독화된 작품 정리 파일을 저장했습니다.");
  }

  async function updateExternalSource(sourceId, patch) {
    const projectId = getAppState().projectId;
    if (!projectId || !sourceId || typeof window.api !== "function") return;
    const pid = encodeURIComponent(projectId);
    await window.api(`/projects/${pid}/graph/external-sources/${encodeURIComponent(sourceId)}`, "PATCH", patch);
    await refreshGraphView({ force: true });
  }

  async function deleteExternalSource(sourceId) {
    const projectId = getAppState().projectId;
    if (!projectId || !sourceId || typeof window.api !== "function") return;
    const pid = encodeURIComponent(projectId);
    await window.api(`/projects/${pid}/graph/external-sources/${encodeURIComponent(sourceId)}`, "DELETE");
    await refreshGraphView({ force: true });
  }

  function selectedRelationPayload() {
    const relationType = safeText($("graph-view-relation-type")?.value, "SAME_ENTITY");
    const customLabel = safeText($("graph-view-relation-custom-label")?.value);
    return {
      relation_type: RELATION_LABELS[relationType] ? relationType : "CUSTOM",
      label: relationType === "CUSTOM" && customLabel ? customLabel : relationLabel(relationType),
      confidence: 0.75,
    };
  }

  async function createExternalLink(srcNodeRef, dstNodeRef) {
    const projectId = getAppState().projectId;
    if (!projectId || !srcNodeRef || !dstNodeRef || srcNodeRef === dstNodeRef || typeof window.api !== "function") return;
    if (isExternalNodeId(srcNodeRef) === isExternalNodeId(dstNodeRef)) {
      setSourceStatus("현재 작품 요소와 가져온 작품 요소를 하나씩 연결해야 합니다.");
      return;
    }
    const pid = encodeURIComponent(projectId);
    await window.api(`/projects/${pid}/graph/external-links`, "POST", {
      src_node_ref: srcNodeRef,
      dst_node_ref: dstNodeRef,
      ...selectedRelationPayload(),
    });
    await refreshGraphView({ force: true });
  }

  async function createExternalLinkFromSelects() {
    const source = $("graph-view-link-source-select")?.value;
    const target = $("graph-view-link-target-select")?.value;
    await createExternalLink(source, target);
  }

  async function deleteExternalLink(linkId) {
    const projectId = getAppState().projectId;
    if (!projectId || !linkId || typeof window.api !== "function") return;
    const pid = encodeURIComponent(projectId);
    await window.api(`/projects/${pid}/graph/external-links/${encodeURIComponent(linkId)}`, "DELETE");
    await refreshGraphView({ force: true });
  }

  async function toggleFavoriteForSelected() {
    const projectId = getAppState().projectId;
    const node = graphState.selectedNodeId ? graphState.nodeById.get(graphState.selectedNodeId) : null;
    if (!projectId || !node || typeof window.api !== "function") return;
    const pid = encodeURIComponent(projectId);
    if (isFavorite(node.id)) {
      await window.api(`/projects/${pid}/graph/favorites`, "DELETE", { node_ref: node.id });
    } else {
      await window.api(`/projects/${pid}/graph/favorites`, "POST", {
        node_ref: node.id,
        node_kind: node.type,
        source_id: node.sourceId || null,
        label_snapshot: node.label,
      });
    }
    const res = await window.api(`/projects/${pid}/graph/view`);
    graphState.externalGraph = res?.external_graph || emptyExternalGraph();
    syncFavoriteSet();
    assignTargets();
    updateStats();
    renderExternalDrawer();
    renderInspector();
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
    const favoriteFilter = $("graph-view-favorite-filter");
    if (favoriteFilter) {
      favoriteFilter.classList.toggle("active", graphState.favoriteOnly);
      favoriteFilter.textContent = graphState.favoriteOnly ? "전체 보기" : "즐겨찾기만 보기";
    }
    const cloudToggle = $("graph-view-cloud-toggle");
    if (cloudToggle) {
      cloudToggle.classList.toggle("active", graphState.showClusterClouds);
      cloudToggle.textContent = graphState.showClusterClouds ? "구름 숨기기" : "구름 표시";
    }
    const externalToggle = $("graph-view-external-toggle");
    if (externalToggle) externalToggle.classList.toggle("active", graphState.externalDrawerOpen);
    const linkToggle = $("graph-view-link-mode-toggle");
    if (linkToggle) {
      linkToggle.classList.toggle("active", graphState.linkMode);
      linkToggle.setAttribute("aria-pressed", graphState.linkMode ? "true" : "false");
    }
    const rotationToggle = $("graph-view-rotation-toggle");
    if (rotationToggle) {
      const is3d = graphState.mode === "3d";
      rotationToggle.disabled = !is3d;
      rotationToggle.classList.toggle("active", is3d && graphState.autoRotate);
      rotationToggle.textContent = is3d
        ? graphState.autoRotate
          ? "회전 정지"
          : "회전 시작"
        : "3D 회전";
      rotationToggle.title = is3d
        ? "입체 그래프 자동 회전을 켜거나 끕니다."
        : "입체 보기에서 사용할 수 있습니다.";
    }
    const help = $("graph-view-help");
    if (help) {
      help.textContent = graphState.linkMode
        ? "연결 만들기 모드입니다. 현재 작품의 요소와 가져온 작품의 요소를 드래그로 이어보세요."
        : graphState.mode === "3d"
          ? "요소는 드래그로 잠시 당겨볼 수 있습니다. 빈 공간 드래그는 입체 회전, Shift+드래그는 이동입니다."
          : "요소는 드래그로 잠시 당겨볼 수 있습니다. 빈 공간 드래그는 이동, 휠은 확대입니다.";
    }
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
    renderExternalDrawer();
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
    graphState.externalGraph = emptyExternalGraph();
    syncFavoriteSet();
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
      graphState.externalGraph = context.externalGraph || emptyExternalGraph();
      syncFavoriteSet();
      setGraphData(buildGraphData(count ? context : null));
      const externalCount = asArray(graphState.externalGraph.sources).filter((source) => source.enabled !== false).length;
      if (count) {
        setSourceStatus(
          externalCount
            ? `문서와 설정에 연결된 작품 ${externalCount}개를 함께 보여줍니다.`
            : "문서, 설정, 인물/장소, 시간 정보를 함께 보여줍니다.",
        );
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

  function rebalance3DTargets(ids) {
    const targets = graphState.nodes.filter((node) => ids.has(node.id));
    const workNode = targets.find((node) => node.id === "work:current");
    const graphNodes = targets.filter((node) => node.id !== "work:current");
    if (!graphNodes.length) {
      if (workNode) {
        workNode.tx = 0;
        workNode.ty = 0;
        workNode.tz = 0;
      }
      return;
    }

    const centroid = graphNodes.reduce(
      (acc, node) => {
        acc.x += node.tx;
        acc.y += node.ty;
        acc.z += node.tz || 0;
        return acc;
      },
      { x: 0, y: 0, z: 0 },
    );
    centroid.x /= graphNodes.length;
    centroid.y /= graphNodes.length;
    centroid.z /= graphNodes.length;

    graphNodes.forEach((node) => {
      node.tx -= centroid.x;
      node.ty -= centroid.y;
      node.tz = (node.tz || 0) - centroid.z;
    });

    const bounds = graphNodes.reduce(
      (acc, node) => ({
        minX: Math.min(acc.minX, node.tx),
        maxX: Math.max(acc.maxX, node.tx),
        minY: Math.min(acc.minY, node.ty),
        maxY: Math.max(acc.maxY, node.ty),
        minZ: Math.min(acc.minZ, node.tz || 0),
        maxZ: Math.max(acc.maxZ, node.tz || 0),
      }),
      { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity, minZ: Infinity, maxZ: -Infinity },
    );
    const spanX = Math.max(1, bounds.maxX - bounds.minX);
    const spanY = Math.max(1, bounds.maxY - bounds.minY);
    const spanZ = Math.max(1, bounds.maxZ - bounds.minZ);
    const maxSpanX = clamp(canvasWidth * 0.48, 220, 420);
    const maxSpanY = clamp(canvasHeight * 0.5, 170, 300);
    const maxSpanZ = 340;
    const scale = Math.min(1, maxSpanX / spanX, maxSpanY / spanY, maxSpanZ / spanZ);
    const limitX = maxSpanX / 2;
    const limitY = maxSpanY / 2;
    const limitZ = maxSpanZ / 2;

    graphNodes.forEach((node) => {
      node.tx = clamp(node.tx * scale, -limitX, limitX);
      node.ty = clamp(node.ty * scale, -limitY, limitY);
      node.tz = clamp((node.tz || 0) * scale, -limitZ, limitZ);
    });

    if (workNode) {
      workNode.tx = -clamp(canvasWidth * 0.055, 38, 72);
      workNode.ty = clamp(canvasHeight * 0.1, 48, 82);
      workNode.tz = 0;
    }
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
    if (graphState.mode === "3d") rebalance3DTargets(ids);
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

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function projectNode(node) {
    if (graphState.mode === "3d") {
      const yAngle = graphState.rotation;
      const xAngle = graphState.rotationX;
      const cosY = Math.cos(yAngle);
      const sinY = Math.sin(yAngle);
      const cosX = Math.cos(xAngle);
      const sinX = Math.sin(xAngle);
      const rotatedX = node.x * cosY - node.z * sinY;
      const rotatedZ = node.x * sinY + node.z * cosY;
      const rotatedY = node.y * cosX - rotatedZ * sinX;
      const depthZ = node.y * sinX + rotatedZ * cosX;
      const perspective = 560 / (560 + depthZ);
      node.screenX = canvasWidth / 2 + rotatedX * perspective * graphState.zoom + graphState.panX;
      node.screenY = canvasHeight / 2 + rotatedY * perspective * graphState.zoom + graphState.panY;
      node.screenRadius = Math.max(5, (node.radius + Math.min(8, node.weight)) * perspective * graphState.zoom);
      node.alpha = Math.max(0.28, Math.min(1, 0.74 + depthZ / 520));
      return;
    }
    node.screenX = canvasWidth / 2 + (node.x - canvasWidth / 2) * graphState.zoom + graphState.panX;
    node.screenY = canvasHeight / 2 + (node.y - canvasHeight / 2) * graphState.zoom + graphState.panY;
    node.screenRadius = Math.max(5, (node.radius + Math.min(7, node.weight * 0.55)) * graphState.zoom);
    node.alpha = 1;
  }

  function updatePhysics() {
    if (graphState.mode === "3d" && graphState.autoRotate) {
      graphState.rotation += graphState.clusterEnabled ? 0.0025 : 0.0015;
    }
    const ids = visibleNodeSet();
    graphState.nodes.forEach((node) => {
      if (!ids.has(node.id)) return;
      const isPulled =
        graphState.pointer.dragging &&
        graphState.pointer.mode === "node" &&
        graphState.pointer.nodeId === node.id;
      const returnSpeed = isPulled ? 0.026 : graphState.mode === "3d" && node.id === "work:current" ? 0.22 : 0.08;
      node.x = lerp(node.x, node.tx, returnSpeed);
      node.y = lerp(node.y, node.ty, returnSpeed);
      node.z = lerp(node.z, node.tz, returnSpeed);
      if (node.elasticHint) node.elasticHint *= isPulled ? 0.99 : 0.91;
      projectNode(node);
    });
  }

  function drawClusterHints(ids) {
    if (!graphState.showClusterClouds || !(graphState.clusterEnabled || graphState.mode === "nd")) return;
    const dimMembers = new Map();
    graphState.nodes.forEach((node) => {
      if (!ids.has(node.id)) return;
      (node.dimensions || []).forEach((dim) => {
        if (!graphState.activeDimensions.has(dim)) return;
        if (!dimMembers.has(dim)) dimMembers.set(dim, []);
        if (node.id !== "work:current") dimMembers.get(dim).push(node);
      });
    });
    ctx.save();
    dimMembers.forEach((members, dim) => {
      const meta = DIMENSION_META[dim];
      if (!meta || !members.length) return;
      drawClusterCloud(dim, members, meta);
    });
    ctx.restore();
  }

  function drawClusterCloud(dim, members, meta) {
    const points = members
      .filter((node) => Number.isFinite(node.screenX) && Number.isFinite(node.screenY))
      .map((node) => ({
        x: node.screenX,
        y: node.screenY,
        r: Math.max(14, node.screenRadius || node.radius || 12),
      }));
    if (!points.length) return;

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    let totalX = 0;
    let totalY = 0;
    points.forEach((point) => {
      minX = Math.min(minX, point.x - point.r);
      maxX = Math.max(maxX, point.x + point.r);
      minY = Math.min(minY, point.y - point.r);
      maxY = Math.max(maxY, point.y + point.r);
      totalX += point.x;
      totalY += point.y;
    });

    const centerX = totalX / points.length;
    const centerY = totalY / points.length;
    const padding = clamp(44 + graphState.clusterDistance * 0.22 + points.length * 1.4, 54, 104);
    const radiusX = Math.max(70, (maxX - minX) / 2 + padding);
    const radiusY = Math.max(52, (maxY - minY) / 2 + padding * 0.72);
    const color = normalizeHexColor(meta.color);
    const alphaScale = graphState.mode === "3d" ? 0.72 : 1;
    const seed = (hashText(dim) % 360) * (Math.PI / 180);

    points.forEach((point) => {
      const puffRadius = Math.max(42, point.r * 3.6 + 24);
      const puff = ctx.createRadialGradient(point.x, point.y, 0, point.x, point.y, puffRadius);
      puff.addColorStop(0, colorWithAlpha(color, 0.075 * alphaScale));
      puff.addColorStop(0.58, colorWithAlpha(color, 0.038 * alphaScale));
      puff.addColorStop(1, colorWithAlpha(color, 0));
      ctx.beginPath();
      ctx.fillStyle = puff;
      ctx.arc(point.x, point.y, puffRadius, 0, Math.PI * 2);
      ctx.fill();
    });

    drawCloudPath(centerX, centerY, radiusX, radiusY, seed);
    const fill = ctx.createRadialGradient(centerX, centerY, Math.min(radiusX, radiusY) * 0.08, centerX, centerY, Math.max(radiusX, radiusY) * 1.12);
    fill.addColorStop(0, colorWithAlpha(color, 0.105 * alphaScale));
    fill.addColorStop(0.62, colorWithAlpha(color, 0.045 * alphaScale));
    fill.addColorStop(1, colorWithAlpha(color, 0));
    ctx.fillStyle = fill;
    ctx.fill();

    drawCloudPath(centerX, centerY, radiusX, radiusY, seed);
    const edge = ctx.createLinearGradient(centerX - radiusX, centerY - radiusY, centerX + radiusX, centerY + radiusY);
    edge.addColorStop(0, colorWithAlpha(color, 0.06 * alphaScale));
    edge.addColorStop(0.45, colorWithAlpha(color, 0.26 * alphaScale));
    edge.addColorStop(1, colorWithAlpha(color, 0.02 * alphaScale));
    ctx.strokeStyle = edge;
    ctx.lineWidth = 1.2;
    ctx.shadowColor = colorWithAlpha(color, 0.12);
    ctx.shadowBlur = 12;
    ctx.stroke();
    ctx.shadowBlur = 0;

    const labelX = clamp(centerX - radiusX + 16, 12, Math.max(12, canvasWidth - 120));
    const labelY = clamp(centerY - radiusY + 22, 22, Math.max(22, canvasHeight - 12));
    ctx.fillStyle = colorWithAlpha(color, 0.78);
    ctx.font = "700 12px 'Noto Sans KR', sans-serif";
    ctx.fillText(meta.label, labelX, labelY);
  }

  function drawCloudPath(centerX, centerY, radiusX, radiusY, seed) {
    const points = [];
    const steps = 34;
    for (let index = 0; index < steps; index += 1) {
      const angle = (index / steps) * Math.PI * 2;
      const wobble =
        1 +
        Math.sin(angle * 3 + seed) * 0.055 +
        Math.sin(angle * 5 - seed * 0.7) * 0.035 +
        Math.cos(angle * 2 + seed * 1.3) * 0.025;
      points.push({
        x: centerX + Math.cos(angle) * radiusX * wobble,
        y: centerY + Math.sin(angle) * radiusY * wobble,
      });
    }
    const first = points[0];
    const last = points[points.length - 1];
    ctx.beginPath();
    ctx.moveTo((last.x + first.x) / 2, (last.y + first.y) / 2);
    for (let index = 0; index < points.length; index += 1) {
      const current = points[index];
      const next = points[(index + 1) % points.length];
      ctx.quadraticCurveTo(current.x, current.y, (current.x + next.x) / 2, (current.y + next.y) / 2);
    }
    ctx.closePath();
  }

  function drawEdge(edge) {
    const source = graphState.nodeById.get(edge.source);
    const target = graphState.nodeById.get(edge.target);
    if (!source || !target) return;
    const selected = graphState.selectedNodeId && (edge.source === graphState.selectedNodeId || edge.target === graphState.selectedNodeId);
    const manual = edge.origin === "manual-external-link";
    const alpha = selected ? 0.85 : manual ? 0.62 : 0.24 + Math.min(0.22, edge.weight * 0.035);
    ctx.save();
    ctx.globalAlpha = alpha * Math.min(source.alpha, target.alpha);
    ctx.strokeStyle = selected ? "#0f766e" : edge.color;
    ctx.lineWidth = selected ? 2.2 : manual ? 2.4 : Math.max(1, Math.min(3, edge.weight * 0.55));
    if (edge.dashed) ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(source.screenX, source.screenY);
    ctx.lineTo(target.screenX, target.screenY);
    ctx.stroke();
    ctx.restore();
  }

  function projectGraphPoint(x, y, z) {
    if (graphState.mode === "3d") {
      const yAngle = graphState.rotation;
      const xAngle = graphState.rotationX;
      const cosY = Math.cos(yAngle);
      const sinY = Math.sin(yAngle);
      const cosX = Math.cos(xAngle);
      const sinX = Math.sin(xAngle);
      const rotatedX = x * cosY - z * sinY;
      const rotatedZ = x * sinY + z * cosY;
      const rotatedY = y * cosX - rotatedZ * sinX;
      const depthZ = y * sinX + rotatedZ * cosX;
      const perspective = 560 / (560 + depthZ);
      return {
        x: canvasWidth / 2 + rotatedX * perspective * graphState.zoom + graphState.panX,
        y: canvasHeight / 2 + rotatedY * perspective * graphState.zoom + graphState.panY,
      };
    }
    return {
      x: canvasWidth / 2 + (x - canvasWidth / 2) * graphState.zoom + graphState.panX,
      y: canvasHeight / 2 + (y - canvasHeight / 2) * graphState.zoom + graphState.panY,
    };
  }

  function drawElasticTethers(ids) {
    visibleNodes().forEach((node) => {
      if (!ids.has(node.id) || !node.elasticHint || node.elasticHint < 0.035) return;
      const target = projectGraphPoint(node.tx, node.ty, node.tz || 0);
      const dx = node.screenX - target.x;
      const dy = node.screenY - target.y;
      const distance = Math.sqrt(dx * dx + dy * dy);
      if (distance < 8) return;

      const alpha = Math.min(0.7, Math.max(0.16, distance / 180)) * Math.min(1, node.elasticHint);
      const midX = (target.x + node.screenX) / 2;
      const midY = (target.y + node.screenY) / 2;
      const curveX = midX - dy * 0.08;
      const curveY = midY + dx * 0.08;
      const gradient = ctx.createLinearGradient(target.x, target.y, node.screenX, node.screenY);
      gradient.addColorStop(0, colorWithAlpha(node.color, 0));
      gradient.addColorStop(0.42, colorWithAlpha(node.color, alpha * 0.9));
      gradient.addColorStop(1, colorWithAlpha(node.color, alpha * 0.18));

      ctx.save();
      ctx.setLineDash([5, 6]);
      ctx.lineCap = "round";
      ctx.lineWidth = Math.min(3.4, 1.1 + distance / 95);
      ctx.strokeStyle = gradient;
      ctx.beginPath();
      ctx.moveTo(target.x, target.y);
      ctx.quadraticCurveTo(curveX, curveY, node.screenX, node.screenY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = alpha * 0.42;
      ctx.fillStyle = node.color;
      ctx.beginPath();
      ctx.arc(target.x, target.y, 3.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    });
  }

  function drawLinkPreview(ids) {
    const draft = graphState.linkDraft;
    if (!graphState.linkMode || !draft?.sourceNodeId) return;
    const source = graphState.nodeById.get(draft.sourceNodeId);
    if (!source || !ids.has(source.id)) return;
    const target = draft.targetNodeId ? graphState.nodeById.get(draft.targetNodeId) : null;
    const endX = target ? target.screenX : draft.pointerX;
    const endY = target ? target.screenY : draft.pointerY;
    if (!Number.isFinite(endX) || !Number.isFinite(endY)) return;
    const color = target ? "#0f766e" : source.color;
    ctx.save();
    ctx.globalAlpha = target ? 0.78 : 0.42;
    ctx.strokeStyle = colorWithAlpha(color, 0.92);
    ctx.lineWidth = target ? 2.6 : 2;
    ctx.setLineDash(target ? [] : [6, 6]);
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(source.screenX, source.screenY);
    ctx.lineTo(endX, endY);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = colorWithAlpha(color, 0.86);
    ctx.beginPath();
    ctx.arc(endX, endY, target ? 5 : 3.5, 0, Math.PI * 2);
    ctx.fill();
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

    if (graphState.linkMode && node.id !== "work:current" && !String(node.id).startsWith("external-source:")) {
      ctx.beginPath();
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = selected || hovered ? "#0f766e" : colorWithAlpha(node.color, 0.82);
      ctx.lineWidth = 1.6;
      ctx.arc(node.screenX + radius * 0.68, node.screenY - radius * 0.68, 5, 0, Math.PI * 2);
      ctx.fill();
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
    drawElasticTethers(ids);
    drawLinkPreview(ids);
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
      box.innerHTML = '<div class="graph-view-inspector-empty">그래프에서 인물, 장소, 사건, 본문 위치를 클릭해보세요.</div>';
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
    const externalSource = node.sourceId ? externalSourceById(node.sourceId) : null;
    const favoriteActive = isFavorite(node.id);
    const sourceKind = node.origin === "external" ? `가져온 작품 · ${externalSource?.source_label || "작품"}` : node.sourceKind || "문서";
    const linkedDocText = node.origin === "external" ? "가져온 작품의 요소" : docTitle || "연결된 본문 없음";
    box.innerHTML = `
      <div class="graph-view-inspector-card">
        <div class="graph-view-inspector-title-row">
          <div class="graph-view-inspector-badges">
            <span class="graph-view-pill" style="color:${typeMeta.color}; border-color:${typeMeta.color}55; background:${typeMeta.color}12">${escapeHTML(typeMeta.label)}</span>
            ${dimensionBadges}
          </div>
          <button
            id="graph-view-favorite-toggle"
            class="graph-view-favorite-btn ${favoriteActive ? "active" : ""}"
            type="button"
            aria-pressed="${favoriteActive ? "true" : "false"}"
            title="${favoriteActive ? "즐겨찾기 해제" : "즐겨찾기"}"
          >${favoriteActive ? "★" : "☆"}</button>
        </div>
        <h3>${escapeHTML(node.label)}</h3>
        <p>${escapeHTML(node.description || node.subtitle || "작품 안에서 연결된 요소입니다.")}</p>
        <div class="graph-view-detail-list">
          <div class="graph-view-detail-row">
            <span>나온 곳</span>
            <strong>${escapeHTML(sourceKind)}</strong>
          </div>
          <div class="graph-view-detail-row">
            <span>연결된 본문</span>
            <strong>${escapeHTML(linkedDocText)}</strong>
          </div>
          <div class="graph-view-detail-row">
            <span>메모</span>
            <strong>${escapeHTML(status ? `상태: ${status}` : node.subtitle || "가까운 선을 따라 관련 요소를 확인하세요.")}</strong>
          </div>
        </div>
      </div>`;
    $("graph-view-favorite-toggle")?.addEventListener("click", () => {
      toggleFavoriteForSelected().catch((error) => {
        console.error(error);
        setSourceStatus("즐겨찾기를 저장하지 못했습니다.");
      });
    });
    if (primary) {
      primary.disabled = !node.docId || node.origin === "external";
      primary.textContent = node.origin === "external" ? "가져온 작품의 요소" : node.docId ? "본문으로 이동" : "연결된 본문 없음";
    }
    if (secondary) {
      secondary.disabled = node.origin === "external" || !(node.docId || node.type === "Character" || node.type === "Place" || node.type === "Fact");
      secondary.textContent = node.origin === "external" ? "현재 작품 위치 없음" : node.docId ? "문서 목록에서 보기" : "설정 목록에서 보기";
    }
    renderLinkNodeSelects();
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
    if (!node || node.origin === "external") return;
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
    graphState.rotationX = -0.12;
    assignTargets();
    updateModeButtons();
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
    loadExternalProjectChoices();
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
    graphState.externalDrawerOpen = false;
    graphState.linkMode = false;
    graphState.linkDraft = null;
    panel.classList.remove("is-open");
    panel.inert = true;
    panel.setAttribute("aria-hidden", "true");
    $("graph-view-open-btn")?.classList.remove("active");
    $("graph-view-sidebar-btn")?.classList.remove("active");
    renderExternalDrawer();
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
    loadDimensionColors();
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
    $("graph-view-external-toggle")?.addEventListener("click", () => {
      graphState.externalDrawerOpen = !graphState.externalDrawerOpen;
      if (graphState.externalDrawerOpen) loadExternalProjectChoices();
      renderExternalDrawer();
    });
    $("graph-view-external-close")?.addEventListener("click", () => {
      graphState.externalDrawerOpen = false;
      graphState.linkMode = false;
      graphState.linkDraft = null;
      renderExternalDrawer();
    });
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
    $("graph-view-favorite-filter")?.addEventListener("click", () => {
      graphState.favoriteOnly = !graphState.favoriteOnly;
      assignTargets();
      updateStats();
      updateModeButtons();
    });
    $("graph-view-cloud-toggle")?.addEventListener("click", () => {
      graphState.showClusterClouds = !graphState.showClusterClouds;
      updateModeButtons();
    });
    $("graph-view-rotation-toggle")?.addEventListener("click", () => {
      if (graphState.mode !== "3d") return;
      graphState.autoRotate = !graphState.autoRotate;
      updateModeButtons();
    });
    $("graph-view-add-project-source")?.addEventListener("click", () => {
      addExternalProjectSource().catch((error) => {
        console.error(error);
        setSourceStatus("선택한 프로젝트를 불러오지 못했습니다.");
      });
    });
    $("graph-view-import-dataset")?.addEventListener("click", () => {
      importStoryPackageFile().catch((error) => {
        console.error(error);
        setSourceStatus(error?.message || "작품 정리 파일을 불러오지 못했습니다.");
      });
    });
    $("graph-view-export-story")?.addEventListener("click", () => {
      exportCurrentStoryPackage().catch((error) => {
        console.error(error);
        setSourceStatus("작품 정리 파일을 저장하지 못했습니다.");
      });
    });
    $("graph-view-link-mode-toggle")?.addEventListener("click", () => {
      graphState.linkMode = !graphState.linkMode;
      graphState.linkDraft = null;
      renderExternalDrawer();
    });
    $("graph-view-create-link")?.addEventListener("click", () => {
      createExternalLinkFromSelects().catch((error) => {
        console.error(error);
        setSourceStatus("관계를 추가하지 못했습니다.");
      });
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

    $("graph-view-dimension-list")?.addEventListener("input", (event) => {
      const dim = event.target?.dataset?.graphViewDimensionColor;
      const meta = dim ? DIMENSION_META[dim] : null;
      if (!meta) return;
      const color = normalizeHexColor(event.target.value, meta.color);
      meta.color = color;
      event.target.value = color;
      event.target.closest(".graph-view-check-item")?.style.setProperty("--graph-color", color);
      saveDimensionColors();
    });

    $("graph-view-external-drawer")?.addEventListener("change", (event) => {
      const sourceId = event.target?.dataset?.toggleExternalSource;
      if (sourceId) {
        updateExternalSource(sourceId, { enabled: Boolean(event.target.checked) }).catch((error) => {
          console.error(error);
          setSourceStatus("연결된 작품 표시 상태를 바꾸지 못했습니다.");
        });
      }
    });

    $("graph-view-external-drawer")?.addEventListener("input", (event) => {
      const sourceId = event.target?.dataset?.externalSourceColor;
      if (sourceId) {
        const color = normalizeHexColor(event.target.value, "#14b8a6");
        event.target.value = color;
        updateExternalSource(sourceId, { color }).catch((error) => {
          console.error(error);
          setSourceStatus("연결된 작품 색상을 저장하지 못했습니다.");
        });
      }
    });

    $("graph-view-external-drawer")?.addEventListener("click", (event) => {
      const deleteSource = event.target?.dataset?.deleteExternalSource;
      if (deleteSource) {
        deleteExternalSource(deleteSource).catch((error) => {
          console.error(error);
          setSourceStatus("연결된 작품을 삭제하지 못했습니다.");
        });
        return;
      }
      const deleteLink = event.target?.dataset?.deleteExternalLink;
      if (deleteLink) {
        deleteExternalLink(deleteLink).catch((error) => {
          console.error(error);
          setSourceStatus("관계를 삭제하지 못했습니다.");
        });
      }
    });

    canvas.addEventListener("pointerdown", (event) => {
      const pos = pointerPosition(event);
      const hit = hitTest(pos.x, pos.y);
      canvas.setPointerCapture(event.pointerId);
      graphState.pointer.dragging = true;
      graphState.pointer.moved = false;
      graphState.pointer.lastX = event.clientX;
      graphState.pointer.lastY = event.clientY;
      graphState.pointer.nodeId = hit ? hit.id : null;
      if (hit && graphState.linkMode && hit.id !== "work:current" && !String(hit.id).startsWith("external-source:")) {
        graphState.pointer.mode = "link";
        graphState.hoverNodeId = hit.id;
        graphState.linkDraft = {
          sourceNodeId: hit.id,
          targetNodeId: null,
          pointerX: pos.x,
          pointerY: pos.y,
        };
      } else if (hit) {
        graphState.pointer.mode = "node";
        graphState.hoverNodeId = hit.id;
        hit.elasticHint = 1;
        selectNode(hit.id);
      } else {
        graphState.pointer.mode =
          graphState.mode === "3d" && !event.shiftKey ? "rotate" : "pan";
      }
      canvas.classList.add("dragging");
      canvas.classList.toggle("rotating", graphState.pointer.mode === "rotate");
      canvas.classList.toggle("node-dragging", graphState.pointer.mode === "node");
      canvas.classList.toggle("linking", graphState.pointer.mode === "link");
    });

    canvas.addEventListener("pointermove", (event) => {
      const pos = pointerPosition(event);
      if (graphState.pointer.dragging) {
        const dx = event.clientX - graphState.pointer.lastX;
        const dy = event.clientY - graphState.pointer.lastY;
        if (Math.abs(dx) + Math.abs(dy) > 2) graphState.pointer.moved = true;
        if (graphState.pointer.mode === "link") {
          const hit = hitTest(pos.x, pos.y);
          graphState.hoverNodeId = hit ? hit.id : null;
          if (graphState.linkDraft) {
            graphState.linkDraft.pointerX = pos.x;
            graphState.linkDraft.pointerY = pos.y;
            graphState.linkDraft.targetNodeId =
              hit && hit.id !== graphState.linkDraft.sourceNodeId && hit.id !== "work:current" && !String(hit.id).startsWith("external-source:")
                ? hit.id
                : null;
          }
        } else if (graphState.pointer.mode === "node") {
          const node = graphState.nodeById.get(graphState.pointer.nodeId);
          if (node) {
            const scale = Math.max(0.35, graphState.zoom);
            if (graphState.mode === "3d") {
              const cosY = Math.cos(graphState.rotation);
              const sinY = Math.sin(graphState.rotation);
              node.x += (dx * cosY) / scale;
              node.y += dy / scale;
              node.z -= (dx * sinY * 0.75) / scale;
            } else {
              node.x += dx / scale;
              node.y += dy / scale;
            }
            node.elasticHint = 1;
            graphState.hoverNodeId = node.id;
          }
        } else if (graphState.pointer.mode === "rotate") {
          graphState.rotation += dx * 0.006;
          graphState.rotationX = clamp(graphState.rotationX - dy * 0.0045, -0.78, 0.78);
          if (Math.abs(dx) + Math.abs(dy) > 2) {
            graphState.autoRotate = false;
            updateModeButtons();
          }
        } else {
          graphState.panX += dx;
          graphState.panY += dy;
        }
        graphState.pointer.lastX = event.clientX;
        graphState.pointer.lastY = event.clientY;
        return;
      }
      const hit = hitTest(pos.x, pos.y);
      graphState.hoverNodeId = hit ? hit.id : null;
      canvas.classList.toggle("node-hover", Boolean(hit));
    });

    canvas.addEventListener("pointerup", (event) => {
      const pos = pointerPosition(event);
      const draggedNodeId = graphState.pointer.nodeId;
      const draggedNode = draggedNodeId ? graphState.nodeById.get(draggedNodeId) : null;
      if (draggedNode) draggedNode.elasticHint = Math.max(draggedNode.elasticHint || 0, 0.95);
      const linkDraft = graphState.pointer.mode === "link" ? graphState.linkDraft : null;
      graphState.pointer.dragging = false;
      graphState.pointer.mode = "pan";
      graphState.pointer.nodeId = null;
      canvas.classList.remove("dragging");
      canvas.classList.remove("rotating");
      canvas.classList.remove("node-dragging");
      canvas.classList.remove("linking");
      if (linkDraft?.sourceNodeId && linkDraft?.targetNodeId) {
        createExternalLink(linkDraft.sourceNodeId, linkDraft.targetNodeId).catch((error) => {
          console.error(error);
          setSourceStatus("관계를 추가하지 못했습니다.");
        });
      } else if (!graphState.pointer.moved) {
        const hit = hitTest(pos.x, pos.y);
        selectNode(draggedNodeId || (hit ? hit.id : null));
      }
      graphState.linkDraft = null;
    });

    canvas.addEventListener("pointerleave", () => {
      graphState.hoverNodeId = null;
      const draggedNode = graphState.pointer.nodeId ? graphState.nodeById.get(graphState.pointer.nodeId) : null;
      if (draggedNode) draggedNode.elasticHint = Math.max(draggedNode.elasticHint || 0, 0.9);
      graphState.pointer.dragging = false;
      graphState.pointer.mode = "pan";
      graphState.pointer.nodeId = null;
      canvas.classList.remove("dragging");
      canvas.classList.remove("rotating");
      canvas.classList.remove("node-dragging");
      canvas.classList.remove("linking");
      canvas.classList.remove("node-hover");
      graphState.linkDraft = null;
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
  window.NFStoryPackage = {
    protect: protectStoryPackage,
    open: openStoryPackage,
    download: downloadJSONFile,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindEvents);
  } else {
    bindEvents();
  }
})();
