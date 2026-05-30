import pandas as pd
import pytest

from argus.analytics.scoring import ScoreInputs, compute_opportunity_score, score_pullback, score_risk_penalty


def test_theme_exposure_scales_to_25_points() -> None:
    breakdown = compute_opportunity_score(ScoreInputs(theme_exposure_score=5.0))
    assert breakdown.theme_exposure == pytest.approx(25.0)


def test_missing_metrics_do_not_crash() -> None:
    breakdown = compute_opportunity_score(ScoreInputs())
    assert breakdown.opportunity_score == pytest.approx(0.0)
    assert "unavailable" in breakdown.explanation.lower()


def test_pullback_score_requires_at_least_10_percent_drawdown() -> None:
    score, reasons = score_pullback(-0.08)
    assert score == 0.0
    assert any("10%" in reason for reason in reasons)


def test_pullback_score_maxes_at_30_percent_drawdown() -> None:
    score, _ = score_pullback(-0.35)
    assert score == pytest.approx(25.0)


def test_high_quality_pullback_candidate_scores_well() -> None:
    breakdown = compute_opportunity_score(
        ScoreInputs(
            theme_exposure_score=5.0,
            drawdown_52w=-0.18,
            rsi_14=38.0,
            distance_from_200dma=0.03,
            relative_return_vs_qqq_3m=0.06,
            watch_status="high_priority",
            recent_news_count=2,
            return_1w=-0.03,
        )
    )

    assert breakdown.opportunity_score > 60.0
    assert "Down 18.0% from 52-week high" in breakdown.explanation
    assert "Still above 200DMA" in breakdown.explanation
    assert "Watch status: high priority" in breakdown.explanation


def test_risk_penalty_for_breakdown_below_200dma() -> None:
    penalty, reasons = score_risk_penalty(
        drawdown_52w=-0.40,
        distance_from_200dma=-0.25,
        return_1w=-0.20,
    )
    assert penalty <= -20.0
    assert any("below 200DMA" in reason for reason in reasons)


def test_ignore_watch_status_reduces_priority_score() -> None:
    breakdown = compute_opportunity_score(ScoreInputs(watch_status="ignore"))
    assert breakdown.watchlist_priority == 0.0


def test_explanation_joins_reason_lines() -> None:
    breakdown = compute_opportunity_score(
        ScoreInputs(
            theme_exposure_score=4.0,
            drawdown_52w=-0.15,
            rsi_14=35.0,
            distance_from_200dma=0.01,
            relative_return_vs_qqq_3m=0.02,
            watch_status="watch",
        )
    )
    assert " | " in breakdown.explanation
    assert len(breakdown.reason_lines) >= 5


def test_catalyst_placeholder_when_no_signals() -> None:
    breakdown = compute_opportunity_score(ScoreInputs())
    assert "No recent catalyst signals tracked yet" in breakdown.explanation


def test_opportunity_score_includes_risk_penalty() -> None:
    base = compute_opportunity_score(
        ScoreInputs(
            theme_exposure_score=4.0,
            drawdown_52w=-0.20,
            rsi_14=35.0,
            distance_from_200dma=0.02,
            relative_return_vs_qqq_3m=0.04,
            watch_status="watch",
        )
    )
    risky = compute_opportunity_score(
        ScoreInputs(
            theme_exposure_score=4.0,
            drawdown_52w=-0.20,
            rsi_14=35.0,
            distance_from_200dma=-0.22,
            relative_return_vs_qqq_3m=0.04,
            watch_status="watch",
            return_1w=-0.18,
        )
    )
    assert risky.opportunity_score < base.opportunity_score


def test_pullback_finder_filters_min_drawdown() -> None:
    from argus.services.pullback_finder_service import apply_pullback_filters

    df = pd.DataFrame(
        [
            {"ticker": "AAA", "drawdown_52w": -0.05, "rsi_14": 40.0, "distance_from_200dma": 0.01},
            {"ticker": "BBB", "drawdown_52w": -0.15, "rsi_14": 40.0, "distance_from_200dma": 0.01},
        ]
    )
    filtered = apply_pullback_filters(df, min_drawdown=0.10)
    assert filtered["ticker"].tolist() == ["BBB"]


