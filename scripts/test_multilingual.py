"""Stage-7 tests: LLM translation layer + multilingual digest writer + i18n.

No network. Persian/Chinese literals are written as \\u escapes so this
source file stays ASCII like the rest of the codebase; at runtime they are
normal unicode strings identical to what config/i18n.yaml holds.
"""

import asyncio
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.base import LLMError, parse_translation_json, translate_batch
from src.llm.prompts import build_translation_messages
from src.models import Article, CuratedItem
from src.publish.markdown_writer import _labels, load_i18n, write_digest

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = Path(__file__).resolve().parent / "scratch_multilingual_test"
DAY = date(2026, 9, 15)
TARGETS = ["fa", "fr", "de", "es", "zh"]
I18N = load_i18n(ROOT / "config" / "i18n.yaml")

AUTHOR = {
    "name": "Mehdi Esteghlal",
    "linkedin": "https://ir.linkedin.com/in/mehdi-esteghlal-317a67100",
    "github": "https://github.com/Mehdiest",
    "repository": "https://github.com/Mehdiest/tech-news-curator",
}

# --- localized literals (\\u escapes, resolved at import time) -------------
FA_NATIVE = "\u0641\u0627\u0631\u0633\u06cc"                # Persian name
ZH_NATIVE = "\u4e2d\u6587"                                   # Chinese name
FA_TITLE = "\u062e\u0628\u0631 \u06cc\u06a9"                 # "story one"
FA_SUMMARY = "\u062e\u0644\u0627\u0635\u0647 \u0641\u0627\u0631\u0633\u06cc \u062f\u0627\u0633\u062a\u0627\u0646 \u0627\u0648\u0644."
FA_TAKE = "\u0646\u0638\u0631 \u0645\u0646: \u062e\u0648\u0628 \u0628\u0648\u062f."
ZH_SUMMARY = "\u6d4b\u8bd5\u6458\u8981"
ZH_TAKE = "\u6d4b\u8bd5\u89c2\u70b9"
ZH_TITLE = "\u4e2d\u6587\u6807\u9898"
L_SOURCE = "\u0645\u0646\u0628\u0639"                        # source
L_COVERAGE = "\u067e\u0648\u0634\u0634"                      # coverage
L_SCORE = "\u0627\u0645\u062a\u06cc\u0627\u0632"              # score
L_SUMMARY_H = "\u062e\u0644\u0627\u0635\u0647"                # summary heading
L_TAKE_H = "\u0646\u0638\u0631 \u0645\u0646"                  # my take
L_CURATED = "\u06af\u0631\u062f\u0622\u0648\u0631\u06cc \u062a\u0648\u0633\u0637"  # curated by
L_GENERATED = "\u062a\u0648\u0644\u06cc\u062f \u062e\u0648\u062f\u06a9\u0627\u0631"  # auto-generated
ZH_SOURCE = "\u6765\u6e90"                                   # source
ZH_SOURCE_WORD = "\u4e2a\u6765\u6e90"                        # counter + source
ZH_TAKE_H = "\u6211\u7684\u89c2\u70b9"                       # my take


def single_reply(code: str) -> str:
    """Model-style reply for exactly one requested language."""
    blocks = {
        "fa": {"title": FA_TITLE, "summary": FA_SUMMARY, "take": FA_TAKE},
        "fr": {"title": "Titre francais", "summary": "Resume francais.", "take": "Mon avis."},
        "de": {"title": "Deutscher Titel", "summary": "Deutsche Zusammenfassung.", "take": "Mein Fazit."},
        "es": {"title": "Titulo espanol", "summary": "Resumen en espanol.", "take": "Mi opinion."},
        "zh": {"title": ZH_TITLE, "summary": ZH_SUMMARY, "take": ZH_TAKE},
    }
    return json.dumps({code: blocks[code]}, ensure_ascii=True)


