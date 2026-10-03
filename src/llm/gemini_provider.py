"""Google Gemini provider using the Gemini generateContent REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import quote

import aiohttp

from src.llm.base import LLMError, Summary, parse_summary_json
from src.llm.prompts import build_messages
from src.models import Article

logger = logging.getLogger(__name__)

_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
_RETRY_DELAY_SECONDS = 2.0
_ASSIGNMENT_PREFIX = re.compile(r"^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=")


def _validate_api_key(api_key: str) -> str:
    """Clean edge noise from a pasted Gemini key and reject malformed values."""
    key = api_key.strip().strip('"').strip("'")
    if not key:
        raise ValueError("api_key is empty - set LLM_API_KEY")
    if key.lower().startswith("bearer "):
        raise ValueError("api_key has a 'Bearer ' prefix - paste ONLY the raw key value")
    if _ASSIGNMENT_PREFIX.match(key):
        raise ValueError(
            "api_key is malformed - paste ONLY the raw key value, without an "
            "environment-variable assignment"
        )
    if any(ch.isspace() for ch in key):
        raise ValueError("api_key contains internal whitespace - paste the raw key value")
    return key


class GeminiProvider:
    """Call a Gemini model through its REST generateContent endpoint."""

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
        self.model = model.strip() or "gemini-2.5-flash"
        self.base_url = base_url.rstrip("/")
        self.url = f"{self.base_url}/models/{quote(self.model, safe='')}:generateContent"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.language = language
        self.max_attempts = max(1, max_attempts)

    async def summarize(self, article: Article) -> Summary:
        """Generate one structured digest summary for an article."""
        reply_text = await self.chat(build_messages(article, self.language))
        summary = parse_summary_json(reply_text)
        logger.debug("llm ok: %s", article.title[:60])
        return summary

    async def chat(self, messages: list[dict], max_tokens: int | None = None) -> str:
        """Send OpenAI-style chat messages through Gemini's REST API."""
        system_parts: list[dict[str, str]] = []
        contents: list[dict] = []

        for message in messages:
            role = str(message.get("role", "user")).lower()
            content = str(message.get("content", ""))
            if not content:
                continue
            if role == "system":
                system_parts.append({"text": content})
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": content}]})

        if not contents:
            raise LLMError("Gemini request has no user content")

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": max_tokens or self.max_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        return await self._chat_with_retry(payload)

    async def _chat_with_retry(self, payload: dict) -> str:
        """Retry transient HTTP and network failures with short backoff."""
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
        """Make one Gemini request and normalize provider errors."""
        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}
        client_timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.post(
                    self.url, json=payload, headers=headers, params=params
                ) as response:
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
    """Extract the first text candidate from a Gemini response."""
    try:
        data = json.loads(body)
        candidates = data["candidates"]
        parts = candidates[0]["content"]["parts"]
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        if not text:
            raise KeyError("text")
        return text
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise LLMError(f"unexpected Gemini response shape: {body[:300]} ({error})") from error
