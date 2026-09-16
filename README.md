# Tech News Curator

Daily tech news digest: aggregate from multiple sources, deduplicate, rank, summarize with an LLM, and publish Markdown to GitHub Pages - all driven by GitHub Actions.

## Architecture

```text
RSS (~16 feeds) + Hacker News API + Reddit + (later: GitHub Trending)
        |
        v  Layer 1 - Ingestion (async, parallel)
   list[Article]   (normalized schema, source-agnostic)
        |
        v  Layer 2 - Dedup (normalized URL + fuzzy title)
        |
        v  Layer 3 - Ranking (coverage + signal + recency)
        |
        v  Layer 4 - LLM (GLM for now; provider-agnostic)
        |
        v  Layer 5 - Publish (lead picture per story + summary + expert take)
   posts/YYYY-MM-DD-tech-digest.md  ->  GitHub Pages
        |
        v  Layer 6 - Scheduler + Site
   GitHub Actions daily cron (04:30 UTC = 08:00 Tehran)
   -> commits posts/ -> builds Jekyll -> deploys GitHub Pages
   (sitemap.xml + feed.xml + JSON-LD Person/TechArticle + og tags)
        |
        v  Layer 7 - Translated editions (stage 7)
   the finished English text is translated per language, keeping the
   author's voice: posts/<day>-tech-digest-{fa,fr,de,es,zh}.md
   + language switcher on every page and on the landing page
```

## Project Layout

```text
tech-news-curator/
|-- src/
|   |-- models.py              # Article + CuratedItem + URL/text normalization
|   |-- ingestion/
|   |   |-- base.py            # shared protocol: async fetch() -> list[Article]
|   |   |-- rss_source.py      # parallel feed fetching (aiohttp + feedparser)
|   |   |-- hn_source.py       # Algolia HN API - front_page or top_day mode
|   |   `-- reddit_source.py   # Reddit JSON API - top/hot posts per subreddit
|   |-- pipeline/
|   |   |-- dedup.py           # exact URL + fuzzy title clustering
|   |   |-- ranker.py          # coverage + signal + recency + category scoring
|   |   `-- images.py          # image policy: blocklist + opt-in og:image enrichment + HEAD validation
|   |-- llm/
|   |   |-- base.py            # Summary + LLMProvider protocol + JSON parser + batch runner
|   |   |-- prompts.py         # persona + JSON contract + per-article fact sheet
|   |   |-- glm_provider.py    # OpenAI-compatible client (api.b.ai/v1) with retries
|   |   `-- factory.py         # provider selection from env vars
|   |-- publish/
|   |   `-- markdown_writer.py # daily digest: en edition + translated siblings
|   `-- main.py                # orchestration + CLI
|-- _config.yml                # Jekyll: title/author/sitemap plugin/excludes
|-- _layouts/                  # default + digest + home (og tags, JSON-LD, RTL)
|-- _includes/head.html        # meta, Open Graph, Person schema, css
|-- index.md                   # landing page: digest archive + language links
|-- feed.xml                   # Liquid-rendered RSS of recent digests (en)
|-- robots.txt                 # points crawlers at sitemap.xml
|-- assets/css/style.css       # clean image-friendly styling + RTL support
|-- .github/workflows/daily-run.yml
|-- config/sources.yaml        # feed list and settings - no code changes needed
|-- config/i18n.yaml           # localized labels/native names per language (UTF-8 data)
|-- .env.example
`-- requirements.txt
```

## Progress

- [x] Stage 1 - Ingestion: `models.py` + `rss_source.py` + `hn_source.py` + `reddit_source.py` + `config/sources.yaml`
- [x] Stage 2 - Dedup: exact URL + fuzzy title clustering (`src/pipeline/dedup.py`)
- [x] Stage 3 - Ranking: coverage + signal + comments + recency + category (`src/pipeline/ranker.py`)
- [x] Stage 4 - LLM layer: GLM provider + persona prompts + batch summarization (`src/llm/`)
- [x] Stage 5 - Publish: `posts/YYYY-MM-DD-tech-digest.md` writer (`src/publish/markdown_writer.py`)
- [x] Stage 5b - Images: feed media tags + og:image enrichment + HEAD validation (`src/pipeline/images.py`)
- [x] Stage 6 - Scheduler + Site: Actions cron -> commit posts/ -> Jekyll -> GitHub Pages, with sitemap/feed/JSON-LD/og SEO
- [x] Stage 7 - Multilingual editions: fa/fr/de/es/zh siblings of every digest, voice-preserving translation, RTL fa, language switcher (`config/i18n.yaml`, `translate_batch`)
- [ ] Optional next - Telegram/Twitter forwarding, OAuth for Reddit, embedding-based dedup

