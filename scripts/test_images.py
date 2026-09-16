"""Unit tests for image extraction and enrichment helpers (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser

from src.ingestion.reddit_source import RedditSource
from src.ingestion.rss_source import RSSSource
from src.models import Article, is_valid_image_url, looks_like_image_url
from src.pipeline.images import extract_og_image

FEED_URL = "https://example.com/feed.xml"

# One feed, five entries: media:content, media_thumbnail, enclosure,
# inline <img>, and no image at all.
FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>t</title><link>https://example.com</link>
<item><title>With Media Content</title><link>https://example.com/a</link>
  <media:content url="https://cdn.example.com/a.jpg" medium="image"/></item>
<item><title>With Thumbnail</title><link>https://example.com/b</link>
  <media:thumbnail url="https://cdn.example.com/b.jpg"/></item>
<item><title>With Enclosure</title><link>https://example.com/c</link>
  <enclosure url="https://cdn.example.com/c.png" type="image/png"/></item>
<item><title>With Inline Img</title><link>https://example.com/d</link>
  <description>&lt;p&gt;hi&lt;img src="https://cdn.example.com/d.webp"&gt;&lt;/p&gt;</description></item>
<item><title>Without Image</title><link>https://example.com/e</link>
  <description>plain text only</description></item>
</channel></rss>
"""


def test_rss_image_extraction_priority():
    entries = feedparser.parse(FEED_XML.encode("utf-8")).entries
    assert len(entries) == 5
    extract = lambda entry: RSSSource._extract_image(entry, FEED_URL)
    assert extract(entries[0]) == "https://cdn.example.com/a.jpg"
    assert extract(entries[1]) == "https://cdn.example.com/b.jpg"
    assert extract(entries[2]) == "https://cdn.example.com/c.png"
    assert extract(entries[3]) == "https://cdn.example.com/d.webp"
    assert extract(entries[4]) is None
    print("PASS rss media_content/media_thumbnail/enclosure/inline-img/no-image")


def test_rss_rejects_bad_urls():
    entry = feedparser.parse(
        f"""<rss><channel><item><title>x</title><link>https://example.com/x</link>
        <media:thumbnail url="/relative/icon.gif"/></item></channel></rss>"""
        .encode("utf-8")
    ).entries[0]
    assert RSSSource._extract_image(entry, FEED_URL) == "https://example.com/relative/icon.gif"
    entry_no_url = feedparser.parse(
        b"<rss><channel><item><title>y</title><link>https://example.com/y</link>"
        b'<media:content url="data:image/png;base64,AAAA"/></item></channel></rss>'
    ).entries[0]
    assert RSSSource._extract_image(entry_no_url, FEED_URL) is None
    print("PASS relative URLs resolved against the feed, data: URIs rejected")


def test_reddit_preview_and_thumbnail():
    escaped = "https://preview.redd.it/pic.jpg?width=640&crop=smart&auto=webp"
    post = {"preview": {"images": [{"source": {"url": escaped.replace("&", "&amp;")}}]}}
    assert RedditSource._post_image(post) == escaped  # &amp; unescaped exactly once
    assert RedditSource._post_image({"thumbnail": "https://b.thumbs.redd.it/t.jpg"}) \
        == "https://b.thumbs.redd.it/t.jpg"
    assert RedditSource._post_image({"thumbnail": "self"}) is None
    assert RedditSource._post_image({}) is None
    print("PASS reddit preview (html-unescaped) > thumbnail > none")


def test_og_image_extraction():
    assert extract_og_image(
        '<html><head><meta property="og:image" content="https://site.com/lead.jpg">'
    ) == "https://site.com/lead.jpg"
    assert extract_og_image(  # content attribute BEFORE property
        '<meta content="https://site.com/lead.jpg" property="og:image">'
    ) == "https://site.com/lead.jpg"
    assert extract_og_image(
        '<meta name="twitter:image" content=" https://site.com/tw.png ">'
    ) == "https://site.com/tw.png"
    assert extract_og_image(
        '<meta property="og:image:secure_url" content="https://site.com/s.jpg">'
    ) == "https://site.com/s.jpg"
    assert extract_og_image(
        '<meta property="og:title" content="not an image">'
        '<meta property="og:image" content="data:image/png;base64,AAAA">'
        '<meta property="og:image" content="https://site.com/ok.jpg">'
    ) == "https://site.com/ok.jpg"  # invalid candidates are skipped, not fatal
    assert extract_og_image("<p>no meta tags here</p>") is None
    print("PASS og:image/twitter:image extraction with attribute order + validation")


