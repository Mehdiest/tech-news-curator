"""Backfill missing translations for already-published digests.

The daily pipeline is idempotent (it never rewrites an existing day), so
posts generated before the translation-retry fix keep their gaps forever:
some items in a translated edition silently fall back to English. This
script repairs that:

1. Parse the English edition of every day found in posts/.
2. Salvage the translations that DO exist from each sibling -<lang>.md
   (always across ALL configured languages, so a restricted --langs run
   can never wipe a sibling edition it was not asked to touch).
3. Translate only the missing (item, language) pairs through the configured
   LLM - same per-pair isolation and retry policy as the daily pipeline.
4. Rewrite ALL editions of the day with the current renderer, so older
   posts also pick up newer formatting (localized meta description, no raw
   rank score, cleaner pluralization).
5. Refresh _includes/latest_digest.html for the newest day, so the home
   page's inline digest matches the repaired content.

Usage:
    python scripts/backfill_translations.py             # repair every day
    python scripts/backfill_translations.py --days 2    # newest two days
    python scripts/backfill_translations.py --langs fa  # only one language
    python scripts/backfill_translations.py --dry-run   # report only

LLM_* env vars (or a .env file) are required only when gaps exist; a
--dry-run never calls the LLM and never writes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from dotenv import load_dotenv

from src.llm.base import (
    TRANSLATION_RETRY_ROUNDS,
    _TRANSLATION_RETRY_DELAY_SECONDS,
    LLMError,
    parse_translation_json,
)
from src.llm.factory import make_provider
from src.llm.prompts import build_translation_messages
from src.models import Article, CuratedItem
from src.publish.markdown_writer import (
    _edition_filename,
    _labels,
    load_i18n,
    read_baseurl,
    write_digest,
    write_latest_include,
)

logger = logging.getLogger("backfill")

I18N_PATH = PROJECT_ROOT / "config" / "i18n.yaml"
CONFIG_PATH = PROJECT_ROOT / "config" / "sources.yaml"

# Token cap for one translation reply. The daily pipeline (translate_batch)
# passes max_tokens=3000; backfill calls provider.chat() directly and used to
# inherit the provider default (700), which truncates long / non-Latin replies
# mid-JSON - every (item, language) pair then failed to parse ("invalid JSON
# from model") and the rewritten editions kept their English text. Pin the
# same cap as the daily path so hi/ru/ar replies survive intact.
TRANSLATION_MAX_TOKENS = 3000

_ITEM_RE = re.compile(r"^##\s*(\d+)\.\s*\[(.*)\]\((.*)\)\s*$")
_IMAGE_RE = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*$")
_META_SCORE_RE = re.compile(r"\*\*Score:\*\*\s*([0-9.]+)")
_META_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def split_front_matter(text: str) -> tuple[dict, str]:
    """Split a digest file into (front-matter dict, body markdown)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            block = "\n".join(lines[1:index])
            try:
                return yaml.safe_load(block) or {}, "\n".join(lines[index + 1:])
            except yaml.YAMLError:
                return {}, text
    return {}, text


def parse_items(body: str, labels: dict) -> list[dict]:
    """Parse digest item blocks (any language) into plain dicts.

    The digest format is machine-written and regular, so a small state
    machine keyed on the `## N. [title](url)` headings is enough. Labels
    come from i18n so translated editions parse with the same code.
    """
    items: list[dict] = []
    current: dict | None = None
    section: str | None = None
    summary_head = f"**{labels['summary_h']}**"
    take_head = f"**{labels['take_h']}**"
    source_head = f"**{labels['source']}:**"
    topic_head = f"**{labels['topic']}:**"
    coverage_head = f"**{labels['coverage']}:**"

    def flush() -> None:
        if current is not None:
            current["summary"] = "\n".join(current.pop("summary_lines")).strip()
            current["take"] = "\n".join(current.pop("take_lines")).strip()
            items.append(current)

    for line in body.splitlines():
        heading = _ITEM_RE.match(line)
        if heading:
            flush()
            current = {
                "index": int(heading.group(1)),
                "title": heading.group(2).strip(),
                "url": heading.group(3).strip(),
                "image": None,
                "source": "",
                "topic": "",
                "coverage": 1,
                "score": None,
                "discussion": "",
                "summary_lines": [],
                "take_lines": [],
            }
            section = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if current["image"] is None and _IMAGE_RE.match(stripped):
            current["image"] = _IMAGE_RE.match(stripped).group(1).strip()
            continue
        if stripped == summary_head:
            section = "summary"
            continue
        if stripped == take_head:
            section = "take"
            continue
        if line.startswith("> ") and section == "take":
            current["take_lines"].append(line[2:].rstrip())
            continue
        if stripped == "---":
            section = None
            continue
        if source_head in stripped or topic_head in stripped or coverage_head in stripped:
            if source_head in stripped:
                current["source"] = stripped.split(source_head, 1)[1].split("|")[0].strip()
            if topic_head in stripped:
                current["topic"] = stripped.split(topic_head, 1)[1].split("|")[0].strip()
            if coverage_head in stripped:
                digits = re.search(r"(\d+)", stripped.split(coverage_head, 1)[1])
                current["coverage"] = int(digits.group(1)) if digits else 1
            score = _META_SCORE_RE.search(stripped)
            if score:
                current["score"] = float(score.group(1))
            for _label, link_url in _META_LINK_RE.findall(stripped):
                if link_url.rstrip("/") != current["url"].rstrip("/"):
                    current["discussion"] = link_url
            continue
        if section == "summary" and stripped and not stripped.startswith("**"):
            current["summary_lines"].append(stripped)
    flush()
    return items


