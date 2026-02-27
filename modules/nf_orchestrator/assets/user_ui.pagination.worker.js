self.onmessage = (event) => {
  const payload = event?.data || {};
  const requestId = payload.request_id;
  const text = String(payload.text || "").replace(/\r\n/g, "\n");
  const budgetRaw = Number.parseInt(String(payload.page_char_budget ?? ""), 10);
  const pageCharBudget =
    Number.isInteger(budgetRaw) && budgetRaw > 0
      ? Math.max(600, Math.min(6000, budgetRaw))
      : 1800;
  const breakChars = new Set(
    Array.isArray(payload.break_chars)
      ? payload.break_chars.map((item) => String(item || ""))
      : [".", ",", "!", "?", ";", ":", "。", "！", "？"],
  );

  const pages = paginateWithBudget(text, pageCharBudget, breakChars);
  self.postMessage({
    request_id: requestId,
    pages,
  });
};

function paginateWithBudget(text, budget, breakChars) {
  if (!text.length) {
    return [{ start: 0, end: 0, text: "" }];
  }

  const pages = [];
  const totalLen = text.length;
  let cursor = 0;

  while (cursor < totalLen) {
    let end = Math.min(totalLen, cursor + budget);
    if (end < totalLen) {
      end = snapBreakPoint(text, cursor, end, breakChars);
    }
    if (end <= cursor) {
      end = Math.min(totalLen, cursor + budget);
    }
    if (end <= cursor) {
      end = Math.min(totalLen, cursor + 1);
    }
    pages.push({
      start: cursor,
      end,
      text: text.slice(cursor, end),
    });
    cursor = end;
  }

  return pages.length > 0 ? pages : [{ start: 0, end: 0, text: "" }];
}

function snapBreakPoint(text, start, candidate, breakChars) {
  const min = Math.max(start + 1, candidate - 280);
  for (let idx = candidate; idx > min; idx -= 1) {
    const ch = text[idx - 1];
    if (ch === "\n") return idx;
    if (/\s/.test(ch)) return idx;
    if (breakChars.has(ch)) return idx;
  }
  return candidate;
}

