"""Provider selection from environment variables."""

import os

from src.llm.base import LLMProvider
from src.llm.gemini_provider import GeminiProvider
from src.llm.glm_provider import GLMProvider

_PROVIDERS = {"gemini": GeminiProvider, "glm": GLMProvider}
_ALIASES = {"9router": "glm", "openai-compatible": "glm", "openai": "glm"}


def make_provider() -> LLMProvider:
    """Build the provider named by LLM_PROVIDER using LLM_* env vars."""
    raw = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    name = _ALIASES.get(raw, raw)
    if name not in _PROVIDERS:
        known = sorted(set(_PROVIDERS) | set(_ALIASES))
        raise ValueError(f"unknown LLM_PROVIDER '{raw}'; known: {known}")

    kwargs = {
        "api_key": os.getenv("LLM_API_KEY", ""),
        "model": os.getenv(
            "LLM_MODEL",
            "gemini-2.5-flash" if name == "gemini" else "glm-5.3",
        ),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "700")),
        "timeout": int(os.getenv("LLM_TIMEOUT", "60")),
        "language": os.getenv("DIGEST_LANGUAGE", "en"),
    }
    if name == "gemini":
        kwargs["base_url"] = os.getenv(
            "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        )
    else:
        kwargs["base_url"] = os.getenv("LLM_BASE_URL", "https://api.b.ai/v1")

    return _PROVIDERS[name](**kwargs)
