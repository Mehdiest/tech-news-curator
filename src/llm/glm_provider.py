"""GLM via any OpenAI-compatible /chat/completions endpoint (default api.b.ai)."""

from __future__ import annotations

import asyncio
import json
import logging
import re

import aiohttp

from src.llm.base import LLMError, Summary, parse_summary_json
from src.llm.prompts import build_messages
from src.models import Article

logger = logging.getLogger(__name__)

_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
_RETRY_DELAY_SECONDS = 2.0

# 'export KEY=...' / 'KEY=...' / 'set KEY=...' pastes (word chars then '=')
_ASSIGNMENT_PREFIX = re.compile(r"^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=")


def _mask_key(api_key: str) -> str:
    """First/last fingerprint of a key safe for logs and hints."""
    if len(api_key) <= 10:
        return f"{api_key[:2]}...{api_key[-2:]}"
    return f"{api_key[:6]}...{api_key[-4:]}"


def _is_local_url(url: str) -> bool:
    """True for loopback endpoints served by a local router/gateway."""
    return any(
        marker in url
        for marker in ("//localhost", "//127.0.0.1", "//[::1]", "//0.0.0.0", "://host.docker.internal")
    )


def _validate_api_key(api_key: str) -> str:
    """Clean edge noise from a hand-pasted key; reject structural paste errors.

    401 "Invalid api_key format" almost always means the secret holds anything
    other than the raw key value. Edge whitespace/newlines and wrapping quotes
    are cleaned automatically; a 'Bearer ' prefix, a pasted 'LLM_API_KEY=...'
    line, or internal whitespace raises with an actionable message.
    """
    key = api_key.strip().strip('"').strip("'")
    if not key:
        raise ValueError("api_key is empty - set LLM_API_KEY")
    if key.lower().startswith("bearer "):
        raise ValueError(
            "api_key has a 'Bearer ' prefix - paste ONLY the raw key value"
        )
    if "LLM_API_KEY" in key or _ASSIGNMENT_PREFIX.match(key):
        raise ValueError(
            "api_key is malformed - paste ONLY the raw key value into the "
            "LLM_API_KEY secret: no 'LLM_API_KEY=' prefix, no quotes, no "
            "spaces. Copy it again from the provider console."
        )
    if any(ch.isspace() for ch in key):
        raise ValueError(
            "api_key contains internal whitespace - paste the raw key value "
            "as one contiguous string"
        )
    return key


class GLMProvider:
    """POST {base_url}/chat/completions with a Bearer key; non-streaming."""

    name = "glm"

    def __init__(
        self,
        api_key: str,
        model: str = "glm-5.3",
        base_url: str = "https://api.b.ai/v1",
        temperature: float = 0.7,
        max_tokens: int = 700,
        timeout: int = 60,
        language: str = "en",
        max_attempts: int = 2,
    ):
        # Secrets are hand-pasted; the preflight cleans invisible edge noise
        # and hard-fails on paste mistakes that cleaning cannot fix.
        cleaned = _validate_api_key(api_key)
        if cleaned != api_key:
            logger.warning(
                "LLM_API_KEY had surrounding whitespace/quotes - cleaned automatically"
            )
        self.api_key = cleaned
        self.model = model
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.language = language
        self.max_attempts = max(1, max_attempts)

    async def summarize(self, article: Article) -> Summary:
        """One chat completion per article; raises LLMError on failure."""
        reply_text = await self.chat(build_messages(article, self.language))
        summary = parse_summary_json(reply_text)
        logger.debug("llm ok: %s", article.title[:60])
        return summary

    async def chat(self, messages: list[dict], max_tokens: int | None = None) -> str:
        """Generic chat completion with the same transient-retry policy."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        return await self._chat_with_retry(payload)

    async def _chat_with_retry(self, payload: dict) -> str:
        """Retry transient failures (429/5xx/timeout) with linear backoff."""
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await self._post_once(payload)
            except LLMError as error:
                if attempt == self.max_attempts or not error.transient:
                    raise
                logger.warning(
                    "llm transient error (%d/%d): %s", attempt, self.max_attempts, error,
                )
                await asyncio.sleep(_RETRY_DELAY_SECONDS * attempt)
        raise LLMError("unreachable retry state")

    def _auth_hint(self, status: int) -> str:
        """Disambiguate 401/403: the key is always attached client-side, so
        the failure is either the endpoint rejecting the key or - for a local
        router such as 9Router/one-api - an UPSTREAM auth failure relayed
        verbatim. OpenRouter's relayed signature is 'Missing Authentication
        header' (numeric code, no 'type' field); the router's own rejections
        read 'Missing API key' / 'Invalid API key'. Saying so in the error
        saves a whole debugging session."""
        if status not in (401, 403):
            return ""
        key_fingerprint = f"Bearer {_mask_key(self.api_key)}"
        if _is_local_url(self.url):
            return (
                f" | hint: the key WAS sent ({key_fingerprint}) to {self.url}. "
                "Local router? Then: 'Invalid/Missing API key' in the body = fix "
                "LLM_API_KEY (the router's own key); 'Missing Authentication "
                "header' (OpenRouter) = the provider connection inside the "
                "router dashboard has no API key attached"
            )
        return (
            f" | hint: the key WAS sent ({key_fingerprint}) to {self.url} and "
            "was rejected - re-copy the RAW key from the provider console "
            "(no 'Bearer ' prefix, no quotes, no spaces)"
        )

    async def _post_once(self, payload: dict) -> str:
        """Single HTTP call; converts every failure into LLMError."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        client_timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.post(self.url, json=payload, headers=headers) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise LLMError(
                            f"HTTP {response.status}: {body[:200]}{self._auth_hint(response.status)}",
                            transient=response.status in _RETRY_STATUS,
                        )
        except aiohttp.ClientError as error:
            raise LLMError(f"network error: {error!r}", transient=True) from error
        return _extract_content(body)


def _extract_content(body: str) -> str:
    """Pull choices[0].message.content out of an OpenAI-style reply."""
    try:
        data = json.loads(body)
        return data["choices"][0]["message"]["content"] or ""
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise LLMError(f"unexpected response shape: {body[:200]} ({error})") from error