def parse_edition(path: Path, i18n: dict) -> tuple[dict, list[dict]]:
    """Parse one edition file into (front-matter, items) using its labels."""
    text = path.read_text(encoding="utf-8")
    front_matter, body = split_front_matter(text)
    lang = str(front_matter.get("lang") or "en")
    return front_matter, parse_items(body, _labels(lang, i18n))


def build_curated_items(
    day: date, en_items: list[dict], all_languages: list[str],
    posts_dir: Path, i18n: dict,
) -> list[CuratedItem]:
    """Rebuild CuratedItem objects: English text + salvaged translations.

    Every configured language is salvaged (never only a restricted subset),
    so rewriting the day can never wipe an edition's existing translations.
    A pair counts as translated only when both the summary and the take
    differ from the English source - a failed LLM call fell back to the
    English text, which is exactly the gap this script repairs.
    """
    parsed_by_lang: dict[str, dict[int, dict]] = {}
    for lang in all_languages:
        path = posts_dir / _edition_filename(day, lang, posts_dir=posts_dir)
        if not path.exists():
            parsed_by_lang[lang] = {}
            continue
        _front_matter, lang_items = parse_edition(path, i18n)
        parsed_by_lang[lang] = {item["index"]: item for item in lang_items}

    items: list[CuratedItem] = []
    for en_item in en_items:
        translations: dict[str, dict[str, str]] = {}
        for lang in all_languages:
            lang_item = parsed_by_lang[lang].get(en_item["index"])
            if not lang_item:
                continue
            summary = lang_item["summary"]
            take = lang_item["take"]
            if not summary or not take:
                continue
            if summary == en_item["summary"] or take == en_item["take"]:
                logger.info(
                    "%s item %d: %s still English - marked for re-translation",
                    day, en_item["index"], lang,
                )
                continue
            translations[lang] = {
                "title": lang_item["title"] or en_item["title"],
                "summary": summary,
                "take": take,
            }
        article = Article(
            title=en_item["title"],
            url=en_item["url"],
            source=en_item["source"] or "unknown",
            image_url=en_item["image"],
            meta={
                "category": en_item["topic"] or "general",
                "coverage": en_item["coverage"] or 1,
                "discussion_url": en_item["discussion"] or "",
            },
        )
        items.append(CuratedItem(
            article=article,
            llm_summary=en_item["summary"],
            personal_take=en_item["take"],
            rank_score=float(en_item["score"] or 0.0),
            translations=translations,
        ))
    return items


