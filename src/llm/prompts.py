"""Prompt construction for the digest writer persona.

Everything is English by default (DIGEST_LANGUAGE=en); the codebase
stays ASCII regardless of the configured output language. Translated
editions (stage 7) are produced from the finished English text so the
author's voice stays identical across languages.
"""

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
    "tr": "Turkish",
    "ar": "Arabic",
    "ru": "Russian",
    "pt": "Portuguese",
    "it": "Italian",
    "ja": "Japanese",
}

SYSTEM_PROMPT = """You write a daily tech news digest for a personal tech blog.

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

You receive ONE entry of an English tech news digest: its headline, its
factual "summary", and the author's short comedic expert commentary ("take").
Translate all three into every language the user lists.

VOICE: the digest author is a veteran tech expert with a sharp comedic voice -
witty, sarcastic about industry hype, full of playful analogies. Preserve that
exact voice in every language: translate the jokes and sarcasm naturally,
never explain them, never flatten the tone. Every edition must read like the
SAME author wrote it, not like a machine translated it.

RULES:
- Write fluent, idiomatic prose per language. Never translate word-for-word.
- Keep product, company and people names in their conventional form for that
  language (usually the original Latin form).
- Do not add, drop or soften any information. Keep every number unchanged.
- "title" is the digest headline: translate it too.
- "zh" means Simplified Chinese.

Return STRICT JSON only, no markdown fences, one object per requested
language code, always the same three fields, for example:
{"fa": {"title": "...", "summary": "...", "take": "..."}, "fr": {"title": "...", "summary": "...", "take": "..."}}
"""


def language_name(code: str) -> str:
    """Map a language code to a readable name; unknown codes pass through."""
    return _LANGUAGE_NAMES.get(code.strip().lower(), code)


def build_messages(article: Article, language: str = "en") -> list[dict]:
    """OpenAI-style chat messages: system persona + one user message per article."""
    system = SYSTEM_PROMPT.replace("__LANGUAGE__", language_name(language))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _user_content(article)},
    ]


def build_translation_messages(entry: dict, targets: list[str]) -> list[dict]:
    """Chat messages for translating one finished digest entry into targets."""
    names = ", ".join(f"{language_name(code)} ({code})" for code in targets)
    shape = ", ".join(
        f'"{code}": {{"title": "...", "summary": "...", "take": "..."}}'
        for code in targets
    )
    user = "\n".join([
        f"Target languages: {names}.",
        f"Return exactly these top-level keys: {{{shape}}}",
        "",
        "Entry to translate (JSON):",
        json.dumps(entry, ensure_ascii=True),
    ])
    return [
        {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _user_content(article: Article) -> str:
    """Compact article fact sheet for the model."""
    published = (
        article.published_at.strftime("%Y-%m-%d %H:%M UTC")
        if article.published_at else "unknown"
    )
    excerpt = article.raw_summary or "(none provided - rely on the title)"
    return "\n".join([
        f"Title: {article.title}",
        f"Source: {article.source}",
        f"URL: {article.url}",
        f"Category: {article.meta.get('category', 'general')}",
        f"Published: {published}",
        f"Coverage: {article.meta.get('coverage', 1)} source(s)",
        f"Engagement: signal={article.signal_score:.0f}, "
        f"comments={article.meta.get('num_comments', 0)}",
        "",
        "Excerpt:",
        excerpt,
    ])
