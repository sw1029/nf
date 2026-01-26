from __future__ import annotations

import os
import re
from typing import Protocol

from modules.nf_model_gateway.remote.gemini_client import call_gemini
from modules.nf_model_gateway.remote.openai_client import call_openai


class RemoteProvider(Protocol):
    def complete(self, prompt: str) -> str: ...


class OpenAIProvider:
    def complete(self, prompt: str) -> str:
        return call_openai(prompt)


class GeminiProvider:
    def complete(self, prompt: str) -> str:
        return call_gemini(prompt)


_TOKEN_RE = re.compile(r"\b[a-zA-Z0-9_-]{16,}\b")
_OPENAI_RE = re.compile(r"sk-[a-zA-Z0-9]{8,}")


def mask_sensitive(text: str) -> str:
    masked = _OPENAI_RE.sub("sk-***", text)
    return _TOKEN_RE.sub("***", masked)


def select_remote_provider(name: str | None = None) -> RemoteProvider:
    provider = (name or os.environ.get("NF_REMOTE_PROVIDER", "openai")).lower()
    if provider == "gemini":
        return GeminiProvider()
    return OpenAIProvider()