def test_pullback_finder_filters_dma_position() -> None:
    from argus.services.pullback_finder_service import apply_pullback_filters

    df = pd.DataFrame(
        [
            {"ticker": "AAA", "drawdown_52w": -0.15, "rsi_14": 40.0, "distance_from_200dma": 0.02},
            {"ticker": "BBB", "drawdown_52w": -0.15, "rsi_14": 40.0, "distance_from_200dma": -0.02},
        ]
    )
    above = apply_pullback_filters(df, dma_position="above")
    below = apply_pullback_filters(df, dma_position="below")
    assert above["ticker"].tolist() == ["AAA"]
    assert below["ticker"].tolist() == ["BBB"]


def test_watchlist_priority_none_defaults_to_zero_points() -> None:
    breakdown = compute_opportunity_score(ScoreInputs(watch_status=None))
    assert breakdown.watchlist_priority == 0.0
    assert "Watch status: none" in breakdown.explanation


def test_pd_na_does_not_crash_scoring() -> None:
    # This should not raise TypeError
    breakdown = compute_opportunity_score(
        ScoreInputs(
            theme_exposure_score=pd.NA,
            drawdown_52w=pd.NA,
            rsi_14=pd.NA,
            distance_from_200dma=pd.NA,
            relative_return_vs_qqq_3m=pd.NA,
            watch_status=None,
            recent_news_count=pd.NA,
            recent_filing_count=pd.NA,
            upcoming_earnings_days=pd.NA,
            return_1w=pd.NA,
        )
    )
    # The default score with all NA and watch_status=None should be 0.0, and not crash
    assert breakdown.opportunity_score == 0.0
    assert "unavailable" in breakdown.explanation.lower()


def test_pullback_finder_excludes_benchmarks_and_hyperscalers() -> None:
    from argus.services.pullback_finder_service import apply_pullback_filters

    df = pd.DataFrame(
        [
            {"ticker": "NVDA", "is_benchmark": 1, "is_hyperscaler": 0, "rsi_14": 40.0},
            {"ticker": "MSFT", "is_benchmark": 1, "is_hyperscaler": 1, "rsi_14": 40.0},
            {"ticker": "VERT", "is_benchmark": 0, "is_hyperscaler": 0, "rsi_14": 40.0},
        ]
    )

    # Filter benchmarks
    no_benchmarks = apply_pullback_filters(df, exclude_benchmarks=True)
    assert no_benchmarks["ticker"].tolist() == ["VERT"]

    # Filter hyperscalers
    no_hyperscalers = apply_pullback_filters(df, exclude_hyperscalers=True)
    assert no_hyperscalers["ticker"].tolist() == ["NVDA", "VERT"]


def test_pullback_finder_allows_nan_rsi_under_default_filter() -> None:
    from argus.services.pullback_finder_service import apply_pullback_filters

    df = pd.DataFrame(
        [
            {"ticker": "AAA", "rsi_14": 40.0},
            {"ticker": "BBB", "rsi_14": pd.NA},
        ]
    )
    # Default range is typically (0, 55). Under default, BBB (NaN RSI) should not be filtered out
    filtered = apply_pullback_filters(df, rsi_min=0.0, rsi_max=55.0)
    assert "BBB" in filtered["ticker"].tolist()
    assert "AAA" in filtered["ticker"].tolist()


def test_score_theme_exposure_bounds_and_clamping() -> None:
    from argus.analytics.scoring import score_theme_exposure
    # Clamping negative and > 5.0
    score, reasons = score_theme_exposure(-1.0)
    assert score == 0.0
    assert "Theme exposure 0.0/5" in reasons

    score, reasons = score_theme_exposure(6.5)
    assert score == 25.0
    assert "Theme exposure 5.0/5" in reasons

    score, reasons = score_theme_exposure(None)
    assert score == 0.0
    assert "Theme exposure score unavailable" in reasons


