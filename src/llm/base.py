"""Abstract LLM interface - swap providers without touching the rest of the pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Protocol

from src.llm.prompts import build_translation_messages
from src.models import Article, CuratedItem

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Any provider failure: HTTP, network, or malformed reply.

    transient=True hints that an immediate retry may succeed (429/5xx/timeout).
    """

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


@dataclass
class Summary:
    """Standard output of every provider."""

    llm_summary: str    # 2-4 sentence factual summary
    personal_take: str  # short comedic expert commentary


class LLMProvider(Protocol):
    """Contract: summarize(article) -> Summary, plus generic chat()."""

    async def summarize(self, article: Article) -> Summary:
        ...

    async def chat(self, messages: list[dict], max_tokens: int | None = None) -> str:
        """One OpenAI-style completion; used by translate_batch."""
        ...


def parse_summary_json(text: str) -> Summary:
    """Parse the model reply into a Summary; tolerates fences and stray prose."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError(f"no JSON object in reply: {text[:120]!r}")
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError as error:
        raise LLMError(f"invalid JSON from model: {error}") from error
    summary = str(data.get("summary", "")).strip()
    take = str(data.get("take", "")).strip()
    if not summary or not take:
        raise LLMError(f"missing summary/take fields in: {text[:120]!r}")
    return Summary(llm_summary=summary, personal_take=take)


def parse_translation_json(text: str, targets: list[str]) -> dict[str, dict[str, str]]:
    """Parse a multi-language reply; tolerates fences and per-language gaps.

    A language whose block is missing or incomplete is simply absent from the
    result (the writer falls back to English for it); a reply with no usable
    language at all raises LLMError so the caller can retry or isolate.
    """
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError(f"no JSON object in reply: {text[:120]!r}")
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError as error:
        raise LLMError(f"invalid JSON from model: {error}") from error
    translations: dict[str, dict[str, str]] = {}
    for code in targets:
        block = data.get(code) if isinstance(data, dict) else None
        if not isinstance(block, dict):
            continue
        title = str(block.get("title", "")).strip()
        summary = str(block.get("summary", "")).strip()
        take = str(block.get("take", "")).strip()
        if summary and take:
            translations[code] = {"title": title, "summary": summary, "take": take}
    if not translations:
        raise LLMError(f"no usable translation in reply: {text[:120]!r}")
    return translations


async def summarize_batch(
    provider: LLMProvider, articles: list[Article], concurrency: int = 3,
) -> list[tuple[Article, Summary | None]]:
    """Summarize with bounded parallelism; a failing article becomes None."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(article: Article) -> tuple[Article, Summary | None]:
        async with semaphore:
            try:
                return article, await provider.summarize(article)
            except LLMError as error:
                logger.warning("llm failed for %r: %s", article.title[:60], error)
                return article, None
            except Exception as error:  # isolation boundary, never crash the batch
                logger.warning("llm crashed for %r: %r", article.title[:60], error)
                return article, None

    return list(await asyncio.gather(*(_one(article) for article in articles)))


async def translate_batch(
    provider: LLMProvider,
    items: list[CuratedItem],
    targets: list[str],
    concurrency: int = 3,
    max_tokens: int = 800,
) -> int:
    """Translate summarized items into extra languages, in place.

    One SMALL chat call per (item, language) pair: short replies keep the
    strict-JSON contract reliable, and a failing pair costs exactly one
    language of one item - every other edition keeps its translation. The
    source text is always the finished English version, so the author's
    voice lands identically in every edition. Returns how many
    (item, language) pairs succeeded.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))
    pairs = [(item, code) for item in items for code in targets]

    async def _one(item: CuratedItem, code: str) -> bool:
        async with semaphore:
            entry = {
                "title": item.article.title,
                "summary": item.llm_summary,
                "take": item.personal_take,
            }
            try:
                reply = await provider.chat(
                    build_translation_messages(entry, [code]), max_tokens=max_tokens,
                )
                item.translations.update(parse_translation_json(reply, [code]))
                return True
            except LLMError as error:
                logger.warning(
                    "translation %s failed for %r: %s",
                    code, item.article.title[:50], error,
                )
            except Exception as error:  # isolation boundary, never crash the batch
                logger.warning(
                    "translation %s crashed for %r: %r",
                    code, item.article.title[:50], error,
                )
            return False

    results = await asyncio.gather(*(_one(item, code) for item, code in pairs))
    ok = sum(1 for done in results if done)
    logger.info("translations: %d/%d (item, language) pairs succeeded", ok, len(pairs))
    return ok
