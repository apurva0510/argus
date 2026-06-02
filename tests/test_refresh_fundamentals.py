from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, JobRun, FundamentalsSnapshot
from argus.pipelines.refresh_fundamentals import refresh_fundamentals


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @property
    def info(self) -> dict:
        if self.symbol == "FAIL":
            raise RuntimeError("API fetch failed")
        if self.symbol == "EMPTY":
            return {}
        if self.symbol == "AAPL":
            return {
                "marketCap": 3000000000000.0,
                "enterpriseValue": 2980000000000.0,
                "trailingPE": 28.5,
                "forwardPE": 25.0,
                "priceToSalesTrailing12Months": 7.5,
                "enterpriseToRevenue": 7.3,
                "enterpriseToEbitda": 21.0,
                "revenueGrowth": 0.08,
                "grossMargins": 0.44,
                "operatingMargins": 0.30,
                "freeCashflow": 95000000000.0,
            }
        return {}


def test_refresh_fundamentals_success_and_idempotency(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="AAPL", name="Apple Inc", is_active=True))

    first = refresh_fundamentals()
    second = refresh_fundamentals()

    assert first["status"] == "success"
    assert first["rows_read"] == 1
    assert first["rows_written"] == 1

    assert second["status"] == "success"
    assert second["rows_read"] == 1
    assert second["rows_written"] == 1  # Updates the record

    with db_module.session_scope() as session:
        snapshots = session.query(FundamentalsSnapshot).all()
        assert len(snapshots) == 1
        assert snapshots[0].market_cap == 3000000000000.0
        assert snapshots[0].enterprise_value == 2980000000000.0
        assert snapshots[0].trailing_pe == 28.5
        assert snapshots[0].forward_pe == 25.0
        assert snapshots[0].price_to_sales == 7.5
        assert snapshots[0].ev_to_sales == 7.3
        assert snapshots[0].ev_to_ebitda == 21.0
        assert snapshots[0].revenue_growth == 0.08
        assert snapshots[0].gross_margin == 0.44
        assert snapshots[0].operating_margin == 0.30
        assert snapshots[0].free_cash_flow == 95000000000.0
        assert snapshots[0].provider == "yfinance"

        jobs = session.query(JobRun).order_by(JobRun.id.asc()).all()
        assert len(jobs) == 2
        assert jobs[0].job_name == "refresh_fundamentals"
        assert jobs[0].status == "success"
        assert jobs[1].status == "success"


def test_refresh_fundamentals_handles_failures_gracefully(sqlite_engine, monkeypatch) -> None:
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

    result = refresh_fundamentals()

    assert result["status"] == "partial_success"
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert result["failed_symbols"] == ["FAIL"]

    with db_module.session_scope() as session:
        assert session.query(FundamentalsSnapshot).count() == 1
        job = session.query(JobRun).one()
        assert job.status == "partial_success"
        assert "FAIL" in (job.error_text or "")