def test_url_helpers():
    assert is_valid_image_url("https://a.com/x.jpg?a=1&b=2")
    assert is_valid_image_url("http://a.com/x")
    assert not is_valid_image_url("data:image/png;base64,AAAA")
    assert not is_valid_image_url("ftp://a.com/x.jpg")
    assert not is_valid_image_url("/relative/path.jpg")
    assert not is_valid_image_url(None)
    assert not is_valid_image_url("https://a.com/" + "x" * 2100)
    assert looks_like_image_url("https://a.com/x.JPG?w=1")
    assert looks_like_image_url("https://a.com/x.avif")
    assert not looks_like_image_url("https://a.com/article.html")
    print("PASS is_valid_image_url / looks_like_image_url")


def test_drop_blocked_images():
    """Blocklist policy: Reddit-hosted images dropped (Reddit is filtered in
    Iran), publisher-hosted images kept, missing blocklist keeps everything."""
    from src.pipeline.images import drop_blocked_images

    def article(image_url):
        return Article(
            title="t", url=f"https://example.com/{abs(hash(image_url))}",
            source="Reddit", published_at=None, signal_score=1, image_url=image_url,
        )

    reddit_preview = article("https://preview.redd.it/pic.jpg?width=640&auto=webp")
    reddit_thumb = article("https://b.thumbs.redd.it/t.jpg")
    publisher = article("https://cdn.example.com/lead.jpg")
    no_image = article(None)
    articles = [reddit_preview, reddit_thumb, publisher, no_image]

    dropped = drop_blocked_images(articles, ["redd.it"])
    assert dropped == 2
    assert reddit_preview.image_url is None and reddit_thumb.image_url is None
    assert publisher.image_url == "https://cdn.example.com/lead.jpg"

    # no blocklist / empty list = no-op
    assert drop_blocked_images(articles, None) == 0
    assert drop_blocked_images(articles, []) == 0
    # full domain labels only: lookalike hosts survive a redd.it entry
    lookalike = article("https://notredd.it.com/keep-me.jpg")
    assert drop_blocked_images([lookalike], ["redd.it"]) == 0
    assert lookalike.image_url.endswith("keep-me.jpg")
    print("PASS drop_blocked_images: redd.it dropped, publisher kept, lookalikes safe")


def test_validate_image_url_with_local_server():
    """HEAD-validation: good URLs kept, Apple-style cache-buster queries stripped,
    broken/HTML responses rejected, HEAD-405 servers tolerated."""
    import asyncio

    import aiohttp
    from aiohttp import web

    from src.pipeline.images import validate_image_url

    async def serve_image(request):
        return web.Response(body=b"x", content_type="image/jpeg")

    async def cached_image(request):
        # 200 only without a query string - the Apple newsroom CDN behavior
        if request.query:
            raise web.HTTPNotFound
        return web.Response(body=b"x", content_type="image/jpeg")

    async def missing(request):
        raise web.HTTPNotFound

    async def html_page(request):
        return web.Response(body=b"<html/>", content_type="text/html")

    async def run_case():
        app = web.Application()
        app.router.add_get("/good.jpg", serve_image)
        app.router.add_get("/cached.jpg", cached_image)
        app.router.add_get("/missing.jpg", missing)
        app.router.add_get("/nohead.jpg", serve_image, allow_head=False)
        app.router.add_get("/html.jpg", html_page)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        base = f"http://127.0.0.1:{runner.addresses[0][1]}"
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as session:
            results = {
                "good": await validate_image_url(session, f"{base}/good.jpg"),
                "cached": await validate_image_url(session, f"{base}/cached.jpg?v=123"),
                "missing": await validate_image_url(session, f"{base}/missing.jpg"),
                "nohead": await validate_image_url(session, f"{base}/nohead.jpg"),
                "html": await validate_image_url(session, f"{base}/html.jpg"),
            }
        await runner.cleanup()
        return results

    results = asyncio.run(run_case())
    assert results["good"].endswith("/good.jpg")
    assert results["cached"].endswith("/cached.jpg")  # query stripped, image kept
    assert results["missing"] is None
    assert results["nohead"].endswith("/nohead.jpg")  # HEAD 405 tolerated
    assert results["html"] is None
    print("PASS validate_image_url keeps working URLs, strips bad queries, drops broken")


if __name__ == "__main__":
    test_rss_image_extraction_priority()
    test_rss_rejects_bad_urls()
    test_reddit_preview_and_thumbnail()
    test_og_image_extraction()
    test_url_helpers()
    test_drop_blocked_images()
    test_validate_image_url_with_local_server()
    print("\nAll image tests passed.")