def canned_reply(langs=None, drop=None) -> str:
    """Multi-language reply used by the parse-level tests."""
    blocks = {
        "fa": {"title": FA_TITLE, "summary": FA_SUMMARY, "take": FA_TAKE},
        "fr": {"title": "Titre francais", "summary": "Resume francais.", "take": "Mon avis."},
        "de": {"title": "Deutscher Titel", "summary": "Deutsche Zusammenfassung.", "take": "Mein Fazit."},
        "es": {"title": "Titulo espanol", "summary": "Resumen en espanol.", "take": "Mi opinion."},
        "zh": {"title": ZH_TITLE, "summary": ZH_SUMMARY, "take": ZH_TAKE},
    }
    for code in (drop or []):
        blocks.pop(code, None)
    keep = set(langs or TARGETS)
    return json.dumps({k: v for k, v in blocks.items() if k in keep}, ensure_ascii=True)


class FakeProvider:
    """Stand-in provider: translate_batch only needs chat().

    Detects the requested language from the user message ("Target languages:
    Persian (Farsi) (fa).") and answers with that language's block; entries
    in `missing` answer with an unusable empty object, `fail` raises.
    """

    name = "fake"

    def __init__(self, fail: bool = False, missing: tuple = ()):  # noqa: RSE102
        self.fail = fail
        self.missing = set(missing)
        self.calls: list[dict] = []

    async def chat(self, messages, max_tokens=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        if self.fail:
            raise LLMError("simulated outage")
        user = messages[1]["content"]
        match = re.search(r"\(([a-z]{2})\)\.", user)
        code = match.group(1) if match else ""
        if code in self.missing:
            return "{}"
        return single_reply(code)


def make_item(title, source, summary, take, score=42.0, topic="ai", coverage=2,
              image=None, translations=None):
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
        article=article, llm_summary=summary, personal_take=take,
        rank_score=score, translations=translations or {},
    )


def build_items():
    """Item one fully translated; item two misses the zh block on purpose."""
    full = parse_translation_json(canned_reply(), TARGETS)
    partial = parse_translation_json(canned_reply(drop=["zh"]), TARGETS)
    return [
        make_item(
            "Story One", "HackerNews",
            "Factual summary of story one, two to four sentences long.",
            "Funny expert take on story one, with a punchline.",
            image="https://cdn.example.com/one.jpg?w=800&h=400",
            translations=full,
        ),
        make_item(
            "Story Two", "Stack Overflow Blog",
            "Summary for story two.",
            "Witty commentary on story two.", score=31.5, topic="dev", coverage=1,
            translations=partial,
        ),
    ]


def test_parse_translation_json():
    clean = parse_translation_json(canned_reply(), TARGETS)
    assert set(clean) == set(TARGETS)
    assert clean["fa"] == {"title": FA_TITLE, "summary": FA_SUMMARY, "take": FA_TAKE}
    fenced = "```json\n" + canned_reply() + "\n```"
    assert set(parse_translation_json(fenced, TARGETS)) == set(TARGETS)
    dropped = parse_translation_json(canned_reply(drop=["zh"]), TARGETS)
    assert set(dropped) == set(TARGETS) - {"zh"}
    # a reply where no language has both summary and take must raise
    broken_field = '{"fa": {"title": "t", "summary": "s", "take": ""}}'
    try:
        parse_translation_json(broken_field, ["fa"])
    except LLMError:
        pass
    else:
        raise AssertionError("fully unusable reply must raise LLMError")
    for bad in ("no json at all", "{}", "{broken"):
        try:
            parse_translation_json(bad, TARGETS)
        except LLMError:
            continue
        raise AssertionError(f"expected LLMError for {bad!r}")
    print("PASS parse_translation_json (clean, fenced, per-language gaps, rejects)")


def test_build_translation_messages():
    messages = build_translation_messages(
        {"title": "Story One", "summary": "S.", "take": "T."}, TARGETS,
    )
    system, user = messages[0]["content"], messages[1]["content"]
    assert "SAME author" in system and "STRICT JSON" in system
    assert "Simplified Chinese" in system
    for needle in ("Persian (Farsi) (fa)", "Simplified Chinese (zh)",
                   '"fa": {"title": "...", "summary": "...", "take": "..."}',
                   "Story One"):
        assert needle in user, needle
    print("PASS build_translation_messages (voice contract, targets, entry payload)")


