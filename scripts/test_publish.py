"""Unit tests for the stage-5 markdown writer (no network, no LLM)."""

import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Article, CuratedItem
from src.publish.markdown_writer import write_digest

SCRATCH = Path(__file__).resolve().parent / "scratch_publish_test"
DAY = date(2026, 9, 15)

AUTHOR = {
    "name": "Mehdi Esteghlal",
    "linkedin": "https://ir.linkedin.com/in/mehdi-esteghlal-317a67100",
    "github": "https://github.com/Mehdiest",
    "repository": "https://github.com/Mehdiest/tech-news-curator",
}


def make_item(title, source, summary, take, score=42.0, topic="ai", coverage=2,
              image=None):
    article = Article(
        title=title,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        source=source,
        published_at=None,
        signal_score=100,
        image_url=image,
        meta={"category": topic, "coverage": coverage, "num_comments": 10},
    )
    return CuratedItem(
        article=article, llm_summary=summary, personal_take=take, rank_score=score,
    )


def build_items():
    return [
        make_item(
            "Story One", "HackerNews",
            "Factual summary of story one, two to four sentences long.",
            "Funny expert take on story one, with a punchline.",
            image="https://cdn.example.com/one.jpg?w=800&h=400",
        ),
        make_item(
            "Story Two", "Stack Overflow Blog",
            "Factual summary of story two, from a different source.",
            "Witty commentary on story two.", score=31.5, topic="dev", coverage=1,
        ),
    ]


def test_write_and_template():
    path = write_digest(build_items(), day=DAY, posts_dir=SCRATCH)
    assert path.name == "2026-09-15-tech-digest.md", path.name
    assert path.parent == SCRATCH
    text = path.read_text(encoding="utf-8")

    # front-matter, including the cover image of the first item
    assert text.startswith("---\n")
    for needle in (
        'title: "Tech Digest - 2026-09-15"', "date: 2026-09-15", "items: 2",
        "sources: [HackerNews, Stack Overflow Blog]", "generator: tech-news-curator",
        'cover: "https://cdn.example.com/one.jpg?w=800&h=400"',
    ):
        assert needle in text, needle

    # body structure: linked title, image, meta, summary, blockquoted take
    assert "# Tech Digest - 2026-09-15" in text
    assert "## 1. [Story One](https://example.com/story-one)" in text
    assert "## 2. [Story Two](https://example.com/story-two)" in text
    assert "![Story One](https://cdn.example.com/one.jpg?w=800&h=400)" in text
    assert "**Source:** HackerNews" in text and "**Topic:** ai" in text
    assert "**Coverage:** 2 source(s)" in text and "**Score:** 42.0" in text
    assert text.count("**Summary**") == 2 and text.count("**My Take**") == 2
    assert "> Funny expert take on story one" in text
    assert "> Witty commentary on story two" in text

    # separator between items but not before the first
    assert text.count("\n---\n\n## ") == 1
    print("PASS write_digest file name, front-matter, item template, image, cover")


def test_item_without_image_has_no_empty_gap():
    items = [make_item("Bare Story", "HackerNews", "Summary text.", "Take text.")]
    text = write_digest(items, day=DAY, posts_dir=SCRATCH).read_text(encoding="utf-8")
    assert "![" not in text, "no image markdown expected without an image_url"
    assert "cover:" not in text
    # linked title flows straight into the meta line
    assert "## 1. [Bare Story](https://example.com/bare-story)\n\n**Source:**" in text
    print("PASS item without image renders cleanly (no image, no cover)")


def test_tricky_urls_and_titles_still_link():
    item = make_item(
        "Weird [Brackets] & \"Quotes\"", "TechCrunch", "Summary.", "Take.",
        image="https://en.wikipedia.org/wiki/Foo_(bar)/thumb/x.jpg",
    )
    text = write_digest([item], day=DAY, posts_dir=SCRATCH).read_text(encoding="utf-8")
    assert "![Weird (Brackets) & 'Quotes']" in text
    assert "](<https://en.wikipedia.org/wiki/Foo_(bar)/thumb/x.jpg>)" in text
    print("PASS brackets/quotes/parenthesized image URLs are escaped safely")


