"""Hacker News top stories via the Algolia HN API - free, no API key."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiohttp

from src.models import Article, utc_now

logger = logging.getLogger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class HNSource:
    """Fetches the HN front page or the top stories of the last 24 hours."""

    name = "hackernews"

    def __init__(
        self,
        mode: str = "front_page",
        min_points: int = 50,
        max_items: int = 30,
        timeout: int = 20,
    ):
        self.mode = mode
        self.min_points = min_points
        self.max_items = max_items
        self.timeout = timeout

    async def fetch(self) -> list[Article]:
        session_timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            async with session.get(HN_SEARCH_URL, params=self._build_params()) as response:
                response.raise_for_status()
                hits = (await response.json()).get("hits", [])

        articles = [
            article for hit in hits if (article := self._hit_to_article(hit)) is not None
        ]
        if self.mode == "top_day":
            articles.sort(key=lambda article: article.signal_score, reverse=True)
        articles = articles[: self.max_items]
        logger.info("hn/%s: %d articles", self.mode, len(articles))
        return articles

    def _build_params(self) -> dict:
        if self.mode == "top_day":
            since_epoch = int((utc_now() - timedelta(hours=24)).timestamp())
            return {
                "tags": "story",
                "numericFilters": f"created_at_i>{since_epoch},points>{self.min_points}",
                "hitsPerPage": 100,
            }
        return {"tags": "front_page", "hitsPerPage": 50}

    def _hit_to_article(self, hit: dict) -> Article | None:
        title = (hit.get("title") or "").strip()
        points = float(hit.get("points") or 0)
        if not title or points < self.min_points:
            return None
        return Article(
            title=title,
            url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
            source="HackerNews",
            published_at=self._hit_datetime(hit),
            signal_score=points,
            meta={
                "num_comments": hit.get("num_comments", 0),
                "hn_id": hit.get("objectID"),
                "category": "hn",
            },
        )

    @staticmethod
    def _hit_datetime(hit: dict) -> datetime | None:
        if "created_at_i" not in hit:
            return None
        return datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
