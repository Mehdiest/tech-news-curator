"""Provider selection from env vars."""

import os

from src.llm.base import LLMProvider
from src.llm.glm_provider import GLMProvider

_PROVIDERS = {"glm": GLMProvider}


def make_provider() -> LLMProvider:
    """Build the provider named by LLM_PROVIDER using LLM_* env vars."""
    name = os.getenv("LLM_PROVIDER", "glm").strip().lower()
    if name not in _PROVIDERS:
        raise ValueError(f"unknown LLM_PROVIDER '{name}'; known: {sorted(_PROVIDERS)}")
    return _PROVIDERS[name](
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", "glm-5.3"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.b.ai/v1"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "700")),
        timeout=int(os.getenv("LLM_TIMEOUT", "60")),
        language=os.getenv("DIGEST_LANGUAGE", "en"),
    )
