"""Stage 2 dedup: exact-URL matching, then greedy fuzzy title clustering."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from src.models import Article

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class _Cluster:
    """One story: the highest-signal article plus the sources covering it."""

    canonical: Article
    norm_title: str = field(init=False)
    sources: set[str] = field(init=False)

    def __post_init__(self) -> None:
        self.norm_title = _normalize_title(self.canonical.title)
        self.sources = {self.canonical.source}
        self.canonical.meta["coverage"] = 1

    def similar_to(self, article: Article, threshold: float) -> bool:
        if article.id == self.canonical.id:
            return True
        candidate = _normalize_title(article.title)
        if not candidate or not self.norm_title:
            return False
        ratio = difflib.SequenceMatcher(None, self.norm_title, candidate).ratio()
        return ratio >= threshold

    def absorb(self, article: Article) -> None:
        if article.source in self.sources:
            return
        self.sources.add(article.source)
        self.canonical.meta["coverage"] = len(self.sources)
        self.canonical.meta["dup_sources"] = sorted(self.sources)


def dedupe(articles: list[Article], title_similarity: float = 0.85) -> list[Article]:
    """Merge same-story articles; the highest-signal copy becomes the canonical one.

    The survivor keeps meta['coverage'] (distinct sources) and meta['dup_sources'],
    which the stage-3 ranker consumes. Ordered processing guarantees that the
    canonical copy is the one with the best signal/date before clustering starts.
    """
    ordered = sorted(articles, key=_canon_key, reverse=True)
    clusters: list[_Cluster] = []
    for article in ordered:
        cluster = _match_cluster(article, clusters, title_similarity)
        if cluster is None:
            clusters.append(_Cluster(article))
        else:
            cluster.absorb(article)
    return [cluster.canonical for cluster in clusters]


def _canon_key(article: Article) -> tuple[float, float]:
    epoch = article.published_at.timestamp() if article.published_at else 0.0
    return (article.signal_score, epoch)


def _match_cluster(article: Article, clusters: list[_Cluster], threshold: float) -> _Cluster | None:
    for cluster in clusters:
        if cluster.similar_to(article, threshold):
            return cluster
    return None


def _normalize_title(title: str) -> str:
    return _NON_ALNUM_RE.sub(" ", title.lower()).strip()