def test_translate_batch_success():
    items = build_items()
    provider = FakeProvider()
    done = asyncio.run(translate_batch(provider, items, TARGETS))
    assert done == 10  # 2 items x 5 languages, one small call each
    for item in items:
        assert set(item.translations) == set(TARGETS)
        assert item.translations["fa"]["summary"] == FA_SUMMARY
    assert len(provider.calls) == 10
    assert provider.calls[0]["max_tokens"] == 800
    print("PASS translate_batch fills every language via per-pair calls")


def test_translate_batch_isolation():
    item = make_item("Solo Story", "HackerNews", "Summary.", "Take.")
    partial = FakeProvider(missing=("zh", "de"))
    done = asyncio.run(translate_batch(partial, [item], TARGETS))
    assert done == 3 and set(item.translations) == set(TARGETS) - {"zh", "de"}

    failing = FakeProvider(fail=True)
    fresh = make_item("Fresh Story", "HackerNews", "Summary.", "Take.")
    done = asyncio.run(translate_batch(failing, [fresh], TARGETS))
    assert done == 0 and fresh.translations == {}  # no crash, English retained
    print("PASS translate_batch isolates per-language gaps and full failures")


def test_writer_multilingual_editions():
    items = build_items()
    path = write_digest(
        items, day=DAY, posts_dir=SCRATCH, author=AUTHOR,
        languages=TARGETS, i18n=I18N,
    )
    assert path.name == "2026-09-15-tech-digest.md"
    names = sorted(p.name for p in SCRATCH.glob("*.md"))
    assert names == sorted([
        "2026-09-15-tech-digest.md", "2026-09-15-tech-digest-fa.md",
        "2026-09-15-tech-digest-fr.md", "2026-09-15-tech-digest-de.md",
        "2026-09-15-tech-digest-es.md", "2026-09-15-tech-digest-zh.md",
    ]), names

    en = (SCRATCH / "2026-09-15-tech-digest.md").read_text(encoding="utf-8")
    # language switcher on the English page with native names + .html links
    assert "**Read this digest in:**" in en
    assert f"[{FA_NATIVE}](2026-09-15-tech-digest-fa.html)" in en
    assert f"[{ZH_NATIVE}](2026-09-15-tech-digest-zh.html)" in en
    assert "[Deutsch](2026-09-15-tech-digest-de.html)" in en
    # front-matter carries the sibling map for the Jekyll index page; the
    # file path is the posts dir name + .html (in production: posts/...)
    assert "lang: en" in en and 'name: "' + FA_NATIVE + '"' in en
    assert f'file: "{SCRATCH.name}/2026-09-15-tech-digest-fa.html"' in en
    # English labels and attribution untouched
    assert "**Source:** HackerNews" in en and "**My Take**" in en
    assert "_Curated by [Mehdi Esteghlal]" in en

    fa = (SCRATCH / "2026-09-15-tech-digest-fa.md").read_text(encoding="utf-8")
    assert "lang: fa" in fa and "dir: rtl" in fa and "og_locale: fa_IR" in fa
    assert f"## 1. [{FA_TITLE}](https://example.com/story-one)" in fa
    assert f"![{FA_TITLE}](https://cdn.example.com/one.jpg?w=800&h=400)" in fa
    assert f"**{L_SOURCE}:** HackerNews" in fa
    assert f"**{L_COVERAGE}:** 2 \u0645\u0646\u0628\u0639" in fa
    assert f"**{L_SCORE}:** 42.0" in fa
    assert f"**{L_SUMMARY_H}**" in fa and f"**{L_TAKE_H}**" in fa
    assert FA_SUMMARY in fa and FA_TAKE in fa
    assert f"_{L_CURATED} [Mehdi Esteghlal]" in fa  # name stays Latin for SEO
    assert f"{L_GENERATED}" in fa and "Curated by:" not in fa
    # fa page links back to the other editions, never to itself
    assert "[English](2026-09-15-tech-digest.html)" in fa
    assert FA_NATIVE + "](" not in fa

    zh = (SCRATCH / "2026-09-15-tech-digest-zh.md").read_text(encoding="utf-8")
    assert f"**{ZH_SOURCE}:** HackerNews" in zh
    assert f"**\u8986\u76d6:** 1 {ZH_SOURCE_WORD}" in zh
    assert f"**{ZH_TAKE_H}**" in zh and ZH_TAKE in zh  # item one translated
    assert "Summary for story two." in zh  # item two fell back to English
    assert "dir: ltr" in zh and "og_locale: zh_CN" in zh

    es = (SCRATCH / "2026-09-15-tech-digest-es.md").read_text(encoding="utf-8")
    assert "Resumen en espanol." in es and "lang: es" in es
    print("PASS writer emits six editions: switcher, RTL fa, labels, fallbacks")


