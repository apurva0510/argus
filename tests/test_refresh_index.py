from __future__ import annotations

from datetime import date, timedelta
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

    import pytest

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
