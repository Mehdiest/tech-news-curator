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

# Batch-level retry policy for translations: LLM sampling is random, so a
# pair that failed once (bad JSON, hiccup, rate limit) often succeeds on a
# later round. Failed pairs are retried retry_rounds extra times with a
# growing delay; a pair that succeeded once is never called again.
TRANSLATION_RETRY_ROUNDS = 2
_TRANSLATION_RETRY_DELAY_SECONDS = 3.0
# Languages per translation chat call. The prompt/parser are multi-target,
# so one call can carry several languages; 4 keeps a 9-language day at
# items x (1 + 2) requests - inside OpenRouter's 50/day free-model quota.
TRANSLATION_CHUNK_SIZE = 4


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
    max_tokens: int = 3000,
    retry_rounds: int = TRANSLATION_RETRY_ROUNDS,
    chunk_size: int = TRANSLATION_CHUNK_SIZE,
) -> int:
    """Translate summarized items into extra languages, in place.

    One chat call per (item, chunk of <=chunk_size languages) instead of one
    per (item, language): build_translation_messages and parse_translation_json
    are multi-target already, and a 9-language day used to cost
    items x (1 summarize + 8 translations) ~ 60+ requests - over the 50/day
    free-model quota on OpenRouter before the day's post was even half done.
    With chunk_size=4 a 7-item day needs 7 + 2x7 = 21 requests, safely inside
    the quota. The source text is always the finished English version, so the
    author's voice lands identically in every edition.

    parse_translation_json tolerates per-language gaps, so a truncated reply
    keeps the languages it did deliver; every retry round re-groups only the
    still-missing languages into fresh chunks (growing delay), so a transient
    model hiccup never strands a whole edition in English. Returns how many
    (item, language) pairs succeeded.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    def _chunks(langs: list[str]) -> list[list[str]]:
        return [langs[i:i + chunk_size] for i in range(0, len(langs), chunk_size)]

    async def _one(item: CuratedItem, codes: list[str]) -> int:
        async with semaphore:
            entry = {
                "title": item.article.title,
                "summary": item.llm_summary,
                "take": item.personal_take,
            }
            # Longer outputs need a proportionally higher cap: each extra
            # language adds roughly a title + summary + take to the reply.
            call_tokens = max_tokens + 500 * (len(codes) - 1)
            try:
                reply = await provider.chat(
                    build_translation_messages(entry, codes), max_tokens=call_tokens,
                )
                parsed = parse_translation_json(reply, codes)
                fresh = [c for c in parsed if c not in item.translations]
                item.translations.update(parsed)
                return len(fresh)
            except LLMError as error:
                logger.warning(
                    "translation %s failed for %r: %s",
                    "/".join(codes), item.article.title[:50], error,
                )
            except Exception as error:  # isolation boundary, never crash the batch
                logger.warning(
                    "translation %s crashed for %r: %r",
                    "/".join(codes), item.article.title[:50], error,
                )
            return 0

    def _pending() -> list[tuple[CuratedItem, list[str]]]:
        return [
            (item, codes)
            for item in items
            for codes in _chunks([c for c in targets if c not in item.translations])
        ]

    total_pairs = len(items) * len(targets)
    ok = 0
    for round_index in range(max(1, retry_rounds + 1)):
        pending = _pending()
        if not pending:
            break
        if round_index:
            logger.info(
                "translations: retry round %d for %d chunk(s)",
                round_index, len(pending),
            )
            await asyncio.sleep(_TRANSLATION_RETRY_DELAY_SECONDS * round_index)
        results = await asyncio.gather(*(_one(item, codes) for item, codes in pending))
        ok += sum(results)
    logger.info(
        "translations: %d/%d (item, language) pairs succeeded", ok, total_pairs,
    )
    return ok