def _reset_scratch() -> None:
    """Wipe the shared scratch dir so edition files from other tests cannot leak."""
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)


def test_writer_backward_compatible():
    _reset_scratch()
    items = [
        make_item("Bare Story", "HackerNews", "Summary text.", "Take text."),
    ]
    text = write_digest(items, day=DAY, posts_dir=SCRATCH).read_text(encoding="utf-8")
    assert "**Read this digest in:**" not in text
    assert "translations:" not in text
    assert "lang: en" in text and "dir: ltr" in text  # new front-matter, harmless
    assert not (SCRATCH / "2026-09-15-tech-digest-fa.md").exists()
    assert "**Source:** HackerNews" in text
    print("PASS no languages configured -> English-only edition, as before")


def test_i18n_labels_and_unknown_language_fallback():
    _reset_scratch()
    assert set(I18N) == {"en", "fa", "fr", "de", "es", "zh"}
    assert I18N["fa"]["dir"] == "rtl" and I18N["fa"]["native_name"] == FA_NATIVE
    assert I18N["en"]["source"] == "Source"
    unknown = _labels("xx", I18N)  # falls back to the en block / defaults
    assert unknown["source"] == "Source" and unknown["dir"] == "ltr"
    missing = _labels("fa", {})   # no i18n at all -> built-in English defaults
    assert missing["take_h"] == "My Take"

    item = make_item("Solo Story", "HackerNews", "Summary.", "Take.")
    path = write_digest([item], day=DAY, posts_dir=SCRATCH, languages=["xx"], i18n=I18N)
    xx = (SCRATCH / "2026-09-15-tech-digest-xx.md").read_text(encoding="utf-8")
    assert path.name == "2026-09-15-tech-digest.md" and "**Source:**" in xx
    print("PASS i18n labels merge correctly; unknown language degrades to English")


def test_rerun_is_idempotent():
    items = build_items()
    first = write_digest(items, day=DAY, posts_dir=SCRATCH, author=AUTHOR,
                         languages=TARGETS, i18n=I18N)
    fa_first = (SCRATCH / "2026-09-15-tech-digest-fa.md").read_text(encoding="utf-8")
    write_digest(items, day=DAY, posts_dir=SCRATCH, author=AUTHOR,
                 languages=TARGETS, i18n=I18N)
    fa_second = (SCRATCH / "2026-09-15-tech-digest-fa.md").read_text(encoding="utf-8")
    stamp = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")
    assert stamp.sub("STAMP", fa_first) == stamp.sub("STAMP", fa_second)
    assert first.name == "2026-09-15-tech-digest.md"
    print("PASS rerun on the same day overwrites every edition identically")


if __name__ == "__main__":
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    try:
        test_parse_translation_json()
        test_build_translation_messages()
        test_translate_batch_success()
        test_translate_batch_isolation()
        test_writer_multilingual_editions()
        test_writer_backward_compatible()
        test_i18n_labels_and_unknown_language_fallback()
        test_rerun_is_idempotent()
    finally:
        if SCRATCH.exists():
            shutil.rmtree(SCRATCH)
    print("\nAll multilingual tests passed.")
