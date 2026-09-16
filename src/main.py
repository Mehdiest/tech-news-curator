"""Pipeline orchestration: ingestion (RSS/HN/Reddit) + dedup + ranking + LLM preview."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.ingestion.hn_source import HNSource
from src.ingestion.reddit_source import RedditSource
from src.ingestion.rss_source import RSSSource
from src.llm.base import summarize_batch, translate_batch
from src.llm.factory import make_provider
from src.models import Article, CuratedItem
from src.pipeline.dedup import dedupe
from src.pipeline.images import drop_blocked_images, enrich_images
from src.pipeline.ranker import Ranker, RankerConfig
from src.publish.markdown_writer import existing_editions, load_i18n, write_digest

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"
I18N_PATH = Path(__file__).resolve().parent.parent / "config" / "i18n.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Read sources.yaml."""
    with open(path, encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def build_sources(cfg: dict, only: str | None = None) -> list:
    """Instantiate fetchers from config."""
    pipeline_cfg = cfg.get("pipeline", {})
    sources = []
    if only in (None, "rss") and cfg.get("rss"):
        sources.append(RSSSource(
            feeds=cfg["rss"],
            max_per_feed=pipeline_cfg.get("max_per_feed", 15),
            timeout=pipeline_cfg.get("request_timeout", 20),
        ))
    if only in (None, "hn") and cfg.get("hn"):
        hn_cfg = cfg["hn"]
        sources.append(HNSource(
            mode=hn_cfg.get("mode", "front_page"),
            min_points=hn_cfg.get("min_points", 50),
            max_items=hn_cfg.get("max_items", 30),
            timeout=pipeline_cfg.get("request_timeout", 20),
        ))
    if only in (None, "reddit") and cfg.get("reddit"):
        reddit_cfg = cfg["reddit"]
        sources.append(RedditSource(
            subreddits=reddit_cfg.get("subreddits", []),
            listing=reddit_cfg.get("listing", "top"),
            time_range=reddit_cfg.get("time_range", "day"),
            min_score=reddit_cfg.get("min_score", 20),
            max_per_sub=reddit_cfg.get("max_per_sub", 25),
            timeout=pipeline_cfg.get("request_timeout", 20),
        ))
    return sources


def _print_digest(ranked: list[Article], limit: int) -> None:
    """Print the ranked digest with the per-component score breakdown."""
    print(f"\n=== Top {limit} ===\n")
    for rank, article in enumerate(ranked[:limit], 1):
        published = (
            article.published_at.strftime("%m-%d %H:%M")
            if article.published_at else "n/a"
        )
        parts = article.meta.get("score_parts", {})
        breakdown = " ".join(f"{name}={value:.1f}" for name, value in parts.items())
        print(f"{rank:2d}. [{article.source}] {article.title}")
        print(f"    {article.url}")
        print(f"    score={article.meta.get('rank_score', 0.0):.1f}  "
              f"coverage={article.meta.get('coverage', 1)}  "
              f"signal={article.signal_score:.0f}  "
              f"published={published} UTC")
        if breakdown:
            print(f"    parts: {breakdown}")
        print()


async def _collect_ranked(cfg: dict, only: str | None) -> list[Article]:
    """Fetch from all sources, dedup, and rank - the front half of the pipeline."""
    sources = build_sources(cfg, only)
    if not sources:
        logger.error("no sources configured for only=%s", only)
        return []

    fetch_results = await asyncio.gather(
        *(source.fetch() for source in sources), return_exceptions=True
    )

    articles: list[Article] = []
    for source, fetch_result in zip(sources, fetch_results):
        if isinstance(fetch_result, BaseException):
            logger.error("source %s failed: %r", source.name, fetch_result)
            continue
        logger.info("%-11s -> %3d articles", source.name, len(fetch_result))
        articles.extend(fetch_result)

    unique_articles = dedupe(
        articles,
        title_similarity=cfg.get("pipeline", {}).get("title_similarity", 0.85),
    )
    logger.info("raw=%d unique=%d", len(articles), len(unique_articles))
    if not unique_articles:
        logger.warning("0 articles fetched - check network or feed list")
        return []
    ranker = Ranker(RankerConfig.from_config(cfg.get("ranker")))
    return ranker.rank(unique_articles)


async def run_preview(cfg: dict, only: str | None, limit: int) -> None:
    """Fetch, rank, and print the top N without calling the LLM."""
    ranked = await _collect_ranked(cfg, only)
    if ranked:
        _print_digest(ranked, limit)


def _print_summaries(pairs: list) -> None:
    """Print summary + take for every successfully summarized article."""
    print("\n=== LLM digest preview ===\n")
    for index, (article, summary) in enumerate(pairs, 1):
        print(f"{index:2d}. [{article.source}] {article.title}")
        print(f"    {article.url}")
        if summary is None:
            print("    (summarization failed - see warnings above)")
        else:
            print(f"    SUMMARY: {summary.llm_summary}")
            print(f"    TAKE: {summary.personal_take}")
        print()


async def run_summarize(cfg: dict, only: str | None, limit: int) -> None:
    """Fetch, rank, then summarize the top N with the configured LLM."""
    ranked = await _collect_ranked(cfg, only)
    if not ranked:
        return
    provider = make_provider()
    logger.info("llm provider=%s model=%s", provider.name, provider.model)
    pairs = await summarize_batch(provider, ranked[:limit])
    _print_summaries(pairs)


def _to_curated_items(pairs: list) -> list[CuratedItem]:
    """Drop failed summaries; carry the rank score into CuratedItem."""
    items = []
    for article, summary in pairs:
        if summary is None:
            continue
        items.append(CuratedItem(
            article=article,
            llm_summary=summary.llm_summary,
            personal_take=summary.personal_take,
            rank_score=float(article.meta.get("rank_score", 0.0)),
        ))
    return items


def _publish_limit(cfg: dict) -> int:
    """DAILY_TOP_N env var wins, then ranker.default_top_n, then 8."""
    env_value = os.getenv("DAILY_TOP_N", "")
    if env_value.strip():
        return int(env_value)
    return int(cfg.get("ranker", {}).get("default_top_n", 8))


async def run_publish(cfg: dict, only: str | None, limit: int, force: bool = False) -> None:
    """Fetch, rank, enrich with images, summarize, translate, and write the digests.

    Idempotent per day: when today's digest already exists the run is a
    no-op (schedule + manual dispatch can never overwrite the day's
    content with freshly sampled LLM text) unless force=True.
    """
    posts_dir = Path(__file__).resolve().parent.parent / "posts"
    if not force:
        already = existing_editions(posts_dir)
        if already:
            names = ", ".join(path.name for path in already)
            logger.warning(
                "today's digest already exists (%s) - skipping to keep the day "
                "idempotent; rerun with --force to regenerate",
                names,
            )
            print(
                f"Digest for today already exists ({names}) - nothing to do. "
                "Use --force to regenerate."
            )
            return
    ranked = await _collect_ranked(cfg, only)
    if not ranked:
        return
    top = ranked[:limit]
    pipeline_cfg = cfg.get("pipeline", {})
    if pipeline_cfg.get("images", True):
        dropped = drop_blocked_images(top, pipeline_cfg.get("image_blocklist"))
        if dropped:
            logger.info("images: %d dropped by image_blocklist", dropped)
        if pipeline_cfg.get("enrich_images", False):
            found = await enrich_images(top)
            logger.info("images: %d enriched from publisher page meta tags", found)
        else:
            logger.info("images: source-provided media only (og:image enrichment off)")
    provider = make_provider()
    logger.info("llm provider=%s model=%s", provider.name, provider.model)
    pairs = await summarize_batch(provider, top)
    items = _to_curated_items(pairs)
    if not items:
        logger.error("no successfully summarized items - nothing to publish")
        return
    languages = [str(code).strip() for code in (cfg.get("languages") or [])]
    languages = [code for code in languages if code]
    if languages and cfg.get("pipeline", {}).get("translations", True):
        translated = await translate_batch(provider, items, languages)
        logger.info(
            "translations: %d/%d calls ok -> %s",
            translated, len(items) * len(languages), ",".join(languages),
        )
    digest_path = write_digest(
        items,
        posts_dir=posts_dir,
        author=cfg.get("author"),
        languages=languages,
        i18n=load_i18n(I18N_PATH),
    )
    _print_summaries(pairs)
    print(f"Digest file: {digest_path}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="tech-news-curator (ingestion + dedup + ranking + LLM)",
    )
    parser.add_argument("--preview", action="store_true",
                        help="fetch all sources and print top N (no LLM calls)")
    parser.add_argument("--summarize", action="store_true",
                        help="fetch, rank, then summarize top N with the LLM")
    parser.add_argument("--publish", action="store_true",
                        help="fetch, rank, summarize, and write posts/YYYY-MM-DD-tech-digest.md")
    parser.add_argument("--force", action="store_true",
                        help="publish: regenerate today's digest even if it already exists")
    parser.add_argument("--limit", type=int, default=None,
                        help="top N; publish defaults to DAILY_TOP_N / ranker.default_top_n")
    parser.add_argument("--source", choices=["rss", "hn", "reddit"])
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    load_dotenv()  # local runs read LLM_API_KEY / DAILY_TOP_N etc. from .env

    if args.preview:
        asyncio.run(run_preview(load_config(), args.source, args.limit or 10))
    elif args.summarize:
        asyncio.run(run_summarize(load_config(), args.source, args.limit or 10))
    elif args.publish:
        cfg = load_config()
        asyncio.run(
            run_publish(cfg, args.source, args.limit or _publish_limit(cfg), force=args.force)
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