async def fill_missing(
    provider, items: list[CuratedItem], targets: list[str], concurrency: int = 3,
) -> int:
    """Translate only the missing (item, language) pairs, with retries."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(item: CuratedItem, code: str) -> bool:
        async with semaphore:
            entry = {
                "title": item.article.title,
                "summary": item.llm_summary,
                "take": item.personal_take,
            }
            try:
                reply = await provider.chat(
                    build_translation_messages(entry, [code]),
                    max_tokens=TRANSLATION_MAX_TOKENS,
                )
                item.translations.update(parse_translation_json(reply, [code]))
                logger.info(
                    "translated %r -> %s", item.article.title[:50], code,
                )
                return True
            except LLMError as error:
                logger.warning("translation %s failed: %s", code, error)
            except Exception as error:  # isolation boundary, never crash the batch
                logger.warning("translation %s crashed: %r", code, error)
            return False

    pairs = [
        (item, code) for item in items for code in targets
        if code not in item.translations
    ]
    if not pairs:
        return 0
    ok = 0
    pending = pairs
    for round_index in range(max(1, TRANSLATION_RETRY_ROUNDS + 1)):
        if not pending:
            break
        if round_index:
            logger.info("retry round %d for %d pair(s)", round_index, len(pending))
            await asyncio.sleep(_TRANSLATION_RETRY_DELAY_SECONDS * round_index)
        results = await asyncio.gather(*(_one(item, code) for item, code in pending))
        ok += sum(1 for done in results if done)
        pending = [pair for pair, done in zip(pending, results) if not done]
    return ok


async def run(args: argparse.Namespace) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    with open(CONFIG_PATH, encoding="utf-8") as stream:
        cfg = yaml.safe_load(stream) or {}
    i18n = load_i18n(I18N_PATH)
    posts_dir = PROJECT_ROOT / "posts"
    # Full configured language set: used for salvaging, rewriting, and the
    # home-page include. A restricted --langs list only limits which pairs
    # get LLM-filled, never what gets wiped or re-linked.
    all_languages = [
        str(code).strip() for code in (cfg.get("languages") or []) if str(code).strip()
    ]
    fill_languages = (
        [code.strip() for code in args.langs.split(",") if code.strip()]
        if args.langs else all_languages
    )
    en_paths = sorted(
        set(posts_dir.glob("*-techtally.md")) | set(posts_dir.glob("*-tech-digest.md")),
        key=lambda path: path.name, reverse=True,
    )
    if args.days:
        en_paths = en_paths[: args.days]
    if not en_paths:
        logger.error("no English editions found in %s", posts_dir)
        return 1

    provider = None
    total_missing = 0
    newest: tuple[date, list[CuratedItem]] | None = None
    for path in en_paths:
        front_matter, en_items = parse_edition(path, i18n)
        day = front_matter.get("date")
        if not en_items or not isinstance(day, date):
            logger.error("cannot parse %s - skipping", path.name)
            continue
        items = build_curated_items(day, en_items, all_languages, posts_dir, i18n)
        missing = [
            (item, code) for item in items for code in fill_languages
            if code not in item.translations
        ]
        total_missing += len(missing)
        print(
            f"{day}: {len(items)} items x {len(all_languages)} languages, "
            f"{len(items) * len(all_languages) - len(missing)} present, "
            f"{len(missing)} missing"
        )
        if args.dry_run:
            continue
        if missing:
            if provider is None:
                provider = make_provider()
                logger.info("llm provider=%s model=%s", provider.name, provider.model)
            filled = await fill_missing(provider, items, fill_languages)
            logger.info("%s: %d/%d pairs filled", day, filled, len(missing))
        else:
            logger.info("%s: no LLM calls needed", day)
        # Rewrite the day either way: even a gap-free day is normalized to
        # the current renderer (localized meta description, no score line).
        write_digest(
            items, day=day, posts_dir=posts_dir,
            author=cfg.get("author"), languages=all_languages, i18n=i18n,
        )
        if newest is None or day > newest[0]:
            newest = (day, items)

    if args.dry_run:
        print(f"\ndry run: {total_missing} translation gap(s) would be filled")
        return 0
    if newest is not None:
        write_latest_include(
            newest[1], newest[0], cfg.get("author"), i18n, all_languages,
            posts_dir.name,
            read_baseurl(
                PROJECT_ROOT / "_config.yml",
                (cfg.get("author") or {}).get("repository", ""),
            ),
            PROJECT_ROOT / "_includes", PROJECT_ROOT / "_data",
            posts_dir,
        )
        logger.info("latest-digest include refreshed for %s", newest[0])
    print(f"\ndone: {total_missing} gap(s) processed across {len(en_paths)} day(s)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill missing translations in already-published digests",
    )
    parser.add_argument("--days", type=int, default=None,
                        help="only the N newest days (default: all)")
    parser.add_argument("--langs", type=str, default=None,
                        help="comma-separated language codes (default: config)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the gaps without calling the LLM or writing")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
