"""Provider selection from environment variables."""

import os

from src.llm.base import LLMProvider
from src.llm.gemini_provider import GeminiProvider
from src.llm.glm_provider import GLMProvider

_PROVIDERS = {
    "gemini": GeminiProvider,
    "glm": GLMProvider,
}

_ALIASES = {
    "openai": "glm",
    "openai-compatible": "glm",
    "9router": "glm",
}


def make_provider() -> LLMProvider:
    """Build the configured LLM provider from environment variables."""

    raw_name = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    name = _ALIASES.get(raw_name, raw_name)

    if name not in _PROVIDERS:
        known = sorted(set(_PROVIDERS) | set(_ALIASES))
        raise ValueError(
            f"unknown LLM_PROVIDER '{raw_name}'; known: {known}"
        )

    defaults = {
        "gemini": {
            "model": "gemini-3.8-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
        },
        "glm": {
            "model": "glm-5.3",
            "base_url": "https://api.b.ai/v1",
        },
    }

    provider_defaults = defaults[name]

    return _PROVIDERS[name](
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv(
            "LLM_MODEL",
            provider_defaults["model"],
        ),
        base_url=os.getenv(
            "LLM_BASE_URL",
            provider_defaults["base_url"],
        ),
        temperature=float(
            os.getenv("LLM_TEMPERATURE", "0.7")
        ),
        max_tokens=int(
            os.getenv("LLM_MAX_TOKENS", "12000")
        ),
        timeout=int(
            os.getenv("LLM_TIMEOUT", "60")
        ),
        language=os.getenv(
            "DIGEST_LANGUAGE",
            "en",
        ),
    )