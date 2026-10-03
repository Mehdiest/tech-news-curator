"""Shared LLM contracts, parsers, and low-request batch operations."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Protocol

from src.llm.prompts import (
build_batch_summary_messages,
build_batch_translation_messages,
)
from src.models import Article, CuratedItem

logger = logging.getLogger(**name**)

class LLMError(Exception):
"""Provider failure: HTTP, network, quota, or malformed model output."""

```
def __init__(self, message: str, transient: bool = False):
    super().__init__(message)
    self.transient = transient
```

@dataclass
class Summary:
"""Standard output of every provider."""

```
llm_summary: str
personal_take: str
```

class LLMProvider(Protocol):
"""Provider contract used by the pipeline."""

```
name: str
model: str

async def summarize(self, article: Article) -> Summary:
    ...

async def chat(
    self,
    messages: list[dict],
    max_tokens: int | None = None,
) -> str:
    ...
```

def _json_object(text: str) -> dict:
"""Extract the outer JSON object from a model response."""

````
cleaned = text.strip()

if cleaned.startswith("```"):
    lines = cleaned.splitlines()

    if lines and lines[0].startswith("```"):
        lines = lines[1:]

    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    cleaned = "\n".join(lines).strip()

start = cleaned.find("{")
end = cleaned.rfind("}")

if start == -1 or end <= start:
    raise LLMError(
        f"no JSON object in reply: {text[:160]!r}"
    )

try:
    data = json.loads(cleaned[start:end + 1])
except json.JSONDecodeError as error:
    raise LLMError(
        f"invalid JSON from model: {error}"
    ) from error

if not isinstance(data, dict):
    raise LLMError("model JSON root must be an object")

return data
````

def parse_summary_json(text: str) -> Summary:
"""Parse one summary response."""

```
data = _json_object(text)

summary = str(data.get("summary", "")).strip()
take = str(data.get("take", "")).strip()

if not summary or not take:
    raise LLMError(
        f"missing summary/take fields in: {text[:160]!r}"
    )

return Summary(
    llm_summary=summary,
    personal_take=take,
)
```

def parse_summary_batch_json(
text: str,
expected: int,
) -> dict[int, Summary]:
"""Parse a batch summary response keyed by article index."""

```
data = _json_object(text)
rows = data.get("items")

if not isinstance(rows, list):
    raise LLMError(
        "batch summary response has no items array"
    )

parsed: dict[int, Summary] = {}

for row in rows:
    if not isinstance(row, dict):
        continue

    try:
        index = int(row.get("index"))
    except (TypeError, ValueError):
        continue

    if not 1 <= index <= expected:
        continue

    summary = str(row.get("summary", "")).strip()
    take = str(row.get("take", "")).strip()

    if summary and take:
        parsed[index] = Summary(
            llm_summary=summary,
            personal_take=take,
        )

if not parsed:
    raise LLMError(
        "batch summary response contained no usable items"
    )

return parsed
```

def parse_translation_json(
text: str,
targets: list[str],
) -> dict[str, dict[str, str]]:
"""Parse a single-item translation response."""

```
data = _json_object(text)
translations: dict[str, dict[str, str]] = {}

for code in targets:
    block = data.get(code)

    if not isinstance(block, dict):
        continue

    title = str(block.get("title", "")).strip()
    summary = str(block.get("summary", "")).strip()
    take = str(block.get("take", "")).strip()

    if title and summary and take:
        translations[code] = {
            "title": title,
            "summary": summary,
            "take": take,
        }

if not translations:
    raise LLMError(
        "no usable translation in reply"
    )

return translations
```

def parse_translation_batch_json(
text: str,
targets: list[str],
expected: int,
) -> dict[int, dict[str, dict[str, str]]]:
"""Parse all translated items from one batch response."""

```
data = _json_object(text)
rows = data.get("items")

if not isinstance(rows, list):
    raise LLMError(
        "batch translation response has no items array"
    )

parsed: dict[int, dict[str, dict[str, str]]] = {}

for row in rows:
    if not isinstance(row, dict):
        continue

    try:
        index = int(row.get("index"))
    except (TypeError, ValueError):
        continue

    if not 1 <= index <= expected:
        continue

    blocks = row.get("translations")

    if not isinstance(blocks, dict):
        continue

    item_translations: dict[str, dict[str, str]] = {}

    for code in targets:
        block = blocks.get(code)

        if not isinstance(block, dict):
            continue

        title = str(block.get("title", "")).strip()
        summary = str(block.get("summary", "")).strip()
        take = str(block.get("take", "")).strip()

        if title and summary and take:
            item_translations[code] = {
                "title": title,
                "summary": summary,
                "take": take,
            }

    if item_translations:
        parsed[index] = item_translations

if not parsed:
    raise LLMError(
        "batch translation response contained no usable items"
    )

return parsed
```

def _is_transient_error(error: Exception) -> bool:
"""Return whether an error is likely to succeed when retried."""

```
if isinstance(error, LLMError):
    return error.transient

message = str(error).lower()

transient_markers = (
    "http 408",
    "http 409",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "408",
    "429",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "connection reset",
    "connection aborted",
    "connection refused",
    "server disconnected",
    "temporary failure",
)

return any(marker in message for marker in transient_markers)
```

async def _chat_with_retries(
provider: LLMProvider,
messages: list[dict],
max_tokens: int | None,
*,
retry_rounds: int = 3,
initial_delay: float = 2.0,
) -> str:
"""Call the provider and retry transient failures with exponential backoff."""

```
attempts = max(0, retry_rounds) + 1

for attempt in range(1, attempts + 1):
    try:
        return await provider.chat(
            messages,
            max_tokens=max_tokens,
        )

    except Exception as error:
        if attempt >= attempts or not _is_transient_error(error):
            raise

        delay = initial_delay * (2 ** (attempt - 1))

        logger.warning(
            "transient LLM failure on attempt %d/%d: %s; "
            "retrying in %.1f seconds",
            attempt,
            attempts,
            error,
            delay,
        )

        await asyncio.sleep(delay)

raise RuntimeError("unreachable retry state")
```

async def summarize_batch(
provider: LLMProvider,
articles: list[Article],
concurrency: int = 1,
retry_rounds: int = 3,
) -> list[tuple[Article, Summary | None]]:
"""Summarize all selected articles in one provider request."""

```
if not articles:
    return []

try:
    reply = await _chat_with_retries(
        provider,
        build_batch_summary_messages(articles),
        max_tokens=max(700, 900 * len(articles)),
        retry_rounds=retry_rounds,
    )

    parsed = parse_summary_batch_json(
        reply,
        len(articles),
    )

except Exception as error:
    logger.warning(
        "batch summarization failed: %s",
        error,
    )
    return [
        (article, None)
        for article in articles
    ]

result: list[tuple[Article, Summary | None]] = []

for index, article in enumerate(articles, 1):
    summary = parsed.get(index)

    if summary is None:
        logger.warning(
            "batch summary missing for %r",
            article.title[:60],
        )

    result.append(
        (article, summary)
    )

logger.info(
    "summaries: %d/%d articles completed in one request",
    sum(summary is not None for _, summary in result),
    len(articles),
)

return result
```

async def translate_batch(
provider: LLMProvider,
items: list[CuratedItem],
targets: list[str],
concurrency: int = 1,
max_tokens: int = 12000,
retry_rounds: int = 3,
chunk_size: int = 0,
) -> int:
"""Translate all selected items and languages in one provider request."""

```
targets = [
    code.strip().lower()
    for code in dict.fromkeys(targets)
    if code and code.strip().lower() != "en"
]

if not items or not targets:
    return 0

payload = [
    {
        "index": index,
        "title": item.article.title,
        "summary": item.llm_summary,
        "take": item.personal_take,
    }
    for index, item in enumerate(items, 1)
]

try:
    reply = await _chat_with_retries(
        provider,
        build_batch_translation_messages(
            payload,
            targets,
        ),
        max_tokens=max_tokens,
        retry_rounds=retry_rounds,
    )

    parsed = parse_translation_batch_json(
        reply,
        targets,
        len(items),
    )

except Exception as error:
    logger.error(
        "batch translations failed: %s",
        error,
    )
    return 0

successful_pairs = 0

for index, translations in parsed.items():
    item = items[index - 1]
    item.translations.update(translations)
    successful_pairs += len(translations)

total_pairs = len(items) * len(targets)

logger.info(
    "translations: %d/%d pairs succeeded in one request",
    successful_pairs,
    total_pairs,
)

return successful_pairs



