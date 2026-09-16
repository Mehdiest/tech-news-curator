"""Parallel RSS fetching from config; feedparser runs inside a worker thread."""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import aiohttp
import feedparser

from src.models import Article, is_valid_image_url, looks_like_image_url, strip_html

logger = logging.getLogger(__name__)

USER_AGENT = "tech-news-curator/0.1 (+https://github.com/Mehdiest/tech-news-curator)"

_IMG_SRC_RE = re.compile(r"<img\b[^>]*?\bsrc=[\"\']([^\"\']+)[\"\']", re.IGNORECASE)


class RSSSource:
    """Fetches all configured feeds in parallel; a failing feed is isolated."""

    name = "rss"

    def __init__(self, feeds: list[dict], max_per_feed: int = 15, timeout: int = 20):
        if not feeds:
            raise ValueError("rss feed list is empty")
        self.feeds = feeds
        self.max_per_feed = max_per_feed
        self.timeout = timeout

    async def fetch(self) -> list[Article]:
        session_timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT}, timeout=session_timeout
        ) as session:
            tasks = [
                asyncio.create_task(self._fetch_one(session, feed))
                for feed in self.feeds
            ]
            feed_results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[Article] = []
        for feed, feed_result in zip(self.feeds, feed_results):
            if isinstance(feed_result, BaseException):
                logger.warning("rss %s failed: %r", feed["url"], feed_result)
                continue
            articles.extend(feed_result)
        logger.info("rss: %d articles from %d feeds", len(articles), len(self.feeds))
        return articles

    async def _fetch_one(self, session: aiohttp.ClientSession, feed: dict) -> list[Article]:
        async with session.get(feed["url"]) as response:
            response.raise_for_status()
            raw = await response.read()
        parsed = await asyncio.to_thread(feedparser.parse, raw)
        return self._parse_entries(parsed.entries, feed)

    def _parse_entries(self, entries: list, feed: dict) -> list[Article]:
        articles: list[Article] = []
        for entry in entries[: self.max_per_feed]:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or entry.get("id")
            if not title or not link:
                continue
            articles.append(self._entry_to_article(entry, feed, title, link))
        return articles

    def _entry_to_article(self, entry, feed: dict, title: str, link: str) -> Article:
        date_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        return Article(
            title=title,
            url=link,
            source=feed.get("name") or feed["url"],
            published_at=self._to_utc(date_struct),
            raw_summary=strip_html(entry.get("summary")),
            image_url=self._extract_image(entry, feed["url"]),
            meta={"category": feed.get("category", "general")},
        )

    @staticmethod
    def _extract_image(entry, feed_url: str) -> str | None:
        """Best image for the entry: media tags first, then inline <img> fallbacks."""
        for media in entry.get("media_content") or []:
            url = media.get("url") or ""
            typed = (
                media.get("medium") == "image"
                or str(media.get("type", "")).startswith("image")
            )
            if url and (typed or looks_like_image_url(url)):
                return RSSSource._resolve(url, feed_url)
        for media in entry.get("media_thumbnail") or []:
            url = media.get("url") or ""
            if url:
                return RSSSource._resolve(url, feed_url)
        for link in entry.get("links") or []:
            href = link.get("href") or ""
            if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
                return RSSSource._resolve(href, feed_url)
        for html_text in RSSSource._html_fragments(entry):
            match = _IMG_SRC_RE.search(html_text)
            if match:
                return RSSSource._resolve(match.group(1), feed_url)
        return None

    @staticmethod
    def _html_fragments(entry) -> list[str]:
        """Raw HTML bodies where an inline <img> may hide."""
        fragments = [entry.get("summary") or ""]
        for content in entry.get("content") or []:
            fragments.append(content.get("value") or "")
        return fragments

    @staticmethod
    def _resolve(url: str, feed_url: str) -> str | None:
        """Make the URL absolute, then keep only usable http(s) image links."""
        absolute = urljoin(feed_url, url.strip())
        return absolute if is_valid_image_url(absolute) else None

    @staticmethod
    def _to_utc(date_struct) -> datetime | None:
        if date_struct is None:
            return None
        # feedparser *_parsed structs are always UTC, hence timegm (not mktime)
        return datetime.fromtimestamp(calendar.timegm(date_struct), tz=timezone.utc)
