from __future__ import annotations

from datetime import date, datetime, timedelta
import pandas as pd
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, PriceBar, JobRun, IndexValue
from argus.pipelines.refresh_index import refresh_index
from argus.analytics.index_builder import calculate_equal_weight_index


def _seed_prices(session: Session, company_id: int, start_date: date, prices: list[float]) -> None:
    for offset, price in enumerate(prices):
        session.add(
            PriceBar(
                company_id=company_id,
                date=start_date + timedelta(days=offset),
                open=price,
                high=price,
                low=price,
                close=price,
                adj_close=price,
                volume=1000,
                provider="yfinance",
                interval="1d",
            )
        )


def _seed_intraday_prices(
    session: Session,
    company_id: int,
    start_time: datetime,
    prices: list[float],
) -> None:
    for offset, price in enumerate(prices):
        bar_time = start_time + timedelta(minutes=15 * offset)
        session.add(
            PriceBar(
                company_id=company_id,
                date=bar_time.date(),
                bar_time=bar_time,
                close=price,
                adj_close=price,
                provider="yfinance",
                interval="15m",
            )
        )


def test_refresh_index_success_and_speedup(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    # Mock SessionLocal to use the test engine
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        # Seed constituents
        c1 = Company(symbol="AAPL", name="Apple Inc", is_active=True, is_benchmark=False)
        c2 = Company(symbol="MSFT", name="Microsoft Corp", is_active=True, is_benchmark=False)
        session.add_all([c1, c2])
        session.flush()

        start_date = date(2026, 5, 1)
        _seed_prices(session, c1.id, start_date, [100.0, 102.0, 104.04])
        _seed_prices(session, c2.id, start_date, [200.0, 204.0, 208.08])

    # Run the index refresh pipeline
    result = refresh_index()
    assert result["status"] == "success"
    assert result["rows_written"] == 3

    # Check database persistence
    with db_module.session_scope() as session:
        stored_values = session.query(IndexValue).order_by(IndexValue.date.asc()).all()
        assert len(stored_values) == 3
        assert stored_values[0].date == date(2026, 5, 1)
        assert stored_values[0].index_value == pytest.approx(100.0)
        assert stored_values[1].index_value == pytest.approx(102.0)
        assert stored_values[2].index_value == pytest.approx(104.04)

        # Verify JobRun entry
        job = session.query(JobRun).filter(JobRun.job_name == "refresh_index").one()
        assert job.status == "success"
        assert job.rows_written == 3

    # Test Idempotency (running refresh_index again should replace values cleanly)
    result_second = refresh_index()
    assert result_second["status"] == "success"
    assert result_second["rows_written"] == 3

    with db_module.session_scope() as session:
        assert session.query(IndexValue).count() == 3
        assert session.query(JobRun).filter(JobRun.job_name == "refresh_index").count() == 2

    # Test the calculation speed-up path: calling calculate_equal_weight_index
    # should select directly from index_values without querying price_bars
    with db_module.session_scope() as session:
        # Delete price_bars to confirm calculate_equal_weight_index loads from table
        session.execute(delete(PriceBar))
        session.commit()

        # Ensure it works when symbols is None (pulls from precalculated table)
        df_index = calculate_equal_weight_index(session)
        assert not df_index.empty
        assert len(df_index) == 3
        assert df_index.iloc[0]["index_value"] == pytest.approx(100.0)
        assert df_index.iloc[2]["index_value"] == pytest.approx(104.04)


def test_refresh_index_recomputes_when_precalculated_values_are_stale(
    sqlite_engine,
    monkeypatch,
) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        company = Company(symbol="ETN", name="Eaton", is_active=True, is_benchmark=False)
        session.add(company)
        session.flush()

        start_date = date(2026, 6, 1)
        _seed_prices(session, company.id, start_date, [100.0, 101.0])
        session.add_all(
            [
                IndexValue(date=start_date, index_value=100.0),
                IndexValue(date=start_date + timedelta(days=1), index_value=101.0),
            ]
        )

    with db_module.session_scope() as session:
        company = session.query(Company).filter(Company.symbol == "ETN").one()
        _seed_prices(session, company.id, date(2026, 6, 3), [102.01])

    result = refresh_index()

    assert result["status"] == "success"
    assert result["rows_written"] == 3

    with db_module.session_scope() as session:
        stored_values = session.query(IndexValue).order_by(IndexValue.date.asc()).all()
        stored_dates = [row.date for row in stored_values]
        latest_index_value = stored_values[-1].index_value

    assert stored_dates == [
        date(2026, 6, 1),
        date(2026, 6, 2),
        date(2026, 6, 3),
    ]
    assert latest_index_value == pytest.approx(102.01)


def test_calculate_equal_weight_index_uses_intraday_bars(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    start_time = datetime(2026, 6, 4, 14, 0)
    with db_module.session_scope() as session:
        c1 = Company(symbol="AAA", name="AAA", is_active=True)
        c2 = Company(symbol="BBB", name="BBB", is_active=True)
        session.add_all([c1, c2])
        session.flush()
        _seed_intraday_prices(session, c1.id, start_time, [100.0, 101.0, 103.02])
        _seed_intraday_prices(session, c2.id, start_time, [200.0, 202.0, 206.04])

    with db_module.session_scope() as session:
        df = calculate_equal_weight_index(
            session,
            symbols=["AAA", "BBB"],
            interval="15m",
        )

    assert df["date"].tolist() == [
        start_time,
        start_time + timedelta(minutes=15),
        start_time + timedelta(minutes=30),
    ]
    assert df["index_value"].tolist() == pytest.approx([100.0, 101.0, 103.02])


def test_calculate_intraday_index_filters_to_market_hours(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    market_time = datetime(2026, 6, 4, 14, 0)  # 10:00 ET during EDT
    points = [
        (datetime(2026, 6, 4, 12, 0), 90.0, 180.0),  # premarket
        (market_time, 100.0, 200.0),
        (market_time + timedelta(minutes=15), 101.0, 202.0),
        (datetime(2026, 6, 4, 20, 15), 150.0, 300.0),  # after-hours
    ]
    with db_module.session_scope() as session:
        c1 = Company(symbol="AAA", name="AAA", is_active=True)
        c2 = Company(symbol="BBB", name="BBB", is_active=True)
        session.add_all([c1, c2])
        session.flush()
        for bar_time, c1_price, c2_price in points:
            for company_id, price in ((c1.id, c1_price), (c2.id, c2_price)):
                session.add(
                    PriceBar(
                        company_id=company_id,
                        date=bar_time.date(),
                        bar_time=bar_time,
                        close=price,
                        adj_close=price,
                        provider="yfinance",
                        interval="15m",
                    )
                )

    with db_module.session_scope() as session:
        df = calculate_equal_weight_index(
            session,
            symbols=["AAA", "BBB"],
            interval="15m",
        )

    assert df["date"].tolist() == [market_time, market_time + timedelta(minutes=15)]
    assert df["index_value"].tolist() == pytest.approx([100.0, 101.0])


def test_calculate_intraday_index_forward_fills_sparse_recent_bars(
    sqlite_engine,
    monkeypatch,
) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    start_time = datetime(2026, 6, 4, 14, 0)
    with db_module.session_scope() as session:
        c1 = Company(symbol="AAA", name="AAA", is_active=True)
        c2 = Company(symbol="BBB", name="BBB", is_active=True)
        session.add_all([c1, c2])
        session.flush()
        _seed_intraday_prices(session, c1.id, start_time, [100.0, 105.0])
        _seed_intraday_prices(session, c2.id, start_time, [200.0])

    with db_module.session_scope() as session:
        df = calculate_equal_weight_index(
            session,
            symbols=["AAA", "BBB"],
            interval="15m",
        )

    assert df["date"].tolist() == [start_time, start_time + timedelta(minutes=15)]
    assert df["index_value"].tolist() == pytest.approx([100.0, 102.5])


def test_calculate_intraday_relative_performance_uses_intraday_benchmarks(
    sqlite_engine,
    monkeypatch,
) -> None:
    from argus.core import db as db_module
    from argus.analytics.index_builder import calculate_relative_performance

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    start_time = datetime(2026, 6, 4, 14, 0)
    with db_module.session_scope() as session:
        qqq = Company(symbol="QQQ", name="QQQ", is_active=True)
        nvda = Company(symbol="NVDA", name="NVIDIA", is_active=True)
        session.add_all([qqq, nvda])
        session.flush()
        _seed_intraday_prices(session, qqq.id, start_time, [100.0, 102.0])
        _seed_intraday_prices(session, nvda.id, start_time, [200.0, 198.0])

    index_df = pd.DataFrame(
        {
            "date": [start_time, start_time + timedelta(minutes=15)],
            "index_value": [100.0, 101.0],
        }
    )
    with db_module.session_scope() as session:
        rel_df = calculate_relative_performance(
            session,
            index_df,
            start_time,
            interval="15m",
        )

    assert rel_df["index_ret"].tolist() == pytest.approx([0.0, 1.0])
    assert rel_df["qqq_ret"].tolist() == pytest.approx([0.0, 2.0])
    assert rel_df["nvda_ret"].tolist() == pytest.approx([0.0, -1.0])
