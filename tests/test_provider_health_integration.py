import pytest
import pandas as pd
from sqlalchemy.orm import Session

from argus.core.models import Company, ProviderHealth
from argus.pipelines.refresh_prices import refresh_prices
from argus.pipelines.refresh_filings import refresh_filings
from argus.pipelines.refresh_news import refresh_news
from argus.pipelines.refresh_macro import refresh_macro


def test_refresh_prices_provider_health_failure(sqlite_engine, monkeypatch) -> None:
    # Seed active company
    with Session(sqlite_engine) as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", is_active=True))
        session.commit()

    class MockFailingProvider:
        @property
        def name(self) -> str:
            return "yfinance"
        def is_available(self) -> bool:
            return True
        def fetch_daily_ohlcv(self, symbol: str, period: str = "2y") -> pd.DataFrame:
            raise ValueError("yfinance connection timed out")

    monkeypatch.setattr(
        "argus.pipelines.refresh_prices.get_market_data_provider",
        lambda: MockFailingProvider(),
    )

    # Run price refresh
    result = refresh_prices(period="2y")
    assert "NVDA" in result["failed_symbols"]

    # Verify ProviderHealth in DB
    with Session(sqlite_engine) as session:
        health = session.query(ProviderHealth).filter_by(provider="yfinance").one()
        assert health.status == "unhealthy"
        assert health.failure_count == 1
        assert "yfinance connection timed out" in (health.last_error or "")


def test_refresh_filings_provider_health_failure(sqlite_engine, monkeypatch) -> None:
    # Seed active company with CIK
    with Session(sqlite_engine) as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", cik="0001045810", is_active=True))
        session.commit()

    def mock_fetch_filings(cik):
        raise RuntimeError("SEC API unavailable")

    monkeypatch.setattr("argus.pipelines.refresh_filings.fetch_filings", mock_fetch_filings)
    monkeypatch.setattr("argus.core.settings.settings.sec_user_agent", "TestAgent/1.0")

    # Run filings refresh
    result = refresh_filings()
    assert "NVDA" in result["failed_symbols"]

    # Verify ProviderHealth in DB
    with Session(sqlite_engine) as session:
        health = session.query(ProviderHealth).filter_by(provider="sec").one()
        assert health.status == "unhealthy"
        assert health.failure_count == 1
        assert "SEC API unavailable" in (health.last_error or "")


def test_refresh_news_provider_health_failure(sqlite_engine, monkeypatch) -> None:
    # Seed active company
    with Session(sqlite_engine) as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", is_active=True))
        session.commit()

    def mock_fetch_rss(query):
        raise ValueError("RSS feed socket error")

    def mock_fetch_gdelt(query, timespan):
        raise ValueError("GDELT API server down")

    monkeypatch.setattr("argus.pipelines.refresh_news.fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr("argus.pipelines.refresh_news.fetch_gdelt_news", mock_fetch_gdelt)

    # Run news refresh
    result = refresh_news(force=True, queries=["NVDA"])
    assert "rss" in result["failed_providers"]
    assert "gdelt" in result["failed_providers"]

    # Verify ProviderHealth in DB
    with Session(sqlite_engine) as session:
        rss_health = session.query(ProviderHealth).filter_by(provider="rss").one()
        assert rss_health.status == "unhealthy"
        assert rss_health.failure_count == 1
        assert "RSS feed socket error" in (rss_health.last_error or "")

        gdelt_health = session.query(ProviderHealth).filter_by(provider="gdelt").one()
        assert gdelt_health.status == "unhealthy"
        assert gdelt_health.failure_count == 1
        assert "GDELT API server down" in (gdelt_health.last_error or "")


def test_refresh_macro_provider_health_failure(sqlite_engine, monkeypatch) -> None:
    def mock_fetch_fred(code, **kwargs):
        raise ValueError("FRED database connection reset")

    def mock_fetch_eia(route, **kwargs):
        raise ValueError("EIA database connection reset")

    monkeypatch.setattr("argus.pipelines.refresh_macro.fetch_fred_series", mock_fetch_fred)
    monkeypatch.setattr("argus.pipelines.refresh_macro.fetch_eia_series", mock_fetch_eia)
    monkeypatch.setattr("argus.core.settings.settings.eia_api_key", "test-key")

    # Run macro refresh
    result = refresh_macro(series_codes=["DGS10", "EIA_ELEC_PRICE"])
    assert "DGS10" in result["failed_series"]
    assert "EIA_ELEC_PRICE" in result["failed_series"]

    # Verify ProviderHealth in DB
    with Session(sqlite_engine) as session:
        fred_health = session.query(ProviderHealth).filter_by(provider="fred").one()
        assert fred_health.status == "unhealthy"
        assert fred_health.failure_count == 1
        assert "FRED database connection reset" in (fred_health.last_error or "")

        eia_health = session.query(ProviderHealth).filter_by(provider="eia").one()
        assert eia_health.status == "unhealthy"
        assert eia_health.failure_count == 1
        assert "EIA database connection reset" in (eia_health.last_error or "")
