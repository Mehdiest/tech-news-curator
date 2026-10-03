"""Google Gemini provider using the generateContent REST API."""

from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from src.llm.base import LLMError, Summary, parse_summary_json
from src.llm.prompts import build_messages
from src.models import Article

logger = logging.getLogger(__name__)

_RETRY_STATUS = {408, 500, 502, 503, 504}
_RETRY_DELAY_SECONDS = 2.0


class GeminiProvider:
    """Call Google's Gemini generateContent endpoint."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        base_url: str = (
            "https://generativelanguage.googleapis.com/v1beta"
        ),
        temperature: float = 0.7,
        max_tokens: int = 12000,
        timeout: int = 60,
        language: str = "en",
        max_attempts: int = 1,
    ):
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        # Keep the language attribute for compatibility with the provider
        # interface used by the existing pipeline.
        self.language = language

        # Quota failures must not be retried. One daily batch request should
        # remain one request even when the free-tier quota is exhausted.
        self.max_attempts = max(1, max_attempts)

        if not self.api_key:
            raise ValueError(
                "api_key is empty - set GEMINI_API_KEY"
            )

    async def summarize(
        self,
        article: Article,
    ) -> Summary:
        """Generate one structured digest summary for an article."""

        reply = await self.chat(
            build_messages(
                article,
                self.language,
            )
        )

        return parse_summary_json(reply)

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int | None = None,
    ) -> str:
        """Generate structured JSON text from Gemini."""

        contents: list[dict] = []
        system_instruction = None

        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", ""))

            if role == "system":
                system_instruction = {
                    "parts": [
                        {"text": content},
                    ],
                }
                continue

            contents.append(
                {
                    "role": (
                        "model"
                        if role == "assistant"
                        else "user"
                    ),
                    "parts": [
                        {"text": content},
                    ],
                }
            )

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "responseMimeType": "application/json",
                "maxOutputTokens": (
                    max_tokens
                    if max_tokens is not None
                    else self.max_tokens
                ),
            },
        }

        if system_instruction:
            payload["systemInstruction"] = system_instruction

        for attempt in range(1, self.max_attempts + 1):
            try:
                return await self._post(payload)

            except LLMError as error:
                if (
                    attempt >= self.max_attempts
                    or not error.transient
                ):
                    raise

                logger.warning(
                    "Gemini transient error (%d/%d): %s",
                    attempt,
                    self.max_attempts,
                    error,
                )

                await asyncio.sleep(
                    _RETRY_DELAY_SECONDS * attempt
                )

        raise LLMError(
            "unreachable Gemini retry state"
        )

    async def _post(
        self,
        payload: dict,
    ) -> str:
        """Send one generateContent request and extract generated text."""

        url = (
            f"{self.base_url}/models/"
            f"{self.model}:generateContent"
        )

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        timeout = aiohttp.ClientTimeout(
            total=self.timeout,
        )

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
            ) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                ) as response:
                    body = await response.text()

                    if response.status >= 400:
                        raise LLMError(
                            (
                                f"HTTP {response.status}: "
                                f"{body[:800]}"
                            ),
                            transient=(
                                response.status
                                in _RETRY_STATUS
                            ),
                        )

        except asyncio.TimeoutError as error:
            raise LLMError(
                "Gemini request timed out",
                transient=True,
            ) from error

        except aiohttp.ClientError as error:
            raise LLMError(
                f"Gemini network error: {error!r}",
                transient=True,
            ) from error

        try:
            data = json.loads(body)

        except json.JSONDecodeError as error:
            raise LLMError(
                f"invalid Gemini JSON response: {body[:300]}"
            ) from error

        candidates = data.get("candidates") or []

        if not candidates:
            raise LLMError(
                f"Gemini returned no candidates: {body[:500]}"
            )

        candidate = candidates[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []

        result = "".join(
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict)
            and part.get("text")
        ).strip()

        if not result:
            finish_reason = candidate.get(
                "finishReason",
                "UNKNOWN",
            )

            raise LLMError(
                (
                    "Gemini returned an empty response. "
                    f"Finish reason: {finish_reason}"
                )
            )

        return result