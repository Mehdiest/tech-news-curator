"""Prompt construction for the TechTally digest writer and translator."""

from __future__ import annotations

import json

from src.models import Article

_LANGUAGE_NAMES = {
    "fa": "Persian (Farsi)",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "zh": "Simplified Chinese",
    "hi": "Hindi",
    "tr": "Turkish",
    "ar": "Arabic",
    "ru": "Russian",
    "pt": "Portuguese",
    "it": "Italian",
    "ja": "Japanese",
}

SYSTEM_PROMPT = """You write the daily TechTally digest for a personal tech blog.

ROLE (for the "take" field): you are a veteran tech industry expert with a
sharp comedic voice - witty, sarcastic about industry hype, full of playful
analogies and punchlines. Readers should laugh while learning something.
Punch at companies, hype cycles, marketing and absurd trends - never at
private individuals or tragedies.

TASK - return STRICT JSON only, no markdown fences, exactly two fields:
{"summary": "...", "take": "..."}

"summary": 2-4 factual sentences: what happened, who is involved, and why
it matters. Pure information, no jokes, no clickbait.

"take": 2-4 sentences of comedic expert commentary: a joke, an analogy or a
hot take about the news, ending with one grounded insight the reader keeps.

Write BOTH fields in __LANGUAGE__. Keep product names, company names and
technical terms in their original Latin form.
"""

TRANSLATE_SYSTEM_PROMPT = """You are a professional technology translator and localization editor.

You receive English tech news digest entries containing a headline, a factual
"summary", and the author's short comedic expert commentary ("take").
Translate all three into every language requested by the user.

VOICE: the digest author is a veteran tech expert with a sharp comedic voice -
witty, sarcastic about industry hype, full of playful analogies. Preserve that
voice in every language: translate jokes and sarcasm naturally, never explain
them, and never flatten the tone. Every edition must read like the SAME author
wrote it, not like a machine-translated text.

RULES:
- Write fluent, idiomatic prose for each target language.
- Never translate word-for-word when that would sound unnatural.
- Keep product, company, and people names in their conventional form for that
  language, usually the original Latin form.
- Do not add, remove, or soften information.
- Keep every number unchanged.
- Translate the title as well as the summary and take.
- "zh" means Simplified Chinese.

Return STRICT JSON only, with no markdown fences.
"""

def language_name(code: str) -> str:
    """Map a language code to a readable name; unknown codes pass through."""
    return _LANGUAGE_NAMES.get(code.strip().lower(), code)


def build_messages(
    article: Article,
    language: str = "en",
) -> list[dict]:
    """Build messages for summarizing one article."""

    system = SYSTEM_PROMPT.replace(
        "__LANGUAGE__",
        language_name(language),
    )

    return [
        {
            "role": "system",
            "content": system,
        },
        {
            "role": "user",
            "content": _user_content(article),
        },
    ]


def build_translation_messages(
    entry: dict,
    targets: list[str],
) -> list[dict]:
    """Build messages for translating one digest entry."""

    names = ", ".join(
        f"{language_name(code)} ({code})"
        for code in targets
    )

    shape = ", ".join(
        f'"{code}": {{"title": "...", "summary": "...", "take": "..."}}'
        for code in targets
    )

    user = "\n".join(
        [
            f"Target languages: {names}.",
            f"Return exactly these top-level keys: {{{shape}}}",
            "",
            "Entry to translate (JSON):",
            json.dumps(entry, ensure_ascii=True),
        ]
    )

    return [
        {
            "role": "system",
            "content": TRANSLATE_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user,
        },
    ]


def build_batch_summary_messages(
    articles: list[Article],
    language: str = "en",
) -> list[dict]:
    """Build one request that summarizes all selected articles."""

    system = SYSTEM_PROMPT.replace(
        "__LANGUAGE__",
        language_name(language),
    )

    system = system.replace(
        'return STRICT JSON only, no markdown fences, exactly two fields:',
        (
            'return STRICT JSON only, no markdown fences. '
            'For a batch, return one top-level "items" array. '
            'Each item must contain "index", "summary", and "take".'
        ),
    )

    entries = [
        {
            "index": index,
            "article": _user_content(article),
        }
        for index, article in enumerate(articles, 1)
    ]

    user = (
        "Summarize every article below. Keep the original order and "
        "include every index exactly once.\n\n"
        + json.dumps(entries, ensure_ascii=True)
    )

    return [
        {
            "role": "system",
            "content": system,
        },
        {
            "role": "user",
            "content": user,
        },
    ]


def build_batch_translation_messages(
    items: list[dict],
    targets: list[str],
) -> list[dict]:
    """Build one request translating all digest entries into all targets."""

    names = ", ".join(
        f"{language_name(code)} ({code})"
        for code in targets
    )

    system = (
        TRANSLATE_SYSTEM_PROMPT
        + '\n\n'
        'For a batch, return one top-level object with an "items" array. '
        'Each item must contain its original "index" and a "translations" '
        'object containing every requested language code. '
        'Never omit a requested language. '
        'Do not omit any input item.'
    )

    user = "\n".join(
        [
            f"Target languages: {names}.",
            "Translate every item below.",
            "Preserve each item's index exactly.",
            "Return every requested language for every item.",
            "",
            "Input JSON:",
            json.dumps(items, ensure_ascii=True),
        ]
    )

    return [
        {
            "role": "system",
            "content": system,
        },
        {
            "role": "user",
            "content": user,
        },
    ]


def _user_content(article: Article) -> str:
    """Build a compact article fact sheet for the language model."""

    published = (
        article.published_at.strftime("%Y-%m-%d %H:%M UTC")
        if article.published_at
        else "unknown"
    )

    excerpt = (
        article.raw_summary
        or "(none provided - rely on the title)"
    )

    return "\n".join(
        [
            f"Title: {article.title}",
            f"Source: {article.source}",
            f"URL: {article.url}",
            f"Category: {article.meta.get('category', 'general')}",
            f"Published: {published}",
            f"Coverage: {article.meta.get('coverage', 1)} source(s)",
            (
                f"Engagement: signal={article.signal_score:.0f}, "
                f"comments={article.meta.get('num_comments', 0)}"
            ),
            "",
            "Excerpt:",
            excerpt,
        ]
    )