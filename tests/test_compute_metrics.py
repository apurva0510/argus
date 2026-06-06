from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from argus.analytics.indicators import annualized_volatility, compute_rsi
from argus.analytics.relative_strength import relative_return
from argus.core.models import Company, DailyMetric, JobRun, PriceBar
from argus.pipelines.compute_metrics import compute_daily_metrics


def _patch_session(sqlite_engine, monkeypatch):
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    return db_module


def _seed_prices(session: Session, company_id: int, start_price: float, days: int = 260) -> None:
    start = date(2024, 1, 1)
    for offset in range(days):
        px = start_price + offset
        session.add(
            PriceBar(
                company_id=company_id,
                date=start + timedelta(days=offset),
                open=px,
                high=px + 1,
                low=px - 1,
                close=px,
                adj_close=px,
                volume=1000 + offset,
                provider="yfinance",
                interval="1d",
            )
        )


@pytest.fixture
def phase4_price_fixture() -> dict[str, object]:
    start = date(2025, 7, 1)
    days = 300
    return {
        "start": start,
        "days": days,
        "abc_prices": [100.0 + offset for offset in range(days)],
        "qqq_prices": [200.0 + (offset * 0.75) for offset in range(days)],
        "nvda_prices": [300.0 + (offset * 1.5) for offset in range(days)],
    }


def _seed_price_series(session: Session, company_id: int, start: date, prices: list[float]) -> None:
    for offset, price in enumerate(prices):
        session.add(
            PriceBar(
                company_id=company_id,
                date=start + timedelta(days=offset),
                open=price - 0.5,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                adj_close=price,
                volume=10_000 + offset,
                provider="yfinance",
                interval="1d",
            )
        )


def _series(start: date, prices: list[float]) -> pd.Series:
    index = pd.to_datetime([start + timedelta(days=offset) for offset in range(len(prices))])
    return pd.Series(prices, index=index, dtype="float64")


