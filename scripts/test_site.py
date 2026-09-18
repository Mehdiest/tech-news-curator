"""Structural tests for the stage-6 GitHub Pages site and the Actions workflow.

Jekyll itself is built remotely by actions/jekyll-build-pages; here we validate
that every config file parses, the workflow wires the full publish pipeline,
and the Liquid templates contain the SEO-critical pieces.
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_config_yml():
    cfg = yaml.safe_load((ROOT / "_config.yml").read_text(encoding="utf-8"))
    assert "Mehdi Esteghlal" in cfg["title"]
    assert "Mehdi Esteghlal" in cfg["description"]
    assert cfg["author"]["linkedin"].startswith("https://ir.linkedin.com/in/")
    assert cfg["author"]["github"] == "https://github.com/Mehdiest"
    assert "jekyll-sitemap" in cfg["plugins"]
    post_defaults = next(d for d in cfg["defaults"] if d["scope"]["path"] == "posts")
    assert post_defaults["values"]["layout"] == "digest"
    for excluded in ("src", "scripts", "config", ".github", ".env"):
        assert excluded in cfg["exclude"], excluded
    print("PASS _config.yml: title/description/author, sitemap plugin, defaults, excludes")


def test_workflow():
    wf = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "daily-run.yml").read_text(encoding="utf-8")
    )
    # two schedules on purpose: primary + same-day safety net (GitHub Actions
    # cron is lossy at popular times; idempotency makes the retry free)
    crons = [entry["cron"] for entry in wf[True]["schedule"]]
    assert crons == ["37 4 * * *", "43 7 * * *"], crons
    assert "workflow_dispatch" in wf[True]  # empty value parses as None
    perms = wf["permissions"]
    assert perms["contents"] == "write" and perms["pages"] == "write"
    assert perms["id-token"] == "write"
    assert perms["actions"] == "write"  # stale-artifact cleanup on re-runs
    steps = wf["jobs"]["publish-and-deploy"]["steps"]
    uses = [step.get("uses", "") for step in steps]
    for action in (
        "actions/checkout", "actions/setup-python", "actions/configure-pages",
        "actions/jekyll-build-pages", "actions/upload-pages-artifact",
        "actions/deploy-pages",
    ):
        assert any(action in u for u in uses), action
    runs = [step.get("run", "") for step in steps]
    assert any("src.main --publish" in r for r in runs)
    # same-day re-runs are idempotent: --force only arrives via a dispatch input
    assert any("--force" in r for r in runs)
    dispatch = wf[True]["workflow_dispatch"]
    assert dispatch["inputs"]["force"]["type"] == "boolean"
    assert dispatch["inputs"]["force"]["default"] is False
    assert any("secrets.LLM_API_KEY" in r for r in runs), "API key must come from secrets"
    assert any("git status --porcelain posts/" in r for r in runs)
    # a silent no-digest outcome must turn the run red; the guard sits after
    # the deploy step so site fixes still ship on broken-LLM days
    assert any("no digest for" in r for r in runs)
    # re-runs must not pile up duplicate github-pages artifacts (deploy-pages
    # aborts on >1), so stale ones are deleted before each upload
    assert any('select(.name == "github-pages")' in r for r in runs)
    # the free-tier default keeps the scheduled run working with zero balance
    assert any("qwen3.8-flash" in r for r in runs)
    # preflight: a malformed secret must fail the run BEFORE ingestion, not
    # only via the end-of-run digest guard; verdicts only, key never logged
    names = [step.get("name", "") for step in steps]
    assert "Validate LLM configuration" in names
    validate_step = next(s for s in steps if s.get("name") == "Validate LLM configuration")
    assert "secrets.LLM_API_KEY" in str(validate_step.get("env", {}))
    validate = validate_step.get("run", "")
    for needle in (
        "LLM_API_KEY is empty", "'Bearer ' prefix",
        "pasted env line", "internal whitespace",
    ):
        assert needle in validate, needle
    print("PASS workflow: dual cron + permissions + publish/commit/Pages deploy chain + secrets + no-digest guard")


def test_templates():
    head = (ROOT / "_includes" / "head.html").read_text(encoding="utf-8")
    for needle in (
        'property="og:title"', 'property="og:image"', 'name="twitter:card"',
        'name="description"', 'rel="alternate" type="application/rss+xml"',
        'property="og:locale"', '"@type": "Person"', '"sameAs"',
        "site.author.linkedin",
    ):
        assert needle in head, needle

    default = (ROOT / "_layouts" / "default.html").read_text(encoding="utf-8")
    assert "site-footer" in default and "site.author.name" in default
    assert 'rel="me"' in default
    # html dir must be derived from page.lang: Jekyll's built-in page.dir (source
    # directory path) shadows any front-matter "dir" value, so rtl never surfaced
    assert 'page.lang | default' in default
    assert 'page.dir' not in default, "page.dir is Jekyll's source dir path, not text direction"
    assert "rtl_langs contains page.lang" in default and "'fa,ar,he,ur'" in default
    # profile sidebar ships on every page and keeps author SEO links
    assert "include sidebar.html" in default
    sidebar = (ROOT / "_includes" / "sidebar.html").read_text(encoding="utf-8")
    assert "site.author.name" in sidebar and 'rel="me"' in sidebar
    # map:"first" over split strings renders empty - initials need slice
    assert 'map: "first"' not in sidebar and "map: 'first'" not in sidebar
    assert "name_words" in sidebar

    digest = (ROOT / "_layouts" / "digest.html").read_text(encoding="utf-8")
    assert '"@type": "TechArticle"' in digest
    assert "datePublished" in digest and "jsonify" in digest
    assert "inLanguage" in digest

    index = (ROOT / "index.md").read_text(encoding="utf-8")
    assert "item.path contains 'posts/'" in index and 'rel="me"' in index
    assert "Mehdi Esteghlal" in index
    # stage 7: archive lists English editions only, each with language links
    assert "item.lang == 'en'" in index
    assert "t.file | relative_url" in index and "hreflang" in index
    assert "\u0641\u0627\u0631\u0633\u06cc" in index and "\u4e2d\u6587" in index

    feed = (ROOT / "feed.xml").read_text(encoding="utf-8")
    assert "<rss version=\"2.0\">" in feed and "xml_escape" in feed
    assert "date_to_rfc822" in feed
    assert "item.lang == 'en'" in feed  # no translated siblings in the feed

    robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
    assert "sitemap.xml" in robots

    css = (ROOT / "assets" / "css" / "style.css").read_text(encoding="utf-8")
    for selector in (".digest img", ".digest blockquote", ".site-footer", ".hero",
                     ".digest-list p.langs", '[dir="rtl"] .digest blockquote'):
        assert selector in css
    print("PASS templates: head meta/og/jsonld, digest TechArticle, index, feed, robots, css")


def test_i18n_yaml():
    i18n = yaml.safe_load((ROOT / "config" / "i18n.yaml").read_text(encoding="utf-8"))
    required = {
        "native_name", "dir", "og_locale", "intro", "read_in", "curated_by",
        "footer_by", "generated", "source", "topic", "coverage",
        "source_word", "score", "summary_h", "take_h",
    }
    assert set(i18n) == {"en", "fa", "fr", "de", "es", "zh"}
    for code, block in i18n.items():
        assert required <= set(block), (code, required - set(block))
    assert i18n["en"]["dir"] == "ltr"
    assert i18n["fa"]["dir"] == "rtl"
    assert i18n["fa"]["native_name"] == "\u0641\u0627\u0631\u0633\u06cc"
    assert i18n["zh"]["og_locale"] == "zh_CN"
    # sources.yaml drives which editions get built
    sources = yaml.safe_load(
        (ROOT / "config" / "sources.yaml").read_text(encoding="utf-8")
    )
    assert sources["languages"] == ["fa", "fr", "de", "es", "zh"]
    assert sources["pipeline"]["translations"] is True
    # image policy: feed-provided pictures only; og:image scraping is opt-in;
    # Reddit-hosted images are dropped (Reddit is filtered in Iran)
    pipeline = sources["pipeline"]
    assert pipeline["images"] is True
    assert pipeline["enrich_images"] is False
    assert "redd.it" in pipeline["image_blocklist"]
    print("PASS i18n.yaml: six languages, complete label sets, RTL fa, config wiring")


def test_llm_key_guardrails():
    """The 401 'Invalid api_key format' preflight must live in the provider."""
    src = (ROOT / "src" / "llm" / "glm_provider.py").read_text(encoding="utf-8")
    assert "def _validate_api_key" in src
    assert "_validate_api_key(api_key)" in src  # actually called in __init__
    assert "bearer" in src.lower()  # 'Bearer ' prefix rejection
    assert "LLM_API_KEY" in src and "isspace" in src
    factory = (ROOT / "src" / "llm" / "factory.py").read_text(encoding="utf-8")
    assert 'os.getenv("LLM_API_KEY", "")' in factory  # empty key still surfaces
    print("PASS glm_provider: api-key preflight (edge cleaning + Bearer/assignment/whitespace rejection)")


def test_ascii_sources():
    """Source files stay pure ASCII English (i18n.yaml + posts/ are exempt)."""
    for rel in (
        "src/llm/glm_provider.py", "src/llm/factory.py", "src/llm/base.py",
        ".github/workflows/daily-run.yml", "scripts/test_site.py",
        "_includes/sidebar.html", "_layouts/default.html", "_config.yml",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        bad = [(i, ch) for i, ch in enumerate(text) if ord(ch) > 127]
        assert not bad, (rel, bad[:3])
    print("PASS ascii: source/workflow/template files are pure ASCII")


def test_site_files_exist():
    for rel in (
        "_config.yml", "index.md", "feed.xml", "robots.txt",
        "_includes/head.html", "_includes/sidebar.html", "_layouts/default.html",
        "_layouts/digest.html", "_layouts/home.html",
        "assets/css/style.css", ".github/workflows/daily-run.yml",
        "config/i18n.yaml",
    ):
        assert (ROOT / rel).is_file(), rel
    print("PASS all stage-6/7 site files exist")


if __name__ == "__main__":
    test_config_yml()
    test_workflow()
    test_templates()
    test_i18n_yaml()
    test_llm_key_guardrails()
    test_ascii_sources()
    test_site_files_exist()
    print("\nAll site tests passed.")
