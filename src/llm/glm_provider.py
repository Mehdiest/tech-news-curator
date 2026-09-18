"""GLM via any OpenAI-compatible /chat/completions endpoint (default api.b.ai)."""

from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from src.llm.base import LLMError, Summary, parse_summary_json
from src.llm.prompts import build_messages
from src.models import Article

logger = logging.getLogger(__name__)

_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
_RETRY_DELAY_SECONDS = 2.0


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
        # Secrets are hand-pasted and 401 "Invalid api_key format" almost
        # always means stray whitespace/quotes/newline around the value.
        # Clean the edges automatically; only hard-fail on structural paste
        # mistakes that cleaning cannot fix.
        raw_key = api_key
        api_key = api_key.strip().strip('"').strip("'")
        if api_key != raw_key:
            logger.warning(
                "LLM_API_KEY had surrounding whitespace/quotes - cleaned automatically"
            )
        if not api_key:
            raise ValueError("api_key is empty - set LLM_API_KEY")
        if "LLM_API_KEY" in api_key or any(ch.isspace() for ch in api_key):
            raise ValueError(
                "api_key is malformed - paste ONLY the raw key value into the "
                "LLM_API_KEY secret: no 'LLM_API_KEY=' prefix, no quotes, no "
                "spaces. Copy it again from the provider console."
            )
        self.api_key = api_key
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
                            f"HTTP {response.status}: {body[:200]}",
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