def test_compute_metrics_is_idempotent_and_stores_expected_values(
    sqlite_engine, monkeypatch
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    with db_module.session_scope() as session:
        abc = Company(symbol="ABC", name="ABC", is_active=True)
        qqq = Company(symbol="QQQ", name="QQQ", is_active=True)
        nvda = Company(symbol="NVDA", name="NVDA", is_active=True)
        session.add_all([abc, qqq, nvda])
        session.flush()
        _seed_prices(session, abc.id, 100.0)
        _seed_prices(session, qqq.id, 200.0)
        _seed_prices(session, nvda.id, 300.0)

    first = compute_daily_metrics()
    second = compute_daily_metrics()

    assert first["status"] == "success"
    assert second["status"] == "success"

    with db_module.session_scope() as session:
        metric_rows = session.query(func.count(DailyMetric.id)).scalar()
        duplicate_keys = (
            session.query(DailyMetric.company_id, DailyMetric.date, func.count(DailyMetric.id))
            .group_by(DailyMetric.company_id, DailyMetric.date)
            .having(func.count(DailyMetric.id) > 1)
            .count()
        )
        jobs = session.query(JobRun).order_by(JobRun.id.asc()).all()

        assert metric_rows == 260 * 3
        assert duplicate_keys == 0
        assert len(jobs) == 2
        assert jobs[0].status == "success"
        assert jobs[1].status == "success"

        abc_id = session.query(Company.id).filter(Company.symbol == "ABC").scalar()
        latest = (
            session.query(DailyMetric)
            .filter(DailyMetric.company_id == abc_id)
            .order_by(DailyMetric.date.desc())
            .first()
        )
        assert latest is not None
        assert latest.return_1d == pytest.approx((359.0 / 358.0) - 1.0)
        assert latest.return_1w == pytest.approx((359.0 / 354.0) - 1.0)
        assert latest.return_1m == pytest.approx((359.0 / 338.0) - 1.0)
        assert latest.ma_50 == pytest.approx((310.0 + 359.0) / 2.0)
        assert latest.ma_200 == pytest.approx((160.0 + 359.0) / 2.0)
        assert latest.high_52w == pytest.approx(359.0)
        assert latest.low_52w == pytest.approx(108.0)
        assert latest.drawdown_52w == pytest.approx(0.0)
        assert latest.distance_from_50dma == pytest.approx((359.0 / 334.5) - 1.0)
        assert latest.relative_return_vs_qqq_1m == pytest.approx(
            ((359.0 / 338.0) - 1.0) - ((459.0 / 438.0) - 1.0)
        )
        assert latest.relative_return_vs_nvda_1m == pytest.approx(
            ((359.0 / 338.0) - 1.0) - ((559.0 / 538.0) - 1.0)
        )


def test_compute_metrics_populates_phase4_windowed_metrics(
    sqlite_engine, monkeypatch, phase4_price_fixture
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    start = phase4_price_fixture["start"]
    abc_prices = phase4_price_fixture["abc_prices"]
    qqq_prices = phase4_price_fixture["qqq_prices"]
    nvda_prices = phase4_price_fixture["nvda_prices"]

    with db_module.session_scope() as session:
        abc = Company(symbol="ABC", name="ABC", is_active=True)
        qqq = Company(symbol="QQQ", name="QQQ", is_active=True)
        nvda = Company(symbol="NVDA", name="NVDA", is_active=True)
        session.add_all([abc, qqq, nvda])
        session.flush()
        _seed_price_series(session, abc.id, start, abc_prices)
        _seed_price_series(session, qqq.id, start, qqq_prices)
        _seed_price_series(session, nvda.id, start, nvda_prices)

    result = compute_daily_metrics()
    assert result["status"] == "success"

    abc_series = _series(start, abc_prices)
    qqq_series = _series(start, qqq_prices)
    nvda_series = _series(start, nvda_prices)
    latest_price = abc_prices[-1]
    latest_date = start + timedelta(days=len(abc_prices) - 1)
    prior_year_close = abc_series[abc_series.index.year < latest_date.year].iloc[-1]
    ma_50 = sum(abc_prices[-50:]) / 50
    ma_200 = sum(abc_prices[-200:]) / 200
    high_52w = max(abc_prices[-252:])
    low_52w = min(abc_prices[-252:])

    with db_module.session_scope() as session:
        abc_id = session.query(Company.id).filter(Company.symbol == "ABC").scalar()
        latest = (
            session.query(DailyMetric)
            .filter(DailyMetric.company_id == abc_id)
            .order_by(DailyMetric.date.desc())
            .first()
        )

        assert latest is not None
        assert latest.date == latest_date
        assert latest.return_1d == pytest.approx((latest_price / abc_prices[-2]) - 1.0)
        assert latest.return_1w == pytest.approx((latest_price / abc_prices[-6]) - 1.0)
        assert latest.return_1m == pytest.approx((latest_price / abc_prices[-22]) - 1.0)
        assert latest.return_3m == pytest.approx((latest_price / abc_prices[-64]) - 1.0)
        assert latest.return_6m == pytest.approx((latest_price / abc_prices[-127]) - 1.0)
        assert latest.return_ytd == pytest.approx((latest_price / prior_year_close) - 1.0)
        assert latest.ma_50 == pytest.approx(ma_50)
        assert latest.ma_200 == pytest.approx(ma_200)
        assert latest.rsi_14 == pytest.approx(compute_rsi(abc_series, 14).iloc[-1])
        assert latest.high_52w == pytest.approx(high_52w)
        assert latest.low_52w == pytest.approx(low_52w)
        assert latest.drawdown_52w == pytest.approx((latest_price / high_52w) - 1.0)
        assert latest.distance_from_50dma == pytest.approx((latest_price / ma_50) - 1.0)
        assert latest.distance_from_200dma == pytest.approx((latest_price / ma_200) - 1.0)
        assert latest.volatility_20d == pytest.approx(
            annualized_volatility(abc_series, 20).iloc[-1]
        )
        assert latest.relative_return_vs_qqq_1m == pytest.approx(
            relative_return(abc_series, qqq_series, 21).iloc[-1]
        )
        assert latest.relative_return_vs_qqq_3m == pytest.approx(
            relative_return(abc_series, qqq_series, 63).iloc[-1]
        )
        assert latest.relative_return_vs_nvda_1m == pytest.approx(
            relative_return(abc_series, nvda_series, 21).iloc[-1]
        )
        assert latest.relative_return_vs_nvda_3m == pytest.approx(
            relative_return(abc_series, nvda_series, 63).iloc[-1]
        )


def test_compute_metrics_upsert_updates_existing_daily_metric(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    with db_module.session_scope() as session:
        abc = Company(symbol="ABC", name="ABC", is_active=True)
        session.add(abc)
        session.flush()
        _seed_prices(session, abc.id, 100.0, days=80)

    first = compute_daily_metrics()
    assert first["status"] == "success"

    with db_module.session_scope() as session:
        abc_id = session.query(Company.id).filter(Company.symbol == "ABC").scalar()
        latest_bar = (
            session.query(PriceBar)
            .filter(PriceBar.company_id == abc_id)
            .order_by(PriceBar.date.desc())
            .first()
        )
        assert latest_bar is not None
        latest_bar.adj_close = 250.0
        latest_bar.close = 250.0

    second = compute_daily_metrics()
    assert second["status"] == "success"

    with db_module.session_scope() as session:
        abc_id = session.query(Company.id).filter(Company.symbol == "ABC").scalar()
        assert session.query(DailyMetric).filter(DailyMetric.company_id == abc_id).count() == 80
        duplicate_keys = (
            session.query(DailyMetric.company_id, DailyMetric.date, func.count(DailyMetric.id))
            .group_by(DailyMetric.company_id, DailyMetric.date)
            .having(func.count(DailyMetric.id) > 1)
            .count()
        )
        latest_metric = (
            session.query(DailyMetric)
            .filter(DailyMetric.company_id == abc_id)
            .order_by(DailyMetric.date.desc())
            .first()
        )
        assert duplicate_keys == 0
        assert latest_metric is not None
        assert latest_metric.return_1d == pytest.approx((250.0 / 178.0) - 1.0)
        assert session.query(JobRun).filter(JobRun.job_name == "compute_daily_metrics").count() == 2


def test_compute_metrics_handles_missing_benchmarks(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    with db_module.session_scope() as session:
        abc = Company(symbol="ABC", name="ABC", is_active=True)
        session.add(abc)
        session.flush()
        _seed_prices(session, abc.id, 100.0, days=80)

    result = compute_daily_metrics()
    assert result["status"] == "success"

    with db_module.session_scope() as session:
        abc_id = session.query(Company.id).filter(Company.symbol == "ABC").scalar()
        row = (
            session.query(DailyMetric)
            .filter(DailyMetric.company_id == abc_id)
            .order_by(DailyMetric.date.desc())
            .first()
        )
        assert row is not None
        assert row.relative_return_vs_qqq_1m is None
        assert row.relative_return_vs_qqq_3m is None
        assert row.relative_return_vs_nvda_1m is None
        assert row.relative_return_vs_nvda_3m is None


def test_compute_metrics_stores_nulls_for_insufficient_history(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    with db_module.session_scope() as session:
        abc = Company(symbol="ABC", name="ABC", is_active=True)
        session.add(abc)
        session.flush()
        _seed_prices(session, abc.id, 100.0, days=10)

    result = compute_daily_metrics()
    assert result["status"] == "success"

    with db_module.session_scope() as session:
        row = session.query(DailyMetric).order_by(DailyMetric.date.desc()).first()
        assert row is not None
        assert row.ma_50 is None
        assert row.ma_200 is None
        assert row.rsi_14 is None
        assert row.high_52w is None
        assert row.low_52w is None
        assert row.drawdown_52w is None
        assert row.distance_from_50dma is None
        assert row.distance_from_200dma is None
        assert row.return_1m is None
        assert row.return_3m is None
        assert row.return_6m is None
        assert row.volatility_20d is None
        assert row.relative_return_vs_qqq_1m is None


def test_compute_metrics_persists_job_run_on_unexpected_failure(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    def fail_unique_key_check(_session) -> bool:
        raise RuntimeError("schema inspection failed")

    monkeypatch.setattr(
        "argus.pipelines.compute_metrics._supports_daily_metrics_unique_key",
        fail_unique_key_check,
    )

    with db_module.session_scope() as session:
        abc = Company(symbol="ABC", name="ABC", is_active=True)
        session.add(abc)
        session.flush()
        _seed_prices(session, abc.id, 100.0, days=10)

    result = compute_daily_metrics()

    assert result["status"] == "failed"
    assert result["error_text"] == "schema inspection failed"

    with db_module.session_scope() as session:
        jobs = session.query(JobRun).all()
        assert len(jobs) == 1
        assert jobs[0].status == "failed"
        assert jobs[0].error_text == "schema inspection failed"
        assert session.query(DailyMetric).count() == 0


def test_compute_metrics_with_mismatched_benchmark_dates(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)

    with db_module.session_scope() as session:
        abc = Company(symbol="ABC", name="ABC", is_active=True)
        qqq = Company(symbol="QQQ", name="QQQ", is_active=True)
        session.add_all([abc, qqq])
        session.flush()

        # Seed mismatched price bars
        # ABC has bars on day 0, 1, 2, 4
        # QQQ has bars on day 0, 1, 3, 4
        start = date(2026, 5, 1)
        for offset in [0, 1, 2, 4]:
            session.add(
                PriceBar(
                    company_id=abc.id,
                    date=start + timedelta(days=offset),
                    close=100.0 + offset,
                    adj_close=100.0 + offset,
                    provider="yfinance",
                    interval="1d",
                )
            )
        for offset in [0, 1, 3, 4]:
            session.add(
                PriceBar(
                    company_id=qqq.id,
                    date=start + timedelta(days=offset),
                    close=200.0 + offset,
                    adj_close=200.0 + offset,
                    provider="yfinance",
                    interval="1d",
                )
            )

    result = compute_daily_metrics()
    # Should run successfully despite mismatched dates
    assert result["status"] == "success"

    with db_module.session_scope() as session:
        # Check that metrics are stored for all 4 dates for ABC
        abc_id = session.query(Company.id).filter(Company.symbol == "ABC").scalar()
        abc_metrics = (
            session.query(DailyMetric)
            .filter(DailyMetric.company_id == abc_id)
            .order_by(DailyMetric.date.asc())
            .all()
        )
        assert len(abc_metrics) == 4
        assert [m.date for m in abc_metrics] == [
            start,
            start + timedelta(days=1),
            start + timedelta(days=2),
            start + timedelta(days=4),
        ]
