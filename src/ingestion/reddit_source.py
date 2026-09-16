"""Reddit public JSON API - top or hot posts of the configured subreddits."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone

import aiohttp

from src.models import Article, strip_html

logger = logging.getLogger(__name__)

USER_AGENT = "tech-news-curator/0.1 (+https://github.com/Mehdiest/tech-news-curator)"
REDDIT_LISTINGS = ("top", "hot")


class RedditSource:
    """Fetches all configured subreddits in parallel; a failing subreddit is isolated."""

    name = "reddit"

    def __init__(
        self,
        subreddits: list[dict],
        listing: str = "top",
        time_range: str = "day",
        min_score: int = 20,
        max_per_sub: int = 25,
        timeout: int = 20,
    ):
        if not subreddits:
            raise ValueError("subreddit list is empty")
        if listing not in REDDIT_LISTINGS:
            raise ValueError(f"listing must be one of {REDDIT_LISTINGS}")
        self.subreddits = subreddits
        self.listing = listing
        self.time_range = time_range
        self.min_score = min_score
        self.max_per_sub = max_per_sub
        self.timeout = timeout

    async def fetch(self) -> list[Article]:
        session_timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT}, timeout=session_timeout
        ) as session:
            tasks = [
                asyncio.create_task(self._fetch_sub(session, sub))
                for sub in self.subreddits
            ]
            sub_results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[Article] = []
        for sub, sub_result in zip(self.subreddits, sub_results):
            if isinstance(sub_result, BaseException):
                logger.warning("reddit r/%s failed: %r", sub["name"], sub_result)
                continue
            articles.extend(sub_result)
        logger.info(
            "reddit: %d articles from %d subreddits", len(articles), len(self.subreddits)
        )
        return articles

    async def _fetch_sub(self, session: aiohttp.ClientSession, sub: dict) -> list[Article]:
        listing_url = f"https://www.reddit.com/r/{sub['name']}/{self.listing}.json"
        params = {"limit": self.max_per_sub}
        if self.listing == "top":
            params["t"] = self.time_range
        async with session.get(listing_url, params=params) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        children = payload.get("data", {}).get("children", [])
        return [
            article
            for child in children
            if (article := self._post_to_article(child.get("data", {}), sub)) is not None
        ]

    def _post_to_article(self, post: dict, sub: dict) -> Article | None:
        title = (post.get("title") or "").strip()
        score = float(post.get("score") or 0)
        if not title or post.get("stickied") or score < self.min_score:
            return None
        return Article(
            title=title,
            url=self._post_url(post),
            source=f"r/{sub['name']}",
            published_at=self._post_datetime(post),
            raw_summary=self._post_summary(post),
            signal_score=score,
            image_url=self._post_image(post),
            meta={
                "num_comments": post.get("num_comments", 0),
                "subreddit": sub["name"],
                "category": sub.get("category", "general"),
            },
        )

    @staticmethod
    def _post_image(post: dict) -> str | None:
        """High-res preview image first, then the small thumbnail fallback."""
        images = post.get("preview", {}).get("images", []) or []
        source_url = (images[0].get("source", {}) if images else {}).get("url") or ""
        if source_url:
            # Reddit JSON embeds HTML-escaped query strings in media URLs
            return html.unescape(source_url)
        thumbnail = post.get("thumbnail") or ""
        if thumbnail.startswith("http"):
            return thumbnail
        return None

    @staticmethod
    def _post_url(post: dict) -> str:
        permalink = post.get("permalink") or ""
        if post.get("is_self") or not post.get("url"):
            return f"https://www.reddit.com{permalink}"
        return post["url"]

    @staticmethod
    def _post_datetime(post: dict) -> datetime | None:
        created = post.get("created_utc")
        if not created:
            return None
        return datetime.fromtimestamp(created, tz=timezone.utc)

    @staticmethod
    def _post_summary(post: dict) -> str | None:
        if post.get("is_self") and post.get("selftext"):
            return strip_html(post["selftext"], max_len=300)
        return None
