from datetime import date

import pandas as pd
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, JobRun, PriceBar
from argus.pipelines.refresh_prices import refresh_prices


def test_refresh_prices_is_idempotent(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    def fake_fetch(_symbol: str, period: str = "2y") -> pd.DataFrame:
        assert period == "2y"
        return pd.DataFrame(
            [
                {
                    "date": date(2025, 1, 2),
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "adj_close": 100.5,
                    "volume": 1000.0,
                },
                {
                    "date": date(2025, 1, 3),
                    "open": 101.0,
                    "high": 103.0,
                    "low": 100.0,
                    "close": 102.0,
                    "adj_close": 101.2,
                    "volume": 1200.0,
                },
            ]
        )

    monkeypatch.setattr("argus.pipelines.refresh_prices.fetch_daily_ohlcv", fake_fetch)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", is_active=True))

    first = refresh_prices(period="2y")
    second = refresh_prices(period="2y")

    with db_module.session_scope() as session:
        bars = session.query(PriceBar).all()
        assert len(bars) == 2
        assert all(bar.provider == "yfinance" for bar in bars)
        assert all(bar.interval == "1d" for bar in bars)

        jobs = session.query(JobRun).order_by(JobRun.id.asc()).all()
        assert len(jobs) == 2
        assert jobs[0].status == "success"
        assert jobs[1].status == "success"

    assert first["rows_written"] == 2
    assert second["rows_written"] == 2


def test_refresh_prices_updates_existing_rows_without_duplicates(
    sqlite_engine, monkeypatch
) -> None:
    from argus.core import db as db_module

    closes_by_run = iter([101.0, 105.0])

    def fake_fetch(_symbol: str, period: str = "2y") -> pd.DataFrame:
        close = next(closes_by_run)
        return pd.DataFrame(
            [
                {
                    "date": date(2025, 1, 2),
                    "open": close - 1.0,
                    "high": close + 1.0,
                    "low": close - 2.0,
                    "close": close,
                    "adj_close": close - 0.5,
                    "volume": close * 10,
                }
            ]
        )

    monkeypatch.setattr("argus.pipelines.refresh_prices.fetch_daily_ohlcv", fake_fetch)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", is_active=True))

    first = refresh_prices(period="2y")
    second = refresh_prices(period="2y")

    assert first["status"] == "success"
    assert second["status"] == "success"

    with db_module.session_scope() as session:
        bars = session.query(PriceBar).all()
        assert len(bars) == 1
        assert bars[0].close == 105.0
        assert bars[0].adj_close == 104.5
        assert bars[0].provider == "yfinance"
        assert bars[0].interval == "1d"


def test_refresh_prices_deduplicates_duplicate_dates_from_provider_payload(
    sqlite_engine, monkeypatch
) -> None:
    from argus.core import db as db_module

    def fake_fetch(_symbol: str, period: str = "2y") -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": date(2025, 1, 2),
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "adj_close": 100.5,
                    "volume": 1000.0,
                },
                {
                    "date": date(2025, 1, 2),
                    "open": 101.0,
                    "high": 103.0,
                    "low": 100.0,
                    "close": 102.0,
                    "adj_close": 101.5,
                    "volume": 1200.0,
                },
            ]
        )

    monkeypatch.setattr("argus.pipelines.refresh_prices.fetch_daily_ohlcv", fake_fetch)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="DUP", name="Duplicate Payload Co", is_active=True))

    result = refresh_prices(period="2y")

    assert result["status"] == "success"
    assert result["rows_read"] == 2
    assert result["rows_written"] == 2

    with db_module.session_scope() as session:
        bars = session.query(PriceBar).all()
        assert len(bars) == 1
        assert bars[0].close == 102.0
        assert bars[0].volume == 1200.0


