      // --- State ---
      let state = {
        projectId: null,
        projectName: "",
        currentDocId: null,
        currentDocType: "EPISODE",
        currentNavTab: "EPISODE",
        docs: {},
        saveTimeout: null,
        postSavePipelineTimer: null,
        backgroundConsistencyTimer: null,
        backgroundConsistencyRunning: false,
        isDirty: false,
        draggedDocId: null,
        draggedGroup: null,
        pendingConsistencySegments: [],
        lastSegmentFingerprints: [],
        lastVerdicts: [],
        showOkVerdicts: false,
        consistencyOptions: {
          filters: {
            entity_id: "",
            time_key: "",
            timeline_idx: "",
          },
          graph_mode: "off",
          layer3_promotion: true,
          verifier_mode: "off",
          triage_mode: "off",
          verification_loop: true,
        },
        editorConfig: {
          fontSize: "1.1rem",
          lineHeight: "1.8",
          letterSpacing: "0px",
          fontFamily: "'Noto Serif KR', serif",
        },
      };

      const SENTENCE_END_CHARS = new Set([
        ".",
        "!",
        "?",
        "\n",
        "。",
        "！",
        "？",
        "…",
        "．",
      ]);
      const SENTENCE_TAIL_CHARS = new Set([
        ".",
        "…",
        "'",
        '"',
        ")",
        "]",
        "}",
        "’",
        "”",
        "」",
        "』",
        "》",
      ]);

      function _hashSegmentText(text) {
        let hash = 2166136261;
        const value = String(text || "");
        for (let i = 0; i < value.length; i += 1) {
          hash ^= value.charCodeAt(i);
          hash = Math.imul(hash, 16777619);
        }
        return `fnv1a:${(hash >>> 0).toString(16)}`;
      }

      function _trimSegmentSpan(text, start, end) {
        let left = Math.max(0, Number(start || 0));
        let right = Math.max(left, Number(end || 0));
        while (left < right && /\s/.test(text[left])) left += 1;
        while (right > left && /\s/.test(text[right - 1])) right -= 1;
        if (right <= left) return null;
        return { start: left, end: right, text: text.slice(left, right) };
      }

      function _segmentTextForConsistency(text) {
        const src = String(text || "");
        const segments = [];
        const textLen = src.length;
        let cursor = 0;
        let idx = 0;

        const appendSegment = (segStart, segEnd, closed) => {
          const trimmed = _trimSegmentSpan(src, segStart, segEnd);
          if (!trimmed) return;
          segments.push({
            start: trimmed.start,
            end: trimmed.end,
            text: trimmed.text,
            fingerprint: _hashSegmentText(trimmed.text),
            closed: Boolean(closed),
          });
        };

        while (idx < textLen) {
          const ch = src[idx];
          if (!SENTENCE_END_CHARS.has(ch)) {
            idx += 1;
            continue;
          }
          if (
            ch === "." &&
            idx > 0 &&
            idx < textLen - 1 &&
            /\d/.test(src[idx - 1] || "") &&
            /\d/.test(src[idx + 1] || "")
          ) {
            idx += 1;
            continue;
          }
          let segEnd = idx;
          if (ch !== "\n") {
            segEnd = idx + 1;
            while (segEnd < textLen && SENTENCE_TAIL_CHARS.has(src[segEnd])) {
              segEnd += 1;
            }
          }
          appendSegment(cursor, segEnd, true);
          cursor = ch === "\n" ? idx + 1 : segEnd;
          idx = cursor;
        }
        appendSegment(cursor, textLen, false);
        return segments;
      }

      function _collectChangedSegments(prevSegments, nextSegments) {
        const prevBuckets = new Map();
        (Array.isArray(prevSegments) ? prevSegments : []).forEach((item) => {
          if (
            !item ||
            !Number.isInteger(item.start) ||
            !Number.isInteger(item.end)
          )
            return;
          const fingerprint =
            typeof item.fingerprint === "string" && item.fingerprint
              ? item.fingerprint
              : _hashSegmentText(item.text || "");
          if (!prevBuckets.has(fingerprint)) prevBuckets.set(fingerprint, []);
          prevBuckets.get(fingerprint).push({
            start: item.start,
            end: item.end,
          });
        });
        prevBuckets.forEach((bucket) =>
          bucket.sort((left, right) => left.start - right.start),
        );

        const changed = [];
        (Array.isArray(nextSegments) ? nextSegments : []).forEach((item) => {
          if (
            !item ||
            !Number.isInteger(item.start) ||
            !Number.isInteger(item.end)
          )
            return;
          if (!item.closed) return;
          const fingerprint =
            typeof item.fingerprint === "string" && item.fingerprint
              ? item.fingerprint
              : _hashSegmentText(item.text || "");
          const bucket = prevBuckets.get(fingerprint);
          if (!Array.isArray(bucket) || bucket.length === 0) {
            changed.push(item);
            return;
          }

          let bestIdx = 0;
          let bestDist = Math.abs(bucket[0].start - item.start);
          for (let idx = 1; idx < bucket.length; idx += 1) {
            const dist = Math.abs(bucket[idx].start - item.start);
            if (dist < bestDist) {
              bestDist = dist;
              bestIdx = idx;
            }
          }
          bucket.splice(bestIdx, 1);
        });
        return changed;
      }

      function _mergeConsistencySegments(segments) {
        const normalized = (Array.isArray(segments) ? segments : [])
          .filter(
            (item) =>
              item &&
              Number.isInteger(item.start) &&
              Number.isInteger(item.end) &&
              item.end > item.start,
          )
          .map((item) => ({ start: item.start, end: item.end }))
          .sort((left, right) => {
            if (left.start !== right.start) return left.start - right.start;
            return left.end - right.end;
          });
        if (normalized.length === 0) return [];
        const merged = [normalized[0]];
        for (let idx = 1; idx < normalized.length; idx += 1) {
          const current = normalized[idx];
          const tail = merged[merged.length - 1];
          if (current.start <= tail.end + 1) {
            tail.end = Math.max(tail.end, current.end);
          } else {
            merged.push(current);
          }
        }
        return merged;
      }

      function _spanOverlaps(startA, endA, startB, endB) {
        return startA < endB && startB < endA;
      }

      function _normalizeGraphMode(raw) {
        if (raw === "manual" || raw === "auto" || raw === "off") return raw;
        if (raw === "on") return "manual";
        return "off";
      }

      function _normalizeVerifierMode(raw) {
        if (raw === "conservative_nli" || raw === "off") return raw;
        if (raw === "on") return "conservative_nli";
        return "off";
      }

      function _normalizeTriageMode(raw) {
        if (raw === "embedding_anomaly" || raw === "off") return raw;
        if (raw === "on") return "embedding_anomaly";
        return "off";
      }

      function _showConsistencyNotice(
        message,
        color = "#3498db",
        ttlMs = 2800,
      ) {
        const cStatus = document.getElementById("consistency-status");
        if (!cStatus || !message) return;
        cStatus.innerText = String(message);
        cStatus.style.color = color;
        if (ttlMs > 0) {
          setTimeout(() => {
            if (
              cStatus.innerText === message &&
              !state.backgroundConsistencyRunning
            ) {
              cStatus.innerText = "";
            }
          }, ttlMs);
        }
      }

      function _readConsistencyOptionsFromUi() {
        const entityInput = document.getElementById(
          "consistency-filter-entity",
        );
        const timeInput = document.getElementById("consistency-filter-time");
        const timelineInput = document.getElementById(
          "consistency-filter-timeline",
        );

        const filters = {};
        const entityId =
          entityInput && typeof entityInput.value === "string"
            ? entityInput.value.trim()
            : "";
        const timeKey =
          timeInput && typeof timeInput.value === "string"
            ? timeInput.value.trim()
            : "";
        const timelineIdxRaw =
          timelineInput && typeof timelineInput.value === "string"
            ? timelineInput.value.trim()
            : "";
        if (entityId) filters.entity_id = entityId;
        if (timeKey) filters.time_key = timeKey;
        if (timelineIdxRaw !== "") {
          const parsedTimeline = Number.parseInt(timelineIdxRaw, 10);
          if (Number.isInteger(parsedTimeline) && parsedTimeline >= 0) {
            filters.timeline_idx = parsedTimeline;
          }
        }

        let selectedLevel = "quick";
        const levelRadios = document.getElementsByName("consistency-level");
        if (levelRadios) {
          for (let r of levelRadios) {
            if (r.checked) {
              selectedLevel = r.value;
              break;
            }
          }
        }

        let graphMode = "off";
        let layer3Promotion = false;
        let verifierMode = "off";
        let triageMode = "off";
        let verificationLoop = false;

        if (selectedLevel === "deep") {
          graphMode = "auto";
          layer3Promotion = true;
          triageMode = "embedding_anomaly";
        } else if (selectedLevel === "strict") {
          graphMode = "auto";
          layer3Promotion = true;
          verifierMode = "conservative_nli";
          triageMode = "embedding_anomaly";
          verificationLoop = true;
        }

        const graphModeInput = document.getElementById(
          "consistency-graph-mode",
        );
        if (graphModeInput && typeof graphModeInput.value === "string") {
          graphMode = _normalizeGraphMode(graphModeInput.value.trim());
        }
        const layer3Input = document.getElementById(
          "consistency-layer3-promotion",
        );
        if (layer3Input) {
          layer3Promotion = Boolean(layer3Input.checked);
        }
        const verifierInput = document.getElementById(
          "consistency-verifier-mode",
        );
        if (verifierInput && typeof verifierInput.value === "string") {
          verifierMode = _normalizeVerifierMode(verifierInput.value.trim());
        }
        const triageInput = document.getElementById(
          "consistency-triage-mode",
        );
        if (triageInput && typeof triageInput.value === "string") {
          triageMode = _normalizeTriageMode(triageInput.value.trim());
        }
        const loopInput = document.getElementById("consistency-loop-enabled");
        if (loopInput) {
          verificationLoop = Boolean(loopInput.checked);
        }

        state.consistencyOptions = {
          filters: {
            entity_id: entityId,
            time_key: timeKey,
            timeline_idx: timelineIdxRaw,
          },
          graph_mode: graphMode,
          layer3_promotion: layer3Promotion,
          verifier_mode: verifierMode,
          triage_mode: triageMode,
          verification_loop: verificationLoop,
        };

        const consistencyParams = {
          graph_mode: graphMode,
          graph_expand_enabled: graphMode !== "off",
          layer3_verdict_promotion: layer3Promotion,
          verifier: {
            mode: verifierMode,
            promote_ok_threshold: 0.95,
            contradict_alert_threshold: 0.7,
            max_claim_chars: 220,
          },
          triage: {
            mode: triageMode,
            anomaly_threshold: 0.65,
            max_segments_per_run: 8,
          },
          verification_loop: {
            enabled: verificationLoop,
            max_rounds: 2,
            round_timeout_ms: 250,
          },
        };

        return {
          filters,
          params: {
            consistency: consistencyParams,
          },
        };
      }

      function _buildConsistencyJobPayload(docId, range, preflight) {
        const options = _readConsistencyOptionsFromUi();
        return {
          type: "CONSISTENCY",
          project_id: state.projectId,
          inputs: {
            input_doc_id: docId,
            input_snapshot_id: "latest",
            range,
            preflight,
            schema_scope: "explicit_only",
            filters: options.filters,
          },
          params: options.params,
        };
      }

      let fallbackHighlightActive = false;

      function clearInlineVerdictHighlights() {
        if (window.CSS && CSS.highlights) {
          CSS.highlights.delete("nf-violate");
          CSS.highlights.delete("nf-unknown");
        }

        const editor = document.getElementById("editor");
        if (!editor) return;
        const spans = editor.querySelectorAll(".nf-highlight-fallback");
        spans.forEach((span) => {
          const parent = span.parentNode;
          if (!parent) return;
          while (span.firstChild) parent.insertBefore(span.firstChild, span);
          parent.removeChild(span);
        });
        if (spans.length > 0) {
          editor.normalize();
        }
        fallbackHighlightActive = false;
      }

      function renderInlineVerdictHighlights(verdicts) {
        clearInlineVerdictHighlights();
        const editor = document.getElementById("editor");
        if (!editor) return;
        const text = editor.textContent || "";
        if (!text) return;

        const textNodes = _collectEditorTextNodes(editor);
        if (!textNodes.length) return;

        const rows = Array.isArray(verdicts) ? verdicts : [];
        const highlightItems = [];

        rows.forEach((item) => {
          const verdict = String(item?.verdict || "UNKNOWN");
          if (verdict !== "VIOLATE" && verdict !== "UNKNOWN") return;
          const span =
            item && typeof item.segment_span === "object"
              ? item.segment_span
              : {};
          const start = Number.isInteger(span.start) ? span.start : null;
          const end = Number.isInteger(span.end) ? span.end : null;
          if (
            start === null ||
            end === null ||
            end <= start ||
            start < 0 ||
            start >= text.length
          )
            return;
          const clampedEnd = Math.min(end, text.length);
          if (clampedEnd <= start) return;
          highlightItems.push({ start, end: clampedEnd, verdict });
        });

        if (
          window.CSS &&
          CSS.highlights &&
          typeof window.Highlight === "function"
        ) {
          const violateRanges = [];
          const unknownRanges = [];
          highlightItems.forEach(({ start, end, verdict }) => {
            const startPos = _positionForOffset(textNodes, start);
            const endPos = _positionForOffset(textNodes, end);
            if (!startPos || !endPos) return;
            const range = document.createRange();
            range.setStart(startPos.node, startPos.offset);
            range.setEnd(endPos.node, endPos.offset);
            if (verdict === "VIOLATE") violateRanges.push(range);
            else unknownRanges.push(range);
          });

          if (violateRanges.length > 0) {
            CSS.highlights.set("nf-violate", new Highlight(...violateRanges));
          }
          if (unknownRanges.length > 0) {
            CSS.highlights.set("nf-unknown", new Highlight(...unknownRanges));
          }
        } else {
          fallbackHighlightActive = true;
          highlightItems.sort((a, b) => b.start - a.start);
          highlightItems.forEach(({ start, end, verdict }) => {
            const startPos = _positionForOffset(textNodes, start);
            const endPos = _positionForOffset(textNodes, end);
            if (!startPos || !endPos) return;
            const range = document.createRange();
            range.setStart(startPos.node, startPos.offset);
            range.setEnd(endPos.node, endPos.offset);

            const span = document.createElement("span");
            const bgClass =
              verdict === "VIOLATE" ? "nf-violate-bg" : "nf-unknown-bg";
            span.className = `nf-highlight-fallback ${bgClass}`;

            try {
              range.surroundContents(span);
            } catch (e) {
              const contents = range.extractContents();
              span.appendChild(contents);
              range.insertNode(span);
            }
          });
        }
      }

      // ... (Config Management omitted, stays same) ...
