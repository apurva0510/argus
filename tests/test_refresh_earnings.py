from __future__ import annotations

from datetime import date
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, JobRun, EarningsEvent
from argus.pipelines.refresh_earnings import refresh_earnings


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @property
    def calendar(self) -> dict:
        if self.symbol == "FAIL":
            raise RuntimeError("API fetch failed")
        if self.symbol == "EMPTY":
            return {}
        if self.symbol == "AAPL":
            return {
                "Dividend Date": date(2026, 5, 13),
                "Ex-Dividend Date": date(2026, 5, 10),
                "Earnings Date": [date(2026, 7, 30)],
                "Earnings Average": 1.89,
                "Revenue Average": 109000000000.0,
            }
        return {}


def test_refresh_earnings_success_and_idempotency(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="AAPL", name="Apple Inc", is_active=True))

    first = refresh_earnings()
    second = refresh_earnings()

    assert first["status"] == "success"
    assert first["rows_read"] == 1
    assert first["rows_written"] == 1

    assert second["status"] == "success"
    assert second["rows_read"] == 1
    # Idempotence check: still written successfully but no duplicates should exist in DB
    assert second["rows_written"] == 1

    with db_module.session_scope() as session:
        events = session.query(EarningsEvent).all()
        assert len(events) == 1
        assert events[0].event_date == date(2026, 7, 30)
        assert events[0].eps_estimate == 1.89
        assert events[0].revenue_estimate == 109000000000.0
        assert events[0].source == "yfinance"

        jobs = session.query(JobRun).order_by(JobRun.id.asc()).all()
        assert len(jobs) == 2
        assert jobs[0].job_name == "refresh_earnings"
        assert jobs[0].status == "success"
        assert jobs[1].status == "success"


def test_refresh_earnings_handles_partial_failures_and_empty_responses(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="AAPL", name="Apple Inc", is_active=True))
        session.add(Company(symbol="FAIL", name="Fail Co", is_active=True))
        session.add(Company(symbol="EMPTY", name="Empty Co", is_active=True))

    result = refresh_earnings()

    assert result["status"] == "partial_success"
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert result["failed_symbols"] == ["FAIL"]

    with db_module.session_scope() as session:
        assert session.query(EarningsEvent).count() == 1
        job = session.query(JobRun).one()
        assert job.status == "partial_success"
        assert "FAIL" in (job.error_text or "")