## Quick Start

```bash
cd tech-news-curator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # needed from stage 4 (LLM) onward

# Stage 1 test: fetch all sources + print top 10
python -m src.main --preview

# Stage 4 test: fetch, rank, then summarize top 3 with the LLM (needs LLM_API_KEY in .env)
python -m src.main --summarize --limit 3

# Stage 5: write posts/YYYY-MM-DD-tech-digest.md (top N from DAILY_TOP_N, default 8)
python -m src.main --publish

# Re-running the same day is a no-op (idempotent); regenerate on purpose with:
python -m src.main --publish --force

# RSS only, Hacker News only, or Reddit only
python -m src.main --preview --source rss
python -m src.main --preview --source hn --limit 5
python -m src.main --preview --source reddit --limit 5

# Verbose logging for feed debugging
python -m src.main --preview -v
```

## Adding a New Source

One line in `config/sources.yaml` - no code changes:

```yaml
rss:
  - {name: Ars Technica AI, url: "https://arstechnica.com/ai/feed/", category: ai}
```

A broken feed never breaks the pipeline; it only logs a warning while the rest continue.

## Ranking Formula (Stage 3)

```text
score = 6.0 * log2(1 + coverage)         # distinct sources covering the story
      + 4.0 * log1p(signal)              # HN points / Reddit ups (log-dampened)
      + 1.0 * log1p(num_comments)        # discussion depth
      + category bonus                   # ai: 2.0, analysis: 1.0, dev: 0.5
      + 10.0 * 0.5 ** (age_hours / 24)   # recency, 24h half-life
```

All weights live in the `ranker:` block of `config/sources.yaml`; `Ranker.explain()`
returns the per-component breakdown printed by `--preview` (`parts:` line).

## LLM Layer (Stage 4)

One chat completion per article against any OpenAI-compatible endpoint
(default: `https://api.b.ai/v1`, model `glm-5.3`, non-streaming). The model
must answer with strict JSON `{"summary": ..., "take": ...}`; replies are
tolerantly parsed (fences and stray prose are stripped).

- **summary**: 2-4 factual sentences - what happened, who, why it matters.
- **take**: comedic veteran-tech-expert commentary - jokes, analogies, hot
  takes aimed at companies and hype (never at people), ending with one
  grounded insight.

| Env var | Default | Meaning |
|---------|---------|---------|
| `LLM_PROVIDER` | `glm` | key into the provider registry (`src/llm/factory.py`) |
| `LLM_API_KEY` | - | Bearer key; required |
| `LLM_BASE_URL` | `https://api.b.ai/v1` | `/chat/completions` is appended |
| `LLM_MODEL` | `glm-5.3` | model name |
| `LLM_TEMPERATURE` | `0.7` | sampling temperature |
| `LLM_MAX_TOKENS` | `700` | reply cap |
| `LLM_TIMEOUT` | `60` | per-request seconds |
| `DIGEST_LANGUAGE` | `en` | output language of summary + take |

Batch runs use bounded parallelism (3 concurrent) and one automatic retry
with backoff on 429/5xx/timeouts; a failing article never stops the digest.

## Images (Stage 5b) - optional by design

Pictures are a second-option feature: any story without one renders as
clean text-only content, and image problems never break a publish run.

1. **Feed-provided (on by default)**: RSS `media:content` / `media:thumbnail`
   / image enclosures / first inline `<img>`; Reddit high-res `preview`
   image - pictures the sources officially hand out with the story.
2. **Page meta tags (opt-in, default OFF)**: `pipeline.enrich_images` in
   `config/sources.yaml` fetches the publisher page and takes its
   `og:image` / `twitter:image`. Off by default on purpose: it hotlinks the
   publisher's own image URL - some CDNs block that (hotlink protection),
   and embedding a media outlet's picture on your own domain is a copyright
   gray area. Enable only if you accept both risks. When enabled, URLs are
   HEAD-validated before embedding (Apple-style cache-buster 404s are
   retried queryless, dead URLs dropped, 400 KB page cap, failures isolated).
3. **Blocklist**: `pipeline.image_blocklist` drops image hosts that are
   unreachable for the audience. `redd.it` is listed by default because
   Reddit is filtered in Iran - its hosted images would render broken for
   Iranian readers. Empty the list to keep them.

Disable pictures entirely with `pipeline.images: false`.

## Publish Format (Stage 5)

`python -m src.main --publish` writes `posts/YYYY-MM-DD-tech-digest.md`:

```markdown
---
title: "Tech Digest - 2026-09-15"
date: 2026-09-15
items: 3
sources: [HackerNews]
cover: "https://cdn.example.com/lead.jpg"
generator: tech-news-curator
---

## 1. [Story title here](https://...)

![Story title here](https://cdn.example.com/lead.jpg)

**Source:** HackerNews  |  **Topic:** ai  |  **Coverage:** 2 source(s)  |  **Score:** 44.6

**Summary**

Factual 2-4 sentence summary.

**My Take**

> Comedic expert commentary ending with one grounded insight.
```

Items without an available picture render cleanly without one; the first
image doubles as the `cover:` front-matter field for Pages themes. Re-running
`--publish` on the same day is a no-op when the digest already exists (LLM
output is sampled, so a second run - schedule + manual dispatch - would
otherwise overwrite the day's post with different text); use `--force` to
regenerate deliberately. Articles whose summarization failed are skipped
entirely. The publish size defaults to `DAILY_TOP_N` from the environment,
then `ranker.default_top_n` (8).

## Multilingual Editions (Stage 7)

The English digest is the canonical edition. When `languages:` is set in
`config/sources.yaml` (default `[fa, fr, de, es, zh]`), every publish also
writes a sibling file per language:

```text
posts/2026-09-15-tech-digest.md       <- English (canonical)
posts/2026-09-15-tech-digest-fa.md    <- Persian, RTL
posts/2026-09-15-tech-digest-fr.md    <- French
posts/2026-09-15-tech-digest-de.md    <- German
posts/2026-09-15-tech-digest-es.md    <- Spanish
posts/2026-09-15-tech-digest-zh.md    <- Simplified Chinese
```

How it works, and why the author's tone survives translation:

1. The English summaries and takes are written first, exactly as before.
2. `translate_batch` then makes one SMALL chat call per (item, language)
   pair - translating the finished English text with a system prompt that
   pins the persona: translate the jokes, never explain or flatten them.
   Short replies keep the strict-JSON contract reliable; a failing pair
   costs exactly one language of one item (that item falls back to its
   English text there - no crash, no gap in the switcher).
3. Every edition carries localized labels from `config/i18n.yaml` (UTF-8
   data file): headings like `**منبع:**` / `**来源:**`, the byline
   (`گردآوری توسط` / `Curado por`), the intro sentence, and the footer.
   Unknown languages degrade to the English labels.
4. The curator name stays `Mehdi Esteghlal` in Latin script in ALL editions
   so the SEO credit never splits across spellings.
5. Each page gets a switcher line - `**Read this digest in:**` فارسی |
   Français | Deutsch | Español | 中文 - linking to the sibling editions,
   and the English edition's front-matter lists them (`translations:`) so
   the landing page archive renders a language link per digest. Persian
   pages ship `lang: fa` + `dir: rtl`, so Jekyll renders them right-to-left
   (`html[dir]` + RTL stylesheet); `og:locale` and `TechArticle.inLanguage`
   follow the edition language.

Change the language set by editing one line (`languages:` in
`config/sources.yaml`); add a language by adding its code there and its
labels to `config/i18n.yaml`. The whole stage is config-driven and skips
silently when `pipeline.translations: false`.

## Author Attribution & SEO

The `author:` block in `config/sources.yaml` drives everything identity
related. Every daily page carries the curator name in four places: the
front-matter `title` (`Tech Digest - ... | Mehdi Esteghlal`) and `author`
field, a unique per-day meta `description`, a visible byline above the fold
linked to LinkedIn, and footer profile links (LinkedIn + GitHub + repo).
Daily fresh posts with consistent author signals are how the curator's name
climbs search results; the site layer (Stage 6) adds JSON-LD Person schema,
Open Graph cards, a sitemap, and an RSS feed on top of this.

## Deployment (Stage 6)

The `daily-tech-digest` workflow runs the whole loop every morning
(04:30 UTC = 08:00 Tehran, or on demand via *Run workflow*):

```text
publish digest -> commit posts/ -> build Jekyll -> deploy GitHub Pages
```

Days are idempotent: a same-day re-run skips the publish step entirely
(zero LLM calls) because today's digest already exists - schedule and
manual dispatch can never overwrite the day's text with different LLM
samples. The manual *Run workflow* form exposes a `force` input that
calls the publish step with `--force` when you really want a regen.

One-time repo setup (after the first push):

1. Settings > Secrets and variables > Actions > **New secret**: `LLM_API_KEY`.
2. Optional *variable* `LLM_MODEL` (defaults to the zero-balance `qwen3.8-flash`).
3. Pages is enabled automatically by the workflow (`configure-pages` with
   `enablement: true`); the site lands at
   `https://<username>.github.io/tech-news-curator/`.

The deployed site includes, out of the box:

- landing page (`index.md`) listing every digest newest first, with a
  language link row per digest (English, فارسی, Français, Deutsch,
  Español, 中文) and the language names in the hero;
- site-wide footer + header with the curator profile links (rel="me");
- per-page Open Graph/Twitter cards using the digest cover image;
- JSON-LD `Person` schema (sameAs -> LinkedIn/GitHub) on every page and
  `TechArticle` schema on each digest - the strongest author signal for Google;
- `sitemap.xml` (jekyll-sitemap), `feed.xml` (hand-rolled Liquid RSS),
  and `robots.txt` pointing at the sitemap.

The `.env` file is generated at runtime from secrets - it never enters the
repository or the deployed site (`exclude` list in `_config.yml`).

## Data Schema

Every item, regardless of source, is normalized into this shape (`src/models.py`):

| Field | Description |
|-------|-------------|
| `id` | sha1 of the normalized URL - dedup key |
| `title` | headline |
| `url` | original link |
| `source` | source name (`TechCrunch`, `HackerNews`, ...) |
| `published_at` | publication time (always UTC-aware) |
| `raw_summary` | original feed excerpt, if available |
| `signal_score` | HN points / Reddit ups; plain RSS = 0 |
| `image_url` | lead picture (feed-provided, or opt-in og:image enrichment; blocklist-filtered), nullable |
| `meta` | side-channel signals: `num_comments`, `category`, ... |

## Implementation Notes

- All fetches are async and parallel; feedparser (sync) runs inside `asyncio.to_thread` so the event loop never blocks.
- URLs are normalized before hashing (`utm_*`, `ref`, `fbclid`, fragment removed) so dedup is reliable.
- HTTP errors are handled only in the ingestion layer; the rest of the pipeline stays transport-agnostic.
- The LLM layer is defined as a Protocol: swapping GLM for any other provider = one new class + one entry in the factory registry.
- feedparser's `published_parsed` structs are always UTC, hence converted with `calendar.timegm` (not `time.mktime`).
- Reddit uses the public JSON API with a descriptive User-Agent; datacenter IPs (GitHub Actions) may hit 429 rate limits - if that happens, lower `max_per_sub` or add OAuth later.
- Dedup is greedy clustering: the highest-signal copy becomes canonical, and `meta.coverage` counts distinct sources covering the story (ranker input). Near-identical headlines across sites can rarely over-merge; embedding similarity is a later upgrade.
- The ranker is deterministic and explainable: every score decomposes into coverage/signal/comments/category/recency parts, so tuning weights never requires guessing.
- Image URLs are markdown-safe: spaces are percent-encoded and parenthesized paths (Wikipedia thumbnails) are wrapped in angle brackets so the link never breaks.
- Images are policy-driven and optional (second-option, never critical): feed-provided media only by default, publisher-page og:image scraping strictly opt-in (`pipeline.enrich_images`, hotlink + copyright risk), and `pipeline.image_blocklist` (default `redd.it`) drops image hosts that are filtered for the audience (Reddit is filtered in Iran).
- Publish days are idempotent: `existing_editions()` short-circuits a same-day re-run before any LLM call, so double triggers (cron + dispatch) can never replace the day's content with different LLM samples; `--force` (or the workflow `force` dispatch input) overrides.
- Translations always translate the finished English text (never re-summarize from scratch), so all six editions carry the same facts, jokes, and emphasis; per-(item, language) calls keep each reply short enough that strict JSON parsing stays reliable.
- ASCII policy: all code/CI files are pure ASCII; the only UTF-8 files are content - `config/i18n.yaml`, `index.md` language names, and generated posts.

## Maintainer

Built and maintained by [Mehdi Esteghlal](https://ir.linkedin.com/in/mehdi-esteghlal-317a67100) - [GitHub @Mehdiest](https://github.com/Mehdiest).
