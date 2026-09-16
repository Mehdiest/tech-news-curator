"""Common protocol implemented by every ingestion source."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.models import Article


@runtime_checkable
class SourceFetcher(Protocol):
    """Contract: async fetch() -> list[Article]."""

    name: str

    async def fetch(self) -> list[Article]:
        ...
