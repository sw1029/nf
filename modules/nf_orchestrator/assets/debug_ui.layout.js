      function clampNumber(value, min, max, fallback) {
        const num = Number(value);
        if (!Number.isFinite(num)) return fallback;
        return Math.max(min, Math.min(max, num));
      }
      function normalizeHexColor(value, fallback = "#ffffff") {
        if (typeof value !== "string") return fallback;
        const v = value.trim();
        if (/^#[0-9a-fA-F]{6}$/.test(v)) return v;
        return fallback;
      }
      function normalizeLayoutStyle(raw) {
        const obj = raw && typeof raw === "object" ? raw : {};
        return {
          letterSpacingEm: clampNumber(obj.letterSpacingEm, -0.02, 0.2, LAYOUT_STYLE_DEFAULTS.letterSpacingEm),
          lineHeight: clampNumber(obj.lineHeight, 1.0, 2.2, LAYOUT_STYLE_DEFAULTS.lineHeight),
          fontSizePx: clampNumber(obj.fontSizePx, 10, 32, LAYOUT_STYLE_DEFAULTS.fontSizePx),
          paddingX: clampNumber(obj.paddingX, 0, 80, LAYOUT_STYLE_DEFAULTS.paddingX),
          bgColor: normalizeHexColor(obj.bgColor, LAYOUT_STYLE_DEFAULTS.bgColor),
          fontPreset: String(obj.fontPreset || LAYOUT_STYLE_DEFAULTS.fontPreset),
          fontCustom: String(obj.fontCustom || LAYOUT_STYLE_DEFAULTS.fontCustom),
        };
      }
      function getFontFamilyForPreset(preset) {
        if (preset === "sans_kr") {
          return 'system-ui, "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", "Noto Sans CJK KR", sans-serif';
        }
        if (preset === "serif") {
          return 'ui-serif, Georgia, "Times New Roman", Times, serif';
        }
        if (preset === "mono") {
          return 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';
        }
        return 'system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif';
      }
      function hexToRgb(hex) {
        const m = /^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$/.exec(hex);
        if (!m) return null;
        return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) };
      }
      function pickTextColorForBackground(bgHex) {
        const rgb = hexToRgb(bgHex);
        if (!rgb) return "";
        const r = rgb.r / 255;
        const g = rgb.g / 255;
        const b = rgb.b / 255;
        const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        return luminance < 0.55 ? "#f9fafb" : "#111827";
      }
      function updateFontCustomEnabled() {
        const presetEl = el("layout-font-preset");
        const customEl = el("layout-font-custom");
        if (!presetEl || !customEl) return;
        const enabled = presetEl.value === "custom";
        customEl.disabled = !enabled;
      }
      function getLayoutStyleFromInputs() {
        const raw = {
          letterSpacingEm: el("layout-letter")?.value,
          lineHeight: el("layout-line")?.value,
          fontSizePx: el("layout-font-size")?.value,
          paddingX: el("layout-padding-x")?.value,
          bgColor: el("layout-bg")?.value,
          fontPreset: el("layout-font-preset")?.value,
          fontCustom: el("layout-font-custom")?.value,
        };
        return normalizeLayoutStyle(raw);
      }
      function applyLayoutStyle(preview, style) {
        preview.style.letterSpacing = style.letterSpacingEm + "em";
        preview.style.lineHeight = String(style.lineHeight);
        preview.style.fontSize = style.fontSizePx + "px";
        preview.style.paddingLeft = style.paddingX + "px";
        preview.style.paddingRight = style.paddingX + "px";
        preview.style.backgroundColor = style.bgColor;
        preview.style.color = pickTextColorForBackground(style.bgColor) || "";

        const fontFamily =
          style.fontPreset === "custom" ? (style.fontCustom || "").trim() : getFontFamilyForPreset(style.fontPreset);
        preview.style.fontFamily = fontFamily || "";
      }
      function saveLayoutStyle() {
        const style = getLayoutStyleFromInputs();
        try {
          localStorage.setItem(LAYOUT_STYLE_STORAGE_KEY, JSON.stringify(style));
        } catch {
          // ignore
        }
      }
      function setLayoutInputs(style) {
        el("layout-letter").value = String(style.letterSpacingEm);
        el("layout-line").value = String(style.lineHeight);
        el("layout-font-size").value = String(style.fontSizePx);
        el("layout-padding-x").value = String(style.paddingX);
        el("layout-bg").value = style.bgColor;
        el("layout-font-preset").value = style.fontPreset;
        el("layout-font-custom").value = style.fontCustom;
        updateFontCustomEnabled();
      }
      function loadLayoutStyle() {
        let raw = null;
        try {
          raw = localStorage.getItem(LAYOUT_STYLE_STORAGE_KEY);
        } catch {
          raw = null;
        }
        if (!raw) {
          updateFontCustomEnabled();
          return;
        }
        try {
          const parsed = JSON.parse(raw);
          const style = normalizeLayoutStyle({ ...LAYOUT_STYLE_DEFAULTS, ...parsed });
          setLayoutInputs(style);
        } catch {
          updateFontCustomEnabled();
        }
      }
      function resetLayoutStyle() {
        setLayoutInputs({ ...LAYOUT_STYLE_DEFAULTS });
        saveLayoutStyle();
        renderPreview();
        setStatus("레이아웃 스타일을 기본값으로 되돌렸습니다.");
      }
      function onLayoutStyleChanged() {
        updateFontCustomEnabled();
        saveLayoutStyle();
        renderPreview();
      }
      function renderPreview() {
        const text = el("layout-text").value || "";
        const preview = el("layout-preview");
        applyLayoutStyle(preview, getLayoutStyleFromInputs());
        if (!state.lintItems || state.lintItems.length === 0) {
          preview.textContent = text;
          return;
        }
        const sorted = [...state.lintItems].sort((a, b) => a.span_start - b.span_start);
        let html = "";
        let cursor = 0;
        sorted.forEach((item) => {
          const start = Math.max(0, item.span_start);
          const end = Math.max(start, item.span_end);
          html += escapeHtml(text.slice(cursor, start));
          const segment = escapeHtml(text.slice(start, end));
          const title = escapeHtml(item.message || item.rule_id);
          html += `<span class="lint" title="${title}">${segment}</span>`;
          cursor = end;
        });
        html += escapeHtml(text.slice(cursor));
        preview.innerHTML = html;
      }
