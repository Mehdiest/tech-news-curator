---
layout: home
title: "Tech Digest - Daily Tech News by Mehdi Esteghlal"
description: "Daily tech news digest: top stories ranked across 16+ sources, summarized with expert commentary, curated by Mehdi Esteghlal. Published in English, Persian, French, German, Spanish and Chinese."
---

<section class="hero">
  <h1>Tech Digest</h1>
  <p class="tagline">
    Every morning, the loudest stories in tech - ranked across 16+ sources,
    summarized factually, and commented by a veteran expert with a sense of humor.
  </p>
  <p class="langs-available">
    Read in your language:
    <span class="lang-name">English</span> &middot;
    <span class="lang-name">فارسی</span> &middot;
    <span class="lang-name">Français</span> &middot;
    <span class="lang-name">Deutsch</span> &middot;
    <span class="lang-name">Español</span> &middot;
    <span class="lang-name">中文</span>
    - every edition below ships in all six.
  </p>
  <p class="byline">
    Curated by
    <a href="{{ site.author.linkedin }}" rel="me">Mehdi Esteghlal</a>
    &middot; <a href="{{ site.author.github }}" rel="me">GitHub</a>
  </p>
</section>

<section class="digest-archive" id="latest-digests">
  <h2>Latest digests</h2>
  <ul class="digest-list">
    {% assign digests = site.pages | where_exp: "item", "item.path contains 'posts/'" | where_exp: "item", "item.lang == 'en'" | sort: "date" | reverse %}
    {% for digest in digests %}
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
    {% endfor %}
  </ul>
  <p class="subscribe">
    Subscribe via <a href="{{ 'feed.xml' | relative_url }}">RSS</a> - new digest every morning.
  </p>
</section>
