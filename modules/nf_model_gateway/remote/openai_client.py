from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


def _extract_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text
    output = payload.get("output")
    if isinstance(output, list):
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                text = block.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
        if texts:
            return "\n".join(texts)
    return ""


def call_openai(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("NF_OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY (or NF_OPENAI_API_KEY) is required")

    model = os.environ.get("NF_OPENAI_MODEL", "gpt-4.1-mini")
    body = json.dumps(
        {
            "model": model,
            "input": prompt,
            "temperature": 0.2,
        }
    ).encode("utf-8")
    req = request.Request(
        url="https://api.openai.com/v1/responses",
        method="POST",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"openai request failed: HTTP {exc.code}: {payload}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"openai request failed: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("openai response was not valid JSON") from exc

    text = _extract_text(parsed if isinstance(parsed, dict) else {})
    if text:
        return text
    raise RuntimeError("openai response did not include text output")