def test_score_pullback_bounds() -> None:
    from argus.analytics.scoring import score_pullback
    # Drawdown magnitude < 10%
    score, reasons = score_pullback(-0.05)
    assert score == 0.0
    assert "need at least 10%" in reasons[0]

    # Drawdown magnitude >= 30%
    score, reasons = score_pullback(-0.35)
    assert score == 25.0
    assert "Down 35.0%" in reasons[0]

    # 10% drawdown
    score, reasons = score_pullback(-0.10)
    assert score == 0.0
    assert "Down 10.0%" in reasons[0]

    # 20% drawdown
    score, reasons = score_pullback(-0.20)
    assert score == 12.5
    assert "Down 20.0%" in reasons[0]


def test_score_technical_setup_all_bins() -> None:
    from argus.analytics.scoring import score_technical_setup
    
    # RSI <= 30 and distance >= 5%
    score, reasons = score_technical_setup(28.0, 0.06)
    assert score == 20.0
    assert any("oversold" in r for r in reasons)
    assert any("above 200DMA" in r for r in reasons)

    # RSI <= 40 and distance >= 0%
    score, reasons = score_technical_setup(35.0, 0.01)
    assert score == 16.0
    assert any("pullback zone" in r for r in reasons)
    assert any("Still above 200DMA" in r for r in reasons)

    # RSI <= 45 and distance >= -5%
    score, reasons = score_technical_setup(43.0, -0.02)
    assert score == 11.0
    assert any("moderate pullback" in r for r in reasons)
    assert any("Near 200DMA" in r for r in reasons)

    # RSI <= 55 and distance >= -10%
    score, reasons = score_technical_setup(50.0, -0.08)
    assert score == 5.0
    assert any("neutral" in r for r in reasons)
    assert any("Slightly below 200DMA" in r for r in reasons)

    # RSI > 55 and distance < -10%
    score, reasons = score_technical_setup(65.0, -0.15)
    assert score == 0.0
    assert any("not oversold" in r for r in reasons)
    assert any("Well below 200DMA" in r for r in reasons)


def test_score_relative_strength_all_bins() -> None:
    from argus.analytics.scoring import score_relative_strength

    # >= 10%
    score, reasons = score_relative_strength(0.12)
    assert score == 15.0
    assert "Outperforming QQQ by 12.0%" in reasons[0]

    # >= 5%
    score, reasons = score_relative_strength(0.06)
    assert score == 12.0

    # >= 0%
    score, reasons = score_relative_strength(0.02)
    assert score == 8.0

    # >= -5%
    score, reasons = score_relative_strength(-0.02)
    assert score == 3.0

    # < -5%
    score, reasons = score_relative_strength(-0.10)
    assert score == 0.0
    assert "Underperforming QQQ by 10.0%" in reasons[0]


def test_score_catalyst_all_bins() -> None:
    from argus.analytics.scoring import score_catalyst

    # High news/filings count
    score, reasons = score_catalyst(recent_news_count=10, recent_filing_count=10)
    assert score == 7.0  # min(4.0 news, 3.0 filings)
    assert any("10 recent news item" in r for r in reasons)

    # Earnings within 14 days
    score, reasons = score_catalyst(upcoming_earnings_days=5)
    assert score == 3.0
    assert any("Earnings in 5 days" in r for r in reasons)


def test_score_risk_penalty_individual_triggers_and_clamping() -> None:
    from argus.analytics.scoring import score_risk_penalty

    # Drawdown <= -35%
    penalty, reasons = score_risk_penalty(drawdown_52w=-0.36, distance_from_200dma=0.0, return_1w=0.0)
    assert penalty == -5.0
    assert any("Deep drawdown risk" in r for r in reasons)

    # Drawdown <= -45%
    penalty, _ = score_risk_penalty(drawdown_52w=-0.48, distance_from_200dma=0.0, return_1w=0.0)
    assert penalty == -10.0

    # Distance < -10%
    penalty, _ = score_risk_penalty(drawdown_52w=0.0, distance_from_200dma=-0.12, return_1w=0.0)
    assert penalty == -8.0

    # Distance < -20%
    penalty, _ = score_risk_penalty(drawdown_52w=0.0, distance_from_200dma=-0.22, return_1w=0.0)
    assert penalty == -15.0

    # 1W Return <= -15%
    penalty, _ = score_risk_penalty(drawdown_52w=0.0, distance_from_200dma=0.0, return_1w=-0.18)
    assert penalty == -5.0

    # All triggers (total -35 clamped to -30)
    penalty, _ = score_risk_penalty(drawdown_52w=-0.48, distance_from_200dma=-0.22, return_1w=-0.18)
    assert penalty == -30.0


