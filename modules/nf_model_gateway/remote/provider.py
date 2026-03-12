from __future__ import annotations

import os
import re
from typing import Protocol

from modules.nf_model_gateway.remote.gemini_client import call_gemini
from modules.nf_model_gateway.remote.openai_client import call_openai


class RemoteProvider(Protocol):
    def complete(self, prompt: str, *, timeout_sec: float = 30.0) -> str: ...


class OpenAIProvider:
    def complete(self, prompt: str, *, timeout_sec: float = 30.0) -> str:
        return call_openai(prompt, timeout_sec=timeout_sec)


class GeminiProvider:
    def complete(self, prompt: str, *, timeout_sec: float = 30.0) -> str:
        return call_gemini(prompt, timeout_sec=timeout_sec)


_TOKEN_RE = re.compile(r"\b[a-zA-Z0-9_-]{16,}\b")
_OPENAI_RE = re.compile(r"sk-[a-zA-Z0-9]{8,}")


def mask_sensitive(text: str) -> str:
    masked = _OPENAI_RE.sub("sk-***", text)
    return _TOKEN_RE.sub("***", masked)


def selected_remote_provider_name(name: str | None = None) -> str:
    return (name or os.environ.get("NF_REMOTE_PROVIDER", "openai")).lower()


def selected_remote_model_id(name: str | None = None) -> str:
    provider = selected_remote_provider_name(name)
    if provider == "gemini":
        model = os.environ.get("NF_GEMINI_MODEL", "gemini-2.0-flash")
    else:
        provider = "openai"
        model = os.environ.get("NF_OPENAI_MODEL", "gpt-4.1-mini")
    return f"{provider}:{model}"


def remote_provider_credentials_configured(name: str | None = None) -> bool:
    provider = selected_remote_provider_name(name)
    if provider == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("NF_GEMINI_API_KEY"))
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("NF_OPENAI_API_KEY"))


def select_remote_provider(name: str | None = None) -> RemoteProvider:
    provider = selected_remote_provider_name(name)
    if provider == "gemini":
        return GeminiProvider()
    return OpenAIProvider()
