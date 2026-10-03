"""Provider selection from environment variables."""

import os

from src.llm.base import LLMProvider
from src.llm.glm_provider import GLMProvider
from src.llm.gemini_provider import GeminiProvider

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
    raw = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    name = _ALIASES.get(raw, raw)

    if name not in _PROVIDERS:
        known = sorted(set(_PROVIDERS) | set(_ALIASES))
        raise ValueError(
            f"unknown LLM_PROVIDER '{raw}'; known: {known}"
        )

    if name == "gemini":
        return GeminiProvider(
            api_key=os.getenv("LLM_API_KEY", ""),
            model=os.getenv("LLM_MODEL", "gemini-3.8-flash"),
            base_url=os.getenv(
                "LLM_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta",
            ),
            temperature=float(
                os.getenv("LLM_TEMPERATURE", "0.7")
            ),
            max_tokens=int(
                os.getenv("LLM_MAX_TOKENS", "700")
            ),
            timeout=int(
                os.getenv("LLM_TIMEOUT", "60")
            ),
            language=os.getenv(
                "DIGEST_LANGUAGE",
                "en",
            ),
        )

    return GLMProvider(
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", "glm-5.3"),
        base_url=os.getenv(
            "LLM_BASE_URL",
            "https://api.b.ai/v1",
        ),
        temperature=float(
            os.getenv("LLM_TEMPERATURE", "0.7")
        ),
        max_tokens=int(
            os.getenv("LLM_MAX_TOKENS", "700")
        ),
        timeout=int(
            os.getenv("LLM_TIMEOUT", "60")
        ),
        language=os.getenv(
            "DIGEST_LANGUAGE",
            "en",
        ),
    )