def test_maximum_possible_score() -> None:
    # All scores maxed, no penalties
    breakdown = compute_opportunity_score(
        ScoreInputs(
            theme_exposure_score=5.0,
            drawdown_52w=-0.30,
            rsi_14=30.0,
            distance_from_200dma=0.05,
            relative_return_vs_qqq_3m=0.10,
            watch_status="high_priority",
            recent_news_count=5,
            recent_filing_count=2,
            upcoming_earnings_days=10,
            return_1w=0.0,
        )
    )
    # 25 (theme) + 25 (pullback) + 20 (tech: 10 + 10) + 15 (relative) + 10 (catalyst: 4 + 3 + 3) + 5 (watchlist)
    # Total = 100.0
    assert breakdown.opportunity_score == pytest.approx(100.0)


def test_minimum_possible_score() -> None:
    # Everything bad, max penalties
    breakdown = compute_opportunity_score(
        ScoreInputs(
            theme_exposure_score=0.0,
            drawdown_52w=-0.45,
            rsi_14=70.0,
            distance_from_200dma=-0.25,
            relative_return_vs_qqq_3m=-0.10,
            watch_status="ignore",
            recent_news_count=0,
            recent_filing_count=0,
            upcoming_earnings_days=None,
            return_1w=-0.20,
        )
    )
    # Components:
    # theme_exposure = 0
    # pullback = 25 (drawdown >= 30%)
    # tech = 0 (rsi > 55, distance < -10%)
    # relative = 0
    # catalyst = 0
    # watchlist = 0
    # penalty = -30 (drawdown >= 45%: -10, distance < -20%: -15, return_1w <= -15%: -5)
    # Total = 25 - 30 = -5.0
    assert breakdown.opportunity_score == pytest.approx(-5.0)


def test_load_pullback_candidates_joins_and_calculates_correctly(sqlite_engine, db_session) -> None:
    from argus.core.models import Company, Watchlist, WatchlistItem, PriceBar, DailyMetric, Theme, CompanyThemeExposure
    from argus.services.pullback_finder_service import load_pullback_candidates
    from datetime import date
    
    # 1. Create themes and companies
    theme = Theme(code="cooling", name="Cooling")
    db_session.add(theme)
    db_session.flush()
    
    c1 = Company(symbol="VRT", name="Vertiv", sector="Cooling", is_active=True, is_benchmark=False)
    c2 = Company(symbol="NVDA", name="NVIDIA", sector="Benchmarks", is_active=True, is_benchmark=True)
    db_session.add_all([c1, c2])
    db_session.flush()
    
    # 2. Exposure
    cte = CompanyThemeExposure(company_id=c1.id, theme_id=theme.id, exposure_score=4.0)
    db_session.add(cte)
    
    # 3. Watchlist
    w1 = Watchlist(name="Cooling", is_system=True)
    w2 = Watchlist(name="Benchmarks", is_system=True)
    db_session.add_all([w1, w2])
    db_session.flush()
    
    wi1 = WatchlistItem(watchlist_id=w1.id, company_id=c1.id, watch_status="high_priority")
    wi2 = WatchlistItem(watchlist_id=w2.id, company_id=c2.id, watch_status="watch")
    db_session.add_all([wi1, wi2])
    
    # 4. PriceBars
    pb1 = PriceBar(company_id=c1.id, date=date(2026, 5, 29), adj_close=100.0, provider="yfinance", interval="1d")
    pb2 = PriceBar(company_id=c2.id, date=date(2026, 5, 29), adj_close=900.0, provider="yfinance", interval="1d")
    db_session.add_all([pb1, pb2])
    
    # 5. DailyMetrics
    dm1 = DailyMetric(
        company_id=c1.id,
        date=date(2026, 5, 29),
        drawdown_52w=-0.15,
        rsi_14=35.0,
        distance_from_200dma=0.02,
        relative_return_vs_qqq_3m=0.04,
        return_1w=-0.02,
    )
    dm2 = DailyMetric(
        company_id=c2.id,
        date=date(2026, 5, 29),
        drawdown_52w=-0.05,
        rsi_14=60.0,
        distance_from_200dma=0.15,
        relative_return_vs_qqq_3m=0.12,
        return_1w=0.01,
    )
    db_session.add_all([dm1, dm2])
    
    db_session.commit()
    
    # Run load_pullback_candidates
    candidates = load_pullback_candidates(sqlite_engine)
    
    assert len(candidates) == 2
    # Verify the values
    vrt = candidates[candidates["ticker"] == "VRT"].iloc[0]
    nvda = candidates[candidates["ticker"] == "NVDA"].iloc[0]
    
    assert vrt["price"] == 100.0
    assert vrt["drawdown_52w"] == -0.15
    assert vrt["theme_exposure_score"] == 4.0
    assert vrt["opportunity_score"] > 0


