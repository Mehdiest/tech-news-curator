---
layout: home
title: "TechTally - Daily Tech News by Mehdi Esteghlal"
description: "TechTally: the day's top tech stories, ranked every morning across 16+ sources, summarized with expert commentary, curated by Mehdi Esteghlal. Published in English, Persian, French, German, Spanish, Chinese, Hindi, Russian and Arabic."
---

<section class="hero">
  <h1>TechTally</h1>
  <p class="tagline"><strong>{{ site.tagline }}</strong></p>
  <p class="tagline">
    An automated pipeline reads 16+ sources every morning - RSS feeds, Hacker News,
    and Reddit - clusters the stories everyone is covering, and ranks them by real
    signal: media coverage, community reaction, and how fresh they are. Each top
    story gets a factual summary plus a short, opinionated take, so you get the
    news and the "why it matters" in under two minutes.
  </p>
  <p class="langs-available">
    Read in your language:
    <span class="lang-name">English</span> &middot;
    <span class="lang-name">فارسی</span> &middot;
    <span class="lang-name">Français</span> &middot;
    <span class="lang-name">Deutsch</span> &middot;
    <span class="lang-name">Español</span> &middot;
    <span class="lang-name">中文</span> &middot;
    <span class="lang-name">हिन्दी</span> &middot;
    <span class="lang-name">Русский</span> &middot;
    <span class="lang-name">العربية</span>
    - every edition ships in all nine.
  </p>
  <p class="byline">
    Curated by
    <a href="{{ site.author.linkedin }}" rel="me">Mehdi Esteghlal</a>
    &middot; <a href="{{ site.author.github }}" rel="me">GitHub</a>
  </p>
</section>

<!-- Compact teaser card for the newest digest. Clicking opens the standalone
     post page (where the share buttons and all six editions live). The old
     full-content inline render made the home page enormous and hid the
     archive, so it is replaced by this card. -->
{% assign latest_post = site.pages | where_exp: "item", "item.path contains 'posts/'" | where_exp: "item", "item.lang == 'en'" | sort: "date" | reverse | first %}
{% if latest_post %}
<section class="latest-digest" id="today">
  <div class="latest-card">
    <p class="latest-kicker">Latest digest &middot; {{ latest_post.date | date: "%B %d, %Y" }}</p>
    <h2><a href="{{ latest_post.url | relative_url }}">{{ latest_post.title }}</a></h2>
    {% if latest_post.description %}
    <p class="latest-desc">{{ latest_post.description | truncatewords: 45 }}</p>
    {% endif %}
    <p class="latest-cta"><a class="read-btn" href="{{ latest_post.url | relative_url }}">Read the full digest &rarr;</a></p>
    <div class="share-row">
      <span class="share-label">Share this digest:</span>
      <a class="share-btn share-tg" target="_blank" rel="noopener"
         href="https://t.me/share/url?url={{ latest_post.url | absolute_url | url_encode }}&text={{ latest_post.title | url_encode }}">Telegram</a>
      <a class="share-btn share-x" target="_blank" rel="noopener"
         href="https://twitter.com/intent/tweet?url={{ latest_post.url | absolute_url | url_encode }}&text={{ latest_post.title | url_encode }}">X</a>
    </div>
  </div>
</section>
{% endif %}

<section class="digest-archive" id="digest-archive">
  <h2>All digests</h2>
  <p class="archive-note">
    Every edition, newest first. Click any title to open that day's digest -
    each one is also available in five more languages on its page.
  </p>
  <ul class="digest-list">
    {% assign digests = site.pages | where_exp: "item", "item.path contains 'posts/'" | where_exp: "item", "item.lang == 'en'" | sort: "date" | reverse %}
    {% assign prev_month = "" %}
    {% for digest in digests %}
    {% unless forloop.first %}
    {% assign this_month = digest.date | date: "%B %Y" %}
    {% if this_month != prev_month %}
    <li class="month-sep"><span>{{ this_month }}</span></li>
    {% assign prev_month = this_month %}
    {% endif %}
    <li>
      <a href="{{ digest.url | relative_url }}">{{ digest.title }}</a>
      <time datetime="{{ digest.date | date_to_xmlschema }}">{{ digest.date | date: "%B %d, %Y" }}</time>
      {% if digest.description %}<p>{{ digest.description }}</p>{% endif %}
      {% if digest.translations %}
      <p class="langs">Also in:
        {% for t in digest.translations %}
        <a href="{{ t.file | relative_url }}" hreflang="{{ t.code }}">{{ t.name }}</a>{% unless forloop.last %} &middot; {% endunless %}
        {% endfor %}
      </p>
      {% endif %}
    </li>
    {% endunless %}
    {% endfor %}
  </ul>
  <p class="subscribe">
    Subscribe via <a href="{{ 'feed.xml' | relative_url }}">RSS</a> - new digest every morning.
  </p>
</section>
