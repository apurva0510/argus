import pytest
from datetime import date, timedelta
from sqlalchemy.orm import Session

from argus.core.models import Company, PriceBar, DailyMetric, ScoreBacktestEvent, ScoreBacktestSummary, Watchlist, WatchlistItem
from argus.pipelines.backtest_scores import backtest_opportunity_scores


def test_backtest_opportunity_scores_calculation_and_spacing(sqlite_engine, db_session: Session) -> None:
    # 1. Seed active company
    comp = Company(symbol="AAPL", name="Apple Inc.", sector="Technology", is_active=True)
    db_session.add(comp)
    db_session.flush()

    # Seed watchlist item
    wl = Watchlist(name="Test Watchlist", is_system=True)
    db_session.add(wl)
    db_session.flush()
    wli = WatchlistItem(watchlist_id=wl.id, company_id=comp.id, watch_status="watch")
    db_session.add(wli)

    # 2. Seed price bars for 70 trading days starting 2026-01-01
    start_date = date(2026, 1, 1)
    prices = []
    # Let's create a price pattern: start at 100, goes down to 90 (drawdown), then rises to 120
    for i in range(75):
        d = start_date + timedelta(days=i)
        # Pattern: first 10 days it drops by 1 per day, then rises by 0.5 per day
        price = 100.0 - i if i < 10 else 90.0 + (i - 10) * 0.5
        bar = PriceBar(
            company_id=comp.id,
            date=d,
            bar_time=d,
            open=price,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            adj_close=price,
            provider="yfinance",
            interval="1d"
        )
        db_session.add(bar)
        prices.append((d, price))
    
    db_session.commit()

    # 3. Seed DailyMetric on 2026-01-05 and 2026-01-06 (separated by 1 trading day)
    metric1 = DailyMetric(
        company_id=comp.id,
        date=date(2026, 1, 5),
        drawdown_52w=-0.15,
        rsi_14=35.0,
        distance_from_200dma=0.05,
        relative_return_vs_qqq_3m=0.02,
        return_1w=-0.03
    )
    metric2 = DailyMetric(
        company_id=comp.id,
        date=date(2026, 1, 6),
        drawdown_52w=-0.16,
        rsi_14=34.0,
        distance_from_200dma=0.04,
        relative_return_vs_qqq_3m=0.01,
        return_1w=-0.04
    )
    db_session.add_all([metric1, metric2])
    db_session.commit()

    # 4. Run backtest from 2026-01-01
    res = backtest_opportunity_scores(start_date=date(2026, 1, 1))

    # Assertions
    # We should have created 1 backtest event because the second event on 2026-01-06 is skipped
    # due to the 5 trading days spacing rule.
    assert res["events_created"] == 1

    events = db_session.query(ScoreBacktestEvent).filter(ScoreBacktestEvent.company_id == comp.id).all()
    assert len(events) == 1
    evt = events[0]
    assert evt.date == date(2026, 1, 5)
    
    # Check that returns are calculated correctly
    # Apple price list date mapping:
    # 2026-01-05 is index 4 (i = 4, price = 96.0)
    # P5 is 5 trading days later -> index 9 (i = 9, price = 91.0)
    # Expected 5D return: (91.0 - 96.0) / 96.0 = -5 / 96 = -0.052083
    assert evt.ret_5d == pytest.approx((91.0 - 96.0) / 96.0)

    # P20 is index 24 (i = 24, price = 90.0 + 14 * 0.5 = 97.0)
    # Expected 20D return: (97.0 - 96.0) / 96.0 = 1 / 96 = 0.010416
    assert evt.ret_20d == pytest.approx((97.0 - 96.0) / 96.0)

    # Peak price from index 4 to 24: starts at P4 = 96.0. drops to 90.0 on index 10, then rises.
    # So peak remains 96.0 until index 22 where price is 96.0, then becomes 96.5 at index 23, 97.0 at index 24.
    # Trough is index 10 (price = 90.0). Max drawdown = (90.0 - 96.0) / 96.0 = -6 / 96 = -0.0625.
    assert evt.drawdown_20d == pytest.approx(-6.0 / 96.0)

    # 5. Check summaries were aggregated
    summaries = db_session.query(ScoreBacktestSummary).all()
    assert len(summaries) > 0
    for s in summaries:
        assert s.event_count == 1
        assert s.avg_return in [evt.ret_5d, evt.ret_20d, evt.ret_60d]


def test_backtest_includes_inactive_companies_with_historical_metrics(sqlite_engine, db_session: Session) -> None:
    comp = Company(symbol="OLD", name="Old Co", sector="Technology", is_active=False)
    db_session.add(comp)
    db_session.flush()

    start_date = date(2026, 1, 1)
    for i in range(70):
        d = start_date + timedelta(days=i)
        price = 100.0 + i
        db_session.add(
            PriceBar(
                company_id=comp.id,
                date=d,
                bar_time=d,
                close=price,
                adj_close=price,
                provider="yfinance",
                interval="1d",
            )
        )
    db_session.add(
        DailyMetric(
            company_id=comp.id,
            date=date(2026, 1, 5),
            drawdown_52w=-0.15,
            rsi_14=35.0,
            distance_from_200dma=0.05,
            relative_return_vs_qqq_3m=0.02,
            return_1w=-0.03,
        )
    )
    db_session.commit()

    result = backtest_opportunity_scores(start_date=date(2026, 1, 1))

    assert result["events_created"] == 1
    event = db_session.query(ScoreBacktestEvent).filter_by(company_id=comp.id).one()
    assert event.date == date(2026, 1, 5)


def test_backtest_earlier_backfill_uses_prior_spacing_not_global_latest(sqlite_engine, db_session: Session) -> None:
    comp = Company(symbol="BT", name="Backtest Co", sector="Technology", is_active=True)
    db_session.add(comp)
    db_session.flush()

    start_date = date(2026, 1, 1)
    for i in range(90):
        d = start_date + timedelta(days=i)
        price = 100.0 + i
        db_session.add(
            PriceBar(
                company_id=comp.id,
                date=d,
                bar_time=d,
                close=price,
                adj_close=price,
                provider="yfinance",
                interval="1d",
            )
        )
    db_session.add(
        ScoreBacktestEvent(
            company_id=comp.id,
            date=date(2026, 2, 1),
            score=50.0,
        )
    )
    db_session.add(
        DailyMetric(
            company_id=comp.id,
            date=date(2026, 1, 5),
            drawdown_52w=-0.15,
            rsi_14=35.0,
            distance_from_200dma=0.05,
            relative_return_vs_qqq_3m=0.02,
            return_1w=-0.03,
        )
    )
    db_session.commit()

    result = backtest_opportunity_scores(start_date=date(2026, 1, 1))

    assert result["events_created"] == 1
    assert db_session.query(ScoreBacktestEvent).filter_by(company_id=comp.id).count() == 2