def test_author_attribution_and_seo():
    path = write_digest(build_items(), day=DAY, posts_dir=SCRATCH, author=AUTHOR)
    text = path.read_text(encoding="utf-8")

    # front-matter: author field, name in the page title, unique meta description
    assert 'author: "Mehdi Esteghlal"' in text
    assert 'title: "Tech Digest - 2026-09-15 | Mehdi Esteghlal"' in text
    assert (
        'description: "Daily tech news digest for 2026-09-15: 2 top stories '
        'summarized with expert commentary, curated by Mehdi Esteghlal."'
    ) in text

    # visible byline near the top, linked to LinkedIn
    assert (
        "_Curated by [Mehdi Esteghlal]"
        "(https://ir.linkedin.com/in/mehdi-esteghlal-317a67100)_" in text
    )

    # footer: repo link no longer broken + curator profile links
    assert (
        "[tech-news-curator](https://github.com/Mehdiest/tech-news-curator)" in text
    )
    assert "Curated by: **Mehdi Esteghlal**" in text
    assert "[LinkedIn](https://ir.linkedin.com/in/mehdi-esteghlal-317a67100)" in text
    assert "[GitHub](https://github.com/Mehdiest)" in text
    print("PASS author attribution: front-matter, byline, footer links, fixed repo link")


def test_without_author_stays_clean():
    text = write_digest(build_items(), day=DAY, posts_dir=SCRATCH).read_text(
        encoding="utf-8"
    )
    assert "author:" not in text and "Curated by" not in text
    assert 'title: "Tech Digest - 2026-09-15"' in text  # no name suffix
    assert "[tech-news-curator] on " in text  # legacy footer still fine
    print("PASS no author configured -> clean output, no attribution lines")


def test_empty_rejected():
    try:
        write_digest([], day=DAY, posts_dir=SCRATCH)
    except ValueError:
        print("PASS empty item list raises ValueError")
        return
    raise AssertionError("empty items must raise ValueError")


def test_existing_editions_helper():
    """The idempotency guard: files of the day (all editions) are found,
    other days and missing dirs are not."""
    from src.publish.markdown_writer import existing_editions

    # SCRATCH may already hold this run's files for DAY - use a clean day
    assert existing_editions(SCRATCH, day=date(2026, 9, 20)) == []
    write_digest(build_items(), day=DAY, posts_dir=SCRATCH, languages=["fa"])
    names = [path.name for path in existing_editions(SCRATCH, day=DAY)]
    assert "2026-09-15-tech-digest.md" in names
    assert "2026-09-15-tech-digest-fa.md" in names
    assert existing_editions(SCRATCH / "missing-dir", day=DAY) == []
    print("PASS existing_editions finds the day's files across editions only")


def test_rerun_is_idempotent():
    first = write_digest(build_items(), day=DAY, posts_dir=SCRATCH)
    first_prefix = first.read_text(encoding="utf-8").split("*Auto-generated")[0]
    second = write_digest(build_items(), day=DAY, posts_dir=SCRATCH)
    second_prefix = second.read_text(encoding="utf-8").split("*Auto-generated")[0]
    assert first == second  # same path, overwritten
    assert first_prefix == second_prefix  # identical body, only stamp differs
    print("PASS rerun on the same day overwrites the same file")


if __name__ == "__main__":
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    try:
        test_write_and_template()
        test_item_without_image_has_no_empty_gap()
        test_tricky_urls_and_titles_still_link()
        test_author_attribution_and_seo()
        test_without_author_stays_clean()
        test_empty_rejected()
        test_existing_editions_helper()
        test_rerun_is_idempotent()
    finally:
        if SCRATCH.exists():
            shutil.rmtree(SCRATCH)
    print("\nAll publish tests passed.")
