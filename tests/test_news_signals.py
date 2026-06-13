import pytest

from argus.analytics.news_signals import analyze_news_sentiment, source_weight


@pytest.mark.parametrize(
    "title",
    [
        "Company raises guidance after it beats estimates",
        "Strong demand and backlog growth support capacity expansion",
        "Analyst price target raised after company wins contract",
    ],
)
def test_financial_positive_phrases_score_positive(title: str) -> None:
    analysis = analyze_news_sentiment(title, None)

    assert analysis["score"] is not None
    assert analysis["score"] > 0
    assert analysis["positive_matches"]


@pytest.mark.parametrize(
    "title",
    [
        "Company cuts guidance after it misses estimates",
        "Weak demand and margin pressure weigh on shares",
        "SEC investigation follows outage and price target cut",
    ],
)
def test_financial_negative_phrases_score_negative(title: str) -> None:
    analysis = analyze_news_sentiment(title, None)

    assert analysis["score"] is not None
    assert analysis["score"] < 0
    assert analysis["negative_matches"]


def test_phrase_matches_prevent_single_word_double_counting() -> None:
    analysis = analyze_news_sentiment("Company raises guidance", None)

    assert analysis["score"] == pytest.approx(1.0)
    terms = [match["term"] for match in analysis["positive_matches"]]
    assert terms == ["raises guidance"]


@pytest.mark.parametrize(
    "title",
    [
        "Management says demand is not weak",
        "Company reports no delay in data center project",
        "Operations continue without outage",
    ],
)
def test_negation_suppresses_negative_matches(title: str) -> None:
    analysis = analyze_news_sentiment(title, None)

    assert not analysis["negative_matches"]
    assert analysis["score"] is None or analysis["score"] >= 0


def test_mixed_article_produces_moderated_score() -> None:
    analysis = analyze_news_sentiment(
        "Company beats estimates but warns of margin pressure",
        None,
    )

    assert analysis["score"] is not None
    assert -1.0 < analysis["score"] < 1.0
    assert analysis["positive_matches"]
    assert analysis["negative_matches"]


def test_no_match_article_returns_no_score_and_empty_matches() -> None:
    analysis = analyze_news_sentiment("Company hosts annual shareholder meeting", None)

    assert analysis["score"] is None
    assert analysis["positive_matches"] == []
    assert analysis["negative_matches"] == []
    assert analysis["categories"] == []


@pytest.mark.parametrize(
    ("provider", "source_name", "expected"),
    [
        ("rss", "Yahoo Finance", 0.7),
        ("rss", "Reuters", 1.0),
        ("ir_feed", "ANET investor relations", 0.8),
        ("ir_feed", "Reuters", 0.8),
        ("rss", "Unknown Blog", 0.7),
    ],
)
def test_source_weight_rss_defaults(provider: str, source_name: str, expected: float) -> None:
    assert source_weight(provider=provider, source_name=source_name) == pytest.approx(expected)
