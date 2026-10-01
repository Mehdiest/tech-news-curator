"""Provider selection from env vars."""

import os

from src.llm.base import LLMProvider
from src.llm.glm_provider import GLMProvider

# Every name here is an OpenAI-compatible /chat/completions endpoint served
# by the same GLMProvider class. Aliases exist so LLM_PROVIDER can mirror
# the gateway the user actually runs in front of a provider (e.g. the
# 9Router local gateway) instead of crashing with 'unknown LLM_PROVIDER'.
_PROVIDERS = {"glm": GLMProvider}
_ALIASES = {"9router": "glm", "openai-compatible": "glm", "openai": "glm"}


def make_provider() -> LLMProvider:
    """Build the provider named by LLM_PROVIDER using LLM_* env vars."""
    raw = os.getenv("LLM_PROVIDER", "glm").strip().lower()
    name = _ALIASES.get(raw, raw)
    if name not in _PROVIDERS:
        known = sorted(set(_PROVIDERS) | set(_ALIASES))
        raise ValueError(f"unknown LLM_PROVIDER '{raw}'; known: {known}")
    return _PROVIDERS[name](
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", "glm-5.3"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.b.ai/v1"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "700")),
        timeout=int(os.getenv("LLM_TIMEOUT", "60")),
        language=os.getenv("DIGEST_LANGUAGE", "en"),
    )
