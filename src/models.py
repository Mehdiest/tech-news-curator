"""Unified article schema shared by all sources, plus URL/text normalization helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "utm_id", "ref", "ref_src", "ref_url",
    "fbclid", "gclid", "mc_cid", "mc_eid",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|avif)(?:[?#]|$)", re.IGNORECASE)


def is_valid_image_url(url: str | None) -> bool:
    """True when the URL is a well-formed http(s) link usable as an image src."""
    if not url or len(url) > 2000:
        return False
    url = url.strip()
    if url.lower().startswith("data:"):
        return False
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def looks_like_image_url(url: str) -> bool:
    """Heuristic: the URL path ends in a common raster image extension."""
    return bool(_IMAGE_EXT_RE.search(url))


def normalize_url(url: str) -> str:
    """Return a stable URL form for dedup: drop tracking params and fragment."""
    parts = urlsplit(url.strip())
    clean_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ]
    return urlunsplit((
        parts.scheme.lower() or "https",
        parts.netloc.lower(),
        parts.path or "/",
        urlencode(clean_query),
        "",
    ))


def strip_html(text: str | None, max_len: int = 600) -> str | None:
    """Strip HTML tags, collapse whitespace, and truncate to max_len."""
    if not text:
        return None
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "..."
    return text or None


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class Article:
    """Source-agnostic representation of a single news item."""

    id: str = field(init=False)               # sha1 of canonical URL; dedup key
    title: str
    url: str
    source: str                               # e.g. "TechCrunch", "HackerNews"
    published_at: datetime | None = None
    raw_summary: str | None = None
    signal_score: float = 0.0                 # HN points / Reddit ups; plain RSS = 0
    image_url: str | None = None              # lead picture for the digest, if any
    meta: dict = field(default_factory=dict)  # extra signals: num_comments, category, ...

    def __post_init__(self) -> None:
        if self.published_at is not None and self.published_at.tzinfo is None:
            self.published_at = self.published_at.replace(tzinfo=timezone.utc)
        self.id = hashlib.sha1(normalize_url(self.url).encode("utf-8")).hexdigest()

    @property
    def canonical_url(self) -> str:
        return normalize_url(self.url)


@dataclass
class CuratedItem:
    """Final output after the LLM layer; this is what gets published."""

    article: Article
    llm_summary: str
    personal_take: str
    rank_score: float = 0.0
    # Stage 7: language code -> {"title", "summary", "take"} in that language.
    # Missing languages fall back to the English text when rendering.
    translations: dict = field(default_factory=dict)