def test_refresh_prices_records_partial_success(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    def fake_fetch(symbol: str, period: str = "2y") -> pd.DataFrame:
        assert period == "1y"
        if symbol == "BAD":
            raise RuntimeError("boom")
        return pd.DataFrame(
            [
                {
                    "date": date(2025, 2, 1),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "adj_close": 10.5,
                    "volume": 100.0,
                }
            ]
        )

    monkeypatch.setattr("argus.pipelines.refresh_prices.fetch_daily_ohlcv", fake_fetch)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="GOOD", name="Good Co", is_active=True))
        session.add(Company(symbol="BAD", name="Bad Co", is_active=True))

    result = refresh_prices(period="1y")
    assert result["status"] == "partial_success"
    assert result["failed_symbols"] == ["BAD"]

    with db_module.session_scope() as session:
        assert session.query(PriceBar).count() == 1
        job = session.query(JobRun).order_by(JobRun.id.desc()).one()
        assert job.status == "partial_success"
        assert "BAD" in (job.error_text or "")


def test_refresh_prices_treats_empty_yfinance_response_as_failed_ticker(
    sqlite_engine, monkeypatch
) -> None:
    from argus.core import db as db_module

    def fake_fetch(_symbol: str, period: str = "2y") -> pd.DataFrame:
        return pd.DataFrame()

    monkeypatch.setattr("argus.pipelines.refresh_prices.fetch_daily_ohlcv", fake_fetch)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="EMPTY", name="Empty Co", is_active=True))

    result = refresh_prices(period="2y")

    assert result == {
        "status": "partial_success",
        "rows_read": 0,
        "rows_written": 0,
        "failed_symbols": ["EMPTY"],
        "error_text": None,
    }

    with db_module.session_scope() as session:
        assert session.query(PriceBar).count() == 0
        job = session.query(JobRun).one()
        assert job.status == "partial_success"
        assert job.rows_read == 0
        assert job.rows_written == 0
        assert "EMPTY" in (job.error_text or "")


def test_refresh_prices_stores_benchmark_tickers(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    def fake_fetch(symbol: str, period: str = "2y") -> pd.DataFrame:
        assert symbol == "QQQ"
        return pd.DataFrame(
            [
                {
                    "date": date(2025, 3, 1),
                    "open": 500.0,
                    "high": 505.0,
                    "low": 499.0,
                    "close": 504.0,
                    "adj_close": 503.5,
                    "volume": 10000.0,
                }
            ]
        )

    monkeypatch.setattr("argus.pipelines.refresh_prices.fetch_daily_ohlcv", fake_fetch)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="QQQ", name="Invesco QQQ Trust", is_active=True, is_benchmark=True))

    result = refresh_prices(period="2y")

    assert result["status"] == "success"

    with db_module.session_scope() as session:
        bar = session.query(PriceBar).one()
        assert bar.provider == "yfinance"
        assert bar.interval == "1d"
        assert bar.adj_close == 503.5


def test_refresh_prices_persists_job_run_on_unexpected_failure(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    def fake_fetch(_symbol: str, period: str = "2y") -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": date(2025, 3, 1),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "adj_close": 10.5,
                    "volume": 100.0,
                }
            ]
        )

    def fail_upsert(*_args, **_kwargs) -> int:
        raise RuntimeError("upsert failed")

    monkeypatch.setattr("argus.pipelines.refresh_prices.fetch_daily_ohlcv", fake_fetch)
    monkeypatch.setattr("argus.pipelines.refresh_prices._upsert_price_bar_rows", fail_upsert)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="FAIL", name="Failure Co", is_active=True))

    result = refresh_prices(period="2y")

    assert result["status"] == "failed"
    assert result["error_text"] == "upsert failed"

    with db_module.session_scope() as session:
        jobs = session.query(JobRun).all()
        assert len(jobs) == 1
        assert jobs[0].status == "failed"
        assert jobs[0].rows_read == 1
        assert jobs[0].rows_written == 0
        assert jobs[0].error_text == "upsert failed"
        assert session.query(PriceBar).count() == 0
