"""Google Gemini provider using the Gemini REST generateContent API."""

from __future__ import annotations

import asyncio
import json
import logging
import re

import aiohttp

from src.llm.base import LLMError, Summary, parse_summary_json
from src.llm.prompts import build_messages

logger = logging.getLogger(__name__)

_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
_RETRY_DELAY_SECONDS = 2.0

_ASSIGNMENT_PREFIX = re.compile(
    r"^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*="
)


def _validate_api_key(api_key: str) -> str:
    """Validate and clean a manually supplied Gemini API key."""
    key = api_key.strip().strip('"').strip("'")

    if not key:
        raise ValueError("api_key is empty - set GEMINI_API_KEY")

    if key.lower().startswith("bearer "):
        raise ValueError(
            "api_key has a 'Bearer ' prefix - paste ONLY the raw key value"
        )

    if "GEMINI_API_KEY" in key or _ASSIGNMENT_PREFIX.match(key):
        raise ValueError(
            "api_key is malformed - paste ONLY the raw Gemini API key"
        )

    if any(ch.isspace() for ch in key):
        raise ValueError(
            "api_key contains internal whitespace - paste the raw key "
            "as one contiguous string"
        )

    return key


class GeminiProvider:
    """Call Google's Gemini generateContent API."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        temperature: float = 0.7,
        max_tokens: int = 700,
        timeout: int = 60,
        language: str = "en",
        max_attempts: int = 2,
    ):
        self.api_key = _validate_api_key(api_key)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.language = language
        self.max_attempts = max(1, max_attempts)

    async def summarize(self, article) -> Summary:
        """Generate one structured digest summary for an article."""
        reply_text = await self.chat(
            build_messages(article, self.language)
        )
        summary = parse_summary_json(reply_text)
        logger.debug("gemini ok: %s", article.title[:60])
        return summary

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int | None = None,
    ) -> str:
        """Generate structured text from Gemini."""
        contents = []

        system_instruction = None

        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", ""))

            if role == "system":
                system_instruction = {
                    "parts": [{"text": content}]
                }
                continue

            gemini_role = "model" if role == "assistant" else "user"

            contents.append(
                {
                    "role": gemini_role,
                    "parts": [{"text": content}],
                }
            )

        payload = {
            "contents": contents,
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": max_tokens or self.max_tokens,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = system_instruction

        return await self._generate_with_retry(payload)

    async def _generate_with_retry(self, payload: dict) -> str:
        """Retry transient Gemini failures with short backoff."""
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
        """Perform one Gemini generateContent request."""
        url = (
            f"{self.base_url}/models/"
            f"{self.model}:generateContent"
        )

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        client_timeout = aiohttp.ClientTimeout(total=self.timeout)

        try:
            async with aiohttp.ClientSession(
                timeout=client_timeout
            ) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                ) as response:
                    body = await response.text()

                    if response.status >= 400:
                        raise LLMError(
                            f"HTTP {response.status}: {body[:500]}",
                            transient=response.status in _RETRY_STATUS,
                        )

        except aiohttp.ClientError as error:
            raise LLMError(
                f"network error: {error!r}",
                transient=True,
            ) from error

        return _extract_content(body)


def _extract_content(body: str) -> str:
    """Extract generated text from a Gemini response."""
    try:
        data = json.loads(body)

        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(
                f"Gemini returned no candidates: {body[:500]}"
            )

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )

        text_parts = [
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("text")
        ]

        result = "".join(text_parts).strip()

        if not result:
            raise LLMError(
                f"Gemini returned an empty response: {body[:500]}"
            )

        return result

    except json.JSONDecodeError as error:
        raise LLMError(
            f"invalid JSON response from Gemini: {body[:300]}"
        ) from error