"""Stage 3 ranking: coverage + engagement signal + recency + category bonus.

Score = coverage_w * log2(1 + sources)
      + signal_w   * log1p(points/ups)
      + comments_w * log1p(num_comments)
      + category bonus (flat, config-driven)
      + recency_w  * 0.5 ** (age_hours / half_life)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from src.models import Article, utc_now

logger = logging.getLogger(__name__)

_FLOAT_KEYS = (
    "coverage_weight",
    "signal_weight",
    "comments_weight",
    "recency_weight",
    "recency_half_life_hours",
)


@dataclass
class RankerConfig:
    """Tunable weights; loaded from the `ranker` block of sources.yaml."""

    coverage_weight: float = 6.0
    signal_weight: float = 4.0
    comments_weight: float = 1.0
    recency_weight: float = 10.0
    recency_half_life_hours: float = 24.0
    category_weights: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict | None) -> "RankerConfig":
        """Build a config from the yaml block; unknown keys are ignored."""
        cfg = cfg or {}
        values = {key: float(cfg[key]) for key in _FLOAT_KEYS if key in cfg}
        values["category_weights"] = {
            str(name): float(weight)
            for name, weight in (cfg.get("category_weights") or {}).items()
        }
        return cls(**values)


class Ranker:
    """Scores articles and returns them sorted by rank_score, best first."""

    def __init__(self, config: RankerConfig | None = None):
        self.cfg = config or RankerConfig()

    def score(self, article: Article) -> float:
        """Weighted sum of all ranking components."""
        return sum(self.explain(article).values())

    def explain(self, article: Article) -> dict[str, float]:
        """Per-component scores; powers the preview breakdown and tuning."""
        coverage = max(1, article.meta.get("coverage", 1))
        comments = max(0, article.meta.get("num_comments") or 0)
        return {
            "coverage": self.cfg.coverage_weight * math.log2(1.0 + coverage),
            "signal": self.cfg.signal_weight * math.log1p(max(article.signal_score, 0.0)),
            "comments": self.cfg.comments_weight * math.log1p(comments),
            "category": self.cfg.category_weights.get(article.meta.get("category"), 0.0),
            "recency": self._recency(article),
        }

    def rank(self, articles: list[Article], top_n: int | None = None) -> list[Article]:
        """Score and sort; annotates meta['rank_score'], meta['rank'], meta['score_parts']."""
        if not articles:
            logger.info("ranker: nothing to rank")
            return []
        for article in articles:
            parts = self.explain(article)
            article.meta["score_parts"] = {name: round(value, 2) for name, value in parts.items()}
            article.meta["rank_score"] = round(sum(parts.values()), 3)
        ranked = sorted(articles, key=lambda item: item.meta["rank_score"], reverse=True)
        for position, article in enumerate(ranked, 1):
            article.meta["rank"] = position
        logger.info("ranker: scored %d articles, best score %.1f", len(ranked), ranked[0].meta["rank_score"])
        return ranked if top_n is None else ranked[:top_n]

    def _recency(self, article: Article) -> float:
        """Exponential decay with a configurable half-life; no date means no bonus."""
        if article.published_at is None:
            return 0.0
        age_hours = max(0.0, (utc_now() - article.published_at).total_seconds() / 3600.0)
        return self.cfg.recency_weight * math.pow(0.5, age_hours / self.cfg.recency_half_life_hours)
