"""Image policy: pictures are a SECOND-OPTION feature, never a critical one.

Priority:
1. Images the sources officially provide with the story itself (RSS media
   tags, Reddit preview API) - attached by the fetchers, kept by default.
2. Open Graph / Twitter Card meta tags scraped from the publisher page -
   an OPT-IN fallback (pipeline.enrich_images, default off). It hotlinks
   the publisher's own image URL: some CDNs block that (hotlink protection)
   and embedding a media outlet's picture on your own domain is a copyright
   gray area. Enable only if you accept both risks.
3. A domain blocklist (pipeline.image_blocklist) drops image hosts that are
   unreachable for the audience - Reddit (redd.it) is filtered in Iran, so
   its hosted images would render broken for Iranian readers.

Nothing here can fail a publish run: dropped or missing images simply mean
the item renders as clean text-only content.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from urllib.parse import urlparse

import aiohttp

from src.models import Article, is_valid_image_url

logger = logging.getLogger(__name__)

USER_AGENT = "tech-news-curator/0.1 (+https://github.com/Mehdiest/tech-news-curator)"

_MAX_HTML_BYTES = 400_000  # og:image lives in <head>; no need for the whole page

# HEAD returns 405/501 on servers that only accept GET - that is not a broken image
_HEAD_UNUSUPPORTED_STATUS = frozenset({405, 501})

_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)

_WANTED_PROPERTIES = (
    "og:image",
    "og:image:secure_url",
    "twitter:image",
    "twitter:image:src",
)


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf'\b{name}=["\']([^"\']*)["\']', tag, re.IGNORECASE)
    return match.group(1) if match else None


def extract_og_image(page_html: str) -> str | None:
    """Return the first valid og:image / twitter:image URL in the HTML."""
    for tag in _META_TAG_RE.findall(page_html):
        prop = (_attr(tag, "property") or _attr(tag, "name") or "").lower()
        if prop not in _WANTED_PROPERTIES:
            continue
        candidate = _attr(tag, "content")
        if not candidate:
            continue
        candidate = html.unescape(candidate).strip()
        if is_valid_image_url(candidate):
            return candidate
    return None


async def _reachable_image(session: aiohttp.ClientSession, url: str) -> bool:
    """Cheap HEAD probe: True when the URL answers 200 with an image body."""
    try:
        async with session.head(url) as response:
            if response.status in _HEAD_UNUSUPPORTED_STATUS:
                return True  # HEAD unsupported; give the URL the benefit of the doubt
            if response.status != 200:
                return False
            content_type = response.headers.get("Content-Type", "")
            return not content_type or content_type.startswith("image/")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False


async def validate_image_url(session: aiohttp.ClientSession, url: str) -> str | None:
    """Return a working variant of the URL, or None when it is broken.

    Some CDNs 404 on the cache-busting query their own og:image carries
    (Apple newsroom does exactly this), so the queryless form is retried once.
    """
    if await _reachable_image(session, url):
        return url
    without_query = url.split("?", 1)[0]
    if without_query != url and await _reachable_image(session, without_query):
        logger.info("image validated without query string: %s", without_query)
        return without_query
    return None


def drop_blocked_images(articles: list[Article], blocklist: list[str] | None) -> int:
    """Detach image URLs whose host matches a blocklist suffix; return the count.

    Suffix matching is on full domain labels ("redd.it" drops
    preview.redd.it / b.thumbs.redd.it but not "notredd.it.com"). Dropped
    items just render text-only - never an error, images are optional.
    """
    if not blocklist:
        return 0
    suffixes = tuple(
        "." + str(domain).lower().strip(".") for domain in blocklist if str(domain).strip(".")
    )
    if not suffixes:
        return 0
    dropped = 0
    for article in articles:
        if not article.image_url:
            continue
        host = (urlparse(article.image_url).hostname or "").lower()
        if host.endswith(suffixes):
            logger.info("image dropped by blocklist (%s): %s", host, article.image_url)
            article.image_url = None
            dropped += 1
    return dropped


async def fetch_page_image(
    session: aiohttp.ClientSession, page_url: str, timeout: int = 10
) -> str | None:
    """Fetch the article page and pull its lead image out of the meta tags."""
    try:
        async with session.get(page_url) as response:
            if response.status != 200:
                logger.debug("image skip %s: HTTP %d", page_url, response.status)
                return None
            content_type = response.headers.get("Content-Type", "")
            if content_type.startswith("image/"):
                # direct image link (e.g. a blog post that IS a picture)
                return page_url
            if content_type and "html" not in content_type:
                return None  # PDFs, podcasts, anything without meta tags
            raw = await response.content.read(_MAX_HTML_BYTES)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.debug("image fetch failed for %s: %r", page_url, exc)
        return None
    return extract_og_image(raw.decode("utf-8", errors="ignore"))


async def enrich_images(
    articles: list[Article], concurrency: int = 4, timeout: int = 10
) -> int:
    """OPT-IN fallback: fill missing image_url fields from publisher meta tags.

    Only called when pipeline.enrich_images is enabled - it hotlinks the
    publisher's image (hotlink protection and copyright gray area, see the
    module docstring). Articles that already carry an image are left
    untouched. Extracted meta-tag URLs are HEAD-validated before being
    attached, and any single failing page is isolated - enrichment never
    raises, never blocks long.
    """
    targets = [article for article in articles if not article.image_url]
    if not targets:
        return 0
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(
        headers={"User-Agent": USER_AGENT}, timeout=timeout_cfg
    ) as session:
        semaphore = asyncio.Semaphore(concurrency)

        async def worker(article: Article) -> int:
            async with semaphore:
                image_url = await fetch_page_image(session, article.url, timeout)
                if image_url:
                    image_url = await validate_image_url(session, image_url)
            if image_url and is_valid_image_url(image_url):
                article.image_url = image_url
                return 1
            return 0

        results = await asyncio.gather(*(worker(a) for a in targets))
    found = sum(results)
    logger.info("images: %d/%d articles enriched from page meta tags", found, len(targets))
    return found