def test_watchlist_update_propagates_to_opportunity_score(sqlite_engine, db_session, monkeypatch) -> None:
    from argus.core.models import Company, Watchlist, WatchlistItem, PriceBar, DailyMetric
    from argus.services.pullback_finder_service import load_pullback_candidates
    from argus.services.watchlist_service import update_watchlist_items
    from argus.core import db as db_module
    from datetime import date
    from sqlalchemy.orm import Session, sessionmaker

    # Patch session maker for watchlist_service
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    # 1. Seed data
    c = Company(symbol="VRT", name="Vertiv", sector="Cooling", is_active=True)
    db_session.add(c)
    db_session.flush()

    w = Watchlist(name="Cooling", is_system=True)
    db_session.add(w)
    db_session.flush()

    wi = WatchlistItem(watchlist_id=w.id, company_id=c.id, watch_status="watch")
    db_session.add(wi)

    pb = PriceBar(company_id=c.id, date=date(2026, 5, 29), adj_close=100.0, provider="yfinance", interval="1d")
    db_session.add(pb)

    dm = DailyMetric(
        company_id=c.id,
        date=date(2026, 5, 29),
        drawdown_52w=-0.15,
        rsi_14=35.0,
        distance_from_200dma=0.02,
        relative_return_vs_qqq_3m=0.04,
        return_1w=-0.02,
    )
    db_session.add(dm)
    db_session.commit()

    # 2. First candidate load: watch_status is "watch" (3.0 watchlist points)
    candidates_1 = load_pullback_candidates(sqlite_engine)
    vrt_1 = candidates_1[candidates_1["ticker"] == "VRT"].iloc[0]
    assert vrt_1["watch_status"] == "watch"
    assert vrt_1["score_watchlist_priority"] == 3.0
    score_1 = vrt_1["opportunity_score"]

    # 3. Update watchlist item status via service
    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": wi.id, "watch_status": "high_priority"}]
    )
    assert errors == []
    assert updated_count == 1

    # 4. Second candidate load: watch_status is "high_priority" (5.0 watchlist points)
    candidates_2 = load_pullback_candidates(sqlite_engine)
    vrt_2 = candidates_2[candidates_2["ticker"] == "VRT"].iloc[0]
    assert vrt_2["watch_status"] == "high_priority"
    assert vrt_2["score_watchlist_priority"] == 5.0
    score_2 = vrt_2["opportunity_score"]

    # Score should have increased by exactly 2.0 points (3.0 -> 5.0)
    assert score_2 == pytest.approx(score_1 + 2.0)



