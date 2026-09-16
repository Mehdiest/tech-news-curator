"""Unit tests for the stage-4 LLM layer (no network by default).

Run `python scripts/test_llm.py --live` to also probe the real endpoint
with a dummy key: a clean LLMError (e.g. HTTP 401) proves reachability.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.base import LLMError, Summary, parse_summary_json, summarize_batch
from src.llm.factory import make_provider
from src.llm.glm_provider import GLMProvider, _extract_content
from src.llm.prompts import build_messages, language_name
from src.models import Article


def make_article(title="Test story"):
    return Article(
        title=title,
        url="https://example.com/test",
        source="TestSrc",
        published_at=None,
        raw_summary="An excerpt about the story.",
        signal_score=42.0,
        meta={"num_comments": 7, "category": "ai", "coverage": 2},
    )


def test_parse_summary_json():
    clean = '{"summary": "A fact.", "take": "A joke."}'
    fenced = "```json\n" + clean + "\n```"
    prose = "Here you go:\n" + clean + "\nHope that helps!"
    for variant in (clean, fenced, prose):
        summary = parse_summary_json(variant)
        assert summary.llm_summary == "A fact." and summary.personal_take == "A joke."
    print("PASS parse_summary_json (clean, fenced, prose-wrapped)")


def test_parse_summary_json_failures():
    for bad in ("no json at all", '{"summary": "only one field"}', "{}", "{broken"):
        try:
            parse_summary_json(bad)
        except LLMError:
            continue
        raise AssertionError(f"expected LLMError for {bad!r}")
    print("PASS parse_summary_json rejects malformed replies")


def test_prompts():
    article = make_article()
    messages = build_messages(article)  # default language = en
    system, user = messages[0]["content"], messages[1]["content"]
    assert "STRICT JSON" in system and "English" in system
    assert "comedic voice" in system
    assert '{"summary"' in system and '"take"' in system
    for needle in ("Title: Test story", "Source: TestSrc",
                   "URL: https://example.com/test", "signal=42", "Excerpt:"):
        assert needle in user, needle
    assert build_messages(article, "de")[0]["content"].count("German") == 1
    assert language_name("xx") == "xx"  # unknown codes pass through
    print("PASS prompt construction (persona, JSON contract, fact sheet)")


def test_extract_content():
    body = '{"choices": [{"message": {"content": "hello"}}]}'
    assert _extract_content(body) == "hello"
    assert _extract_content('{"choices": [{"message": {"content": null}}]}') == ""
    for bad in ("not json", '{"choices": []}', '{"other": 1}'):
        try:
            _extract_content(bad)
        except LLMError:
            continue
        raise AssertionError(f"expected LLMError for {bad!r}")
    print("PASS _extract_content shape handling")


def test_provider_init():
    provider = GLMProvider(api_key="k", base_url="https://api.b.ai/v1/")
    assert provider.url == "https://api.b.ai/v1/chat/completions"
    assert provider.model == "glm-5.3" and provider.language == "en"
    try:
        GLMProvider(api_key="")
    except ValueError:
        print("PASS provider init (url join, defaults, empty key rejected)")
        return
    raise AssertionError("empty api_key must raise ValueError")


def test_factory():
    os.environ.update({
        "LLM_PROVIDER": "glm", "LLM_API_KEY": "k",
        "LLM_BASE_URL": "https://api.b.ai/v1", "LLM_MODEL": "glm-5.3",
    })
    provider = make_provider()
    assert isinstance(provider, GLMProvider) and provider.api_key == "k"
    os.environ["LLM_PROVIDER"] = "does-not-exist"
    try:
        make_provider()
    except ValueError:
        os.environ["LLM_PROVIDER"] = "glm"
        print("PASS factory (env-driven build, unknown provider rejected)")
        return
    raise AssertionError("unknown provider must raise ValueError")


async def _batch_flow():
    class FakeProvider:
        name = "fake"

        async def summarize(self, article):
            if article.title == "boom":
                raise LLMError("planned failure")
            return Summary(llm_summary="s", personal_take="t")

    articles = [make_article("ok-1"), make_article("boom"), make_article("ok-2")]
    pairs = await summarize_batch(FakeProvider(), articles, concurrency=2)
    assert [summary for _, summary in pairs] == [
        Summary("s", "t"), None, Summary("s", "t"),
    ]
    print("PASS summarize_batch (order kept, failures isolated as None)")


def test_batch():
    asyncio.run(_batch_flow())


async def _live_probe():
    provider = GLMProvider(api_key="dummy-key-probe", model="glm-5.3")
    try:
        await provider.summarize(make_article("Live probe"))
    except LLMError as error:
        print(f"PASS live probe - endpoint reachable, clean error: {str(error)[:90]}")
        return
    print("NOTE live probe unexpectedly succeeded with a dummy key")


def test_live_probe():
    asyncio.run(_live_probe())


if __name__ == "__main__":
    test_parse_summary_json()
    test_parse_summary_json_failures()
    test_prompts()
    test_extract_content()
    test_provider_init()
    test_factory()
    test_batch()
    if "--live" in sys.argv:
        test_live_probe()
    print("\nAll LLM layer tests passed.")
