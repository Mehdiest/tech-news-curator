"""Google Gemini provider using the Gemini REST API."""

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
_ASSIGNMENT_PREFIX = re.compile(r"^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=")


def _validate_api_key(api_key: str) -> str:
    """Clean edge noise from a hand-pasted Gemini API key."""
    key = api_key.strip().strip('"').strip("'")
    if not key:
        raise ValueError("api_key is empty - set LLM_API_KEY")
    if key.lower().startswith("bearer "):
        raise ValueError("Gemini API key must be the raw key, without 'Bearer '")
    if "LLM_API_KEY" in key or _ASSIGNMENT_PREFIX.match(key):
        raise ValueError("LLM_API_KEY must contain only the raw API key value")
    if any(ch.isspace() for ch in key):
        raise ValueError("LLM_API_KEY contains internal whitespace")
    return key


class GeminiProvider:
    """Call Google's Gemini generateContent REST endpoint."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        temperature: float = 0.7,
        max_tokens: int = 700,
        timeout: int = 60,
        language: str = "en",
        max_attempts: int = 2,
    ):
        self.api_key = _validate_api_key(api_key)
        self.model = model
        self.url = f"{base_url.rstrip('/')}/models/{model}:generateContent"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.language = language
        self.max_attempts = max(1, max_attempts)

    async def summarize(self, article: Article) -> Summary:
        """Generate one structured English digest summary."""
        reply_text = await self.chat(build_messages(article, self.language))
        summary = parse_summary_json(reply_text)
        logger.debug("gemini ok: %s", article.title[:60])
        return summary

    async def chat(self, messages: list[dict], max_tokens: int | None = None) -> str:
        """Convert OpenAI-style messages to Gemini generateContent format."""
        system_parts = []
        contents = []
        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", ""))
            if role == "system":
                system_parts.append(content)
            else:
                contents.append({
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": max_tokens or self.max_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}],
            }
        return await self._generate_with_retry(payload)

    async def _generate_with_retry(self, payload: dict) -> str:
        """Retry transient HTTP and network failures with a short backoff."""
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await self._post_once(payload)
            except LLMError as error:
                if attempt == self.max_attempts or not error.transient:
                    raise
                logger.warning(
                    "gemini transient error (%d/%d): %s",
                    attempt,
                    self.max_attempts,
                    error,
                )
                await asyncio.sleep(_RETRY_DELAY_SECONDS * attempt)
        raise LLMError("unreachable retry state")

    async def _post_once(self, payload: dict) -> str:
        """Make one Gemini API request and extract its first text part."""
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        client_timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.post(self.url, json=payload, headers=headers) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise LLMError(
                            f"HTTP {response.status}: {body[:300]}",
                            transient=response.status in _RETRY_STATUS,
                        )
        except aiohttp.ClientError as error:
            raise LLMError(f"network error: {error!r}", transient=True) from error
        return _extract_content(body)


def _extract_content(body: str) -> str:
    """Extract candidates[0].content.parts[0].text from a Gemini reply."""
    try:
        data = json.loads(body)
        candidates = data.get("candidates") or []
        parts = candidates[0]["content"]["parts"]
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        if not text:
            raise KeyError("empty text")
        return text
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise LLMError(f"unexpected Gemini response shape: {body[:300]} ({error})") from error
