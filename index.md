---
layout: home
title: "TechTally - Daily Tech News by Mehdi Esteghlal"
description: "TechTally: the day's top tech stories, ranked every morning across 16+ sources, summarized with expert commentary, curated by Mehdi Esteghlal. Published in English, Persian, French, German, Spanish and Chinese."
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
    <span class="lang-name">中文</span>
    - every edition ships in all six.
  </p>
  <p class="byline">
    Curated by
    <a href="{{ site.author.linkedin }}" rel="me">Mehdi Esteghlal</a>
    &middot; <a href="{{ site.author.github }}" rel="me">GitHub</a>
  </p>
</section>

<section class="latest-digest" id="today">
  {% include latest_digest.html %}
</section>

<section class="digest-archive" id="digest-archive">
  <h2>Digest archive</h2>
  <p class="archive-note">
    The newest edition is shown above. Every past edition stays online -
    pick any date to read it.
  </p>
  <ul class="digest-list">
    {% assign digests = site.pages | where_exp: "item", "item.path contains 'posts/'" | where_exp: "item", "item.lang == 'en'" | sort: "date" | reverse %}
    {% assign latest_day = site.data.latest_digest.date | date: "%Y-%m-%d" %}
    {% assign prev_month = "" %}
    {% for digest in digests %}
    {% assign digest_day = digest.date | date: "%Y-%m-%d" %}
    {% unless digest_day == latest_day %}
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
