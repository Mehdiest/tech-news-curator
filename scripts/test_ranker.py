"""Unit tests for the stage-3 ranker (no network needed)."""

import math
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Article, utc_now
from src.pipeline.ranker import Ranker, RankerConfig


def make_article(title="Test story", signal=0.0, coverage=1, hours_old=1.0,
                 comments=0, category="general"):
    meta = {"coverage": coverage, "num_comments": comments, "category": category}
    published = utc_now() - timedelta(hours=hours_old) if hours_old is not None else None
    return Article(
        title=title,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        source="TestSrc",
        published_at=published,
        signal_score=signal,
        meta=meta,
    )


def test_coverage_component():
    ranker = Ranker()
    one = ranker.explain(make_article(coverage=1))["coverage"]
    three = ranker.explain(make_article(coverage=3))["coverage"]
    assert abs(one - 6.0) < 1e-9, one            # log2(2) * 6
    assert abs(three - 12.0) < 1e-9, three       # log2(4) * 6
    print("PASS coverage component")


def test_signal_is_log_scaled():
    ranker = Ranker()
    low = ranker.explain(make_article(signal=50))["signal"]
    high = ranker.explain(make_article(signal=500))["signal"]
    assert abs(low - 4 * math.log1p(50)) < 1e-9, low        # log1p(50) = ln(51)
    assert abs(high - 4 * math.log1p(500)) < 1e-9, high     # log1p(500)
    assert high < low * 3, "log scale must dampen the 10x signal gap"
    print("PASS signal log-scaling")


def test_recency_decay():
    ranker = Ranker()
    fresh = ranker.explain(make_article(hours_old=1))["recency"]
    old = ranker.explain(make_article(hours_old=48))["recency"]
    none = ranker.explain(make_article(hours_old=None))["recency"]
    assert 9.0 < fresh < 10.0, fresh              # ~10 * 0.5^(1/24)
    assert abs(old - 2.5) < 1e-9, old             # exactly two half-lives
    assert none == 0.0, none
    print("PASS recency decay")


def test_category_bonus():
    ranker = Ranker(RankerConfig.from_config(
        {"category_weights": {"ai": 2.0, "general": 0.0}}
    ))
    ai = ranker.explain(make_article(category="ai"))["category"]
    general = ranker.explain(make_article(category="general"))["category"]
    unknown = ranker.explain(make_article(category="weird"))["category"]
    assert ai == 2.0 and general == 0.0 and unknown == 0.0
    print("PASS category bonus")


def test_rank_ordering_and_meta():
    ranker = Ranker()
    hot_covered = make_article("Covered story", signal=200, coverage=3, hours_old=2)
    fresh_plain = make_article("Fresh plain", signal=0, coverage=1, hours_old=1)
    stale_big = make_article("Stale big", signal=800, coverage=1, hours_old=200)
    ranked = ranker.rank([stale_big, fresh_plain, hot_covered])
    assert [a.title for a in ranked] == ["Covered story", "Stale big", "Fresh plain"], \
        [a.title for a in ranked]
    assert ranked[0].meta["rank"] == 1
    assert ranked[0].meta["rank_score"] >= ranked[-1].meta["rank_score"]
    assert set(ranked[0].meta["score_parts"]) == {
        "coverage", "signal", "comments", "category", "recency",
    }
    top_only = ranker.rank([hot_covered, fresh_plain, stale_big], top_n=2)
    assert len(top_only) == 2
    assert ranker.rank([]) == []
    print("PASS rank ordering, meta annotation, top_n, empty input")


def test_explain_sums_to_score():
    ranker = Ranker()
    article = make_article(signal=120, coverage=2, comments=40, category="ai")
    parts = ranker.explain(article)  # one snapshot; recency uses utc_now()
    assert abs(ranker.score(article) - sum(parts.values())) < 1e-6
    print("PASS score equals sum of parts")


def test_from_config():
    cfg = RankerConfig.from_config({
        "coverage_weight": 8, "unknown_key": 1, "category_weights": {"dev": 0.5},
    })
    assert cfg.coverage_weight == 8.0
    assert cfg.category_weights == {"dev": 0.5}
    assert RankerConfig.from_config(None).coverage_weight == 6.0  # defaults
    print("PASS from_config parsing")


if __name__ == "__main__":
    test_coverage_component()
    test_signal_is_log_scaled()
    test_recency_decay()
    test_category_bonus()
    test_rank_ordering_and_meta()
    test_explain_sums_to_score()
    test_from_config()
    print("\nAll ranker tests passed.")
