from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, parse, request


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return ""
    texts: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return "\n".join(texts)


def call_gemini(prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("NF_GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY (or NF_GEMINI_API_KEY) is required")

    model = os.environ.get("NF_GEMINI_MODEL", "gemini-2.0-flash")
    query = parse.urlencode({"key": api_key})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?{query}"
    body = json.dumps(
        {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }
    ).encode("utf-8")
    req = request.Request(
        url=url,
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"gemini request failed: HTTP {exc.code}: {payload}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"gemini request failed: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gemini response was not valid JSON") from exc
    text = _extract_text(parsed if isinstance(parsed, dict) else {})
    if text:
        return text
    raise RuntimeError("gemini response did not include text output")
