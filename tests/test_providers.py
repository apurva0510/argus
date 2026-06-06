from __future__ import annotations
import pytest
import pandas as pd
import httpx
import time
from unittest.mock import MagicMock
from datetime import date, datetime, UTC

from argus.core.settings import settings
from argus.sources.factory import get_market_data_provider
from argus.sources.yfinance_client import YFinanceProvider
from argus.sources.finnhub_client import FinnhubProvider
from argus.sources.twelvedata_client import TwelveDataProvider
from argus.sources.alphavantage_client import AlphaVantageProvider


def test_yfinance_provider_basic() -> None:
    provider = YFinanceProvider()
    assert provider.name == "yfinance"
    assert provider.is_available() is True


def test_finnhub_provider_availability() -> None:
    p1 = FinnhubProvider(api_key="")
    assert p1.is_available() is False

    p2 = FinnhubProvider(api_key="dummy_key")
    assert p2.is_available() is True


def test_twelvedata_provider_availability() -> None:
    p1 = TwelveDataProvider(api_key="")
    assert p1.is_available() is False

    p2 = TwelveDataProvider(api_key="dummy_key")
    assert p2.is_available() is True


def test_alphavantage_provider_availability() -> None:
    p1 = AlphaVantageProvider(api_key="")
    assert p1.is_available() is False

    p2 = AlphaVantageProvider(api_key="dummy_key")
    assert p2.is_available() is True


def test_finnhub_provider_fetch(monkeypatch) -> None:
    provider = FinnhubProvider(api_key="dummy")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "s": "ok",
        "t": [1622505600, 1622592000],
        "o": [100.0, 101.0],
        "h": [105.0, 106.0],
        "l": [99.0, 100.0],
        "c": [102.0, 103.0],
        "v": [5000, 6000],
    }

    def mock_get(*args, **kwargs):
        return mock_resp

    monkeypatch.setattr(httpx, "get", mock_get)

    df = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert not df.empty
    assert len(df) == 2
    assert list(df.columns) == ["date", "open", "high", "low", "close", "adj_close", "volume"]
    assert df.loc[0, "close"] == 102.0
    assert df.loc[0, "adj_close"] == 102.0
    assert df.loc[1, "volume"] == 6000.0


def test_twelvedata_provider_fetch(monkeypatch) -> None:
    provider = TwelveDataProvider(api_key="dummy")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "ok",
        "values": [
            {
                "datetime": "2026-05-29",
                "open": "100.00",
                "high": "105.00",
                "low": "99.00",
                "close": "102.50",
                "volume": "100000",
            },
            {
                "datetime": "2026-05-28",
                "open": "98.00",
                "high": "101.00",
                "low": "97.00",
                "close": "99.50",
                "volume": "80000",
            },
        ],
    }

    def mock_get(*args, **kwargs):
        return mock_resp

    monkeypatch.setattr(httpx, "get", mock_get)

    df = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert not df.empty
    assert len(df) == 2
    # Twelve data returns newest first; check that we sorted it to ascending (oldest first)
    assert df.loc[0, "close"] == 99.50
    assert df.loc[1, "close"] == 102.50
    assert df.loc[0, "volume"] == 80000.0


def test_alphavantage_provider_fetch(monkeypatch) -> None:
    provider = AlphaVantageProvider(api_key="dummy")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Time Series (Daily)": {
            "2026-05-29": {
                "1. open": "100.00",
                "2. high": "105.00",
                "3. low": "99.00",
                "4. close": "102.50",
                "5. volume": "100000",
            },
            "2026-05-28": {
                "1. open": "98.00",
                "2. high": "101.00",
                "3. low": "97.00",
                "4. close": "99.50",
                "5. volume": "80000",
            },
        }
    }

    def mock_get(*args, **kwargs):
        return mock_resp

    monkeypatch.setattr(httpx, "get", mock_get)

    df = provider.fetch_daily_ohlcv("AAPL", period="2y")
    assert not df.empty
    assert len(df) == 2
    # Ascending sort check
    assert df.loc[0, "close"] == 99.50
    assert df.loc[1, "close"] == 102.50


def test_factory_resolves_configured_when_available(monkeypatch) -> None:
    # 1. Configured yfinance should resolve yfinance
    p_yf = get_market_data_provider("yfinance")
    assert isinstance(p_yf, YFinanceProvider)
    assert p_yf.name == "yfinance"

    # 2. Configured finnhub with key should resolve finnhub
    monkeypatch.setattr(settings, "finnhub_api_key", "dummy_key")
    p_fh = get_market_data_provider("finnhub")
    assert isinstance(p_fh, FinnhubProvider)
    assert p_fh.name == "finnhub"


def test_factory_fallback_when_key_missing(monkeypatch) -> None:
    # Set config to finnhub but blank key in settings
    monkeypatch.setattr(settings, "finnhub_api_key", "")
    monkeypatch.setattr(settings, "market_data_provider", "finnhub")

    p = get_market_data_provider()
    # It must fallback to yfinance
    assert isinstance(p, YFinanceProvider)
    assert p.name == "yfinance"


def test_provider_field_persistence(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.models import Company, PriceBar
    from argus.pipelines.refresh_prices import refresh_prices
    from argus.sources.base import BaseMarketDataProvider
    from sqlalchemy.orm import Session, sessionmaker

    class MockCustomProvider(BaseMarketDataProvider):
        @property
        def name(self) -> str:
            return "mocked_custom"

        def is_available(self) -> bool:
            return True

        def fetch_daily_ohlcv(self, symbol: str, period: str = "2y") -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "date": date(2026, 5, 29),
                        "open": 100.0,
                        "high": 105.0,
                        "low": 99.0,
                        "close": 102.5,
                        "adj_close": 102.5,
                        "volume": 1000.0,
                    }
                ]
            )

    # 1. Mock DB SessionLocal
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    # 2. Mock factory resolution
    monkeypatch.setattr(
        "argus.pipelines.refresh_prices.get_market_data_provider",
        lambda: MockCustomProvider(),
    )

    # Seed company
    with db_module.session_scope() as session:
        session.add(Company(symbol="TEST_PERSIST", name="Persist Test", is_active=True))

    res = refresh_prices(period="2y")
    assert res["status"] == "success"

    # Verify provider name is correctly preserved in price bar DB record
    with db_module.session_scope() as session:
        bars = session.query(PriceBar).all()
        assert len(bars) == 1
        assert bars[0].provider == "mocked_custom"
        assert bars[0].close == 102.5


def test_provider_status_reporting(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.models import Company, JobRun
    from argus.services.dashboard_service import load_dashboard_data_from_engine
    from sqlalchemy.orm import Session, sessionmaker

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    # Mock settings active provider and API keys presence
    monkeypatch.setattr(settings, "market_data_provider", "finnhub")
    monkeypatch.setattr(settings, "finnhub_api_key", "secret_key")
    monkeypatch.setattr(settings, "twelve_data_api_key", "")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", "")

    # Insert a failed job run into job_runs
    with db_module.session_scope() as session:
        session.add(Company(symbol="CO_A", name="Co A", is_active=True))
        session.add(
            JobRun(
                job_name="refresh_prices",
                started_at=datetime.now(UTC).replace(tzinfo=None),
                finished_at=datetime.now(UTC).replace(tzinfo=None),
                status="failed",
                error_text="Finnhub connection timed out",
            )
        )

    data = load_dashboard_data_from_engine(sqlite_engine)

    assert "provider_status" in data
    p_status = data["provider_status"]
    assert p_status["active_provider"] == "finnhub"
    assert p_status["finnhub_available"] is True
    assert p_status["twelvedata_available"] is False

    assert "stale_tickers_count" in data
    assert data["stale_tickers_count"] == 1  # No prices imported at all -> stale

    assert "failed_job" in data
    assert data["failed_job"] is not None
    assert data["failed_job"]["job_name"] == "refresh_prices"
    assert data["failed_job"]["error_text"] == "Finnhub connection timed out"


def test_twelvedata_provider_chunking(monkeypatch) -> None:
    # 2 years span should yield 2 yearly chunks (since 2 * 365 = 730 days)
    # We will verify that fetch_daily_ohlcv makes exactly 2 HTTP requests and merges them
    provider = TwelveDataProvider(api_key="key")

    calls = []

    def mock_get(url, params, timeout=None):
        calls.append(params.copy())
        # Return mock JSON response matching chunk dates
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Return different data points depending on start_date
        date_str = params.get("start_date", "2026-05-29")
        mock_resp.json.return_value = {
            "status": "ok",
            "values": [
                {
                    "datetime": date_str,
                    "open": "100.00",
                    "high": "105.00",
                    "low": "99.00",
                    "close": "101.50",
                    "volume": "1000",
                }
            ],
        }
        return mock_resp

    monkeypatch.setattr(httpx, "get", mock_get)
    # Mock sleep to speed up test execution
    monkeypatch.setattr(time, "sleep", lambda x: None)

    df = provider.fetch_daily_ohlcv("AAPL", period="2y")

    # Assert exactly 2 HTTP requests were dispatched
    assert len(calls) == 2
    # Verify period start/end range dates differ across chunks
    assert calls[0]["start_date"] != calls[1]["start_date"]

    # Assert merged DataFrame
    assert not df.empty
    assert len(df) == 2


def test_alphavantage_provider_pacing(monkeypatch) -> None:
    # Reset pacing state to guarantee first call does not sleep
    monkeypatch.setattr("argus.sources.alphavantage_client._last_alphavantage_request_time", 0.0)
    provider = AlphaVantageProvider(api_key="key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Time Series (Daily)": {
            "2026-05-29": {
                "1. open": "100.0",
                "2. high": "100.0",
                "3. low": "100.0",
                "4. close": "100.0",
                "5. volume": "100",
            }
        }
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp)

    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    # Trigger first call
    provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert len(sleep_calls) == 0

    # Trigger second call immediately (must wait for pacing window)
    provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert len(sleep_calls) == 1
    assert sleep_calls[0] > 0.0
    assert sleep_calls[0] <= 12.5


def test_twelvedata_provider_pacing(monkeypatch) -> None:
    # Reset pacing state to guarantee first call does not sleep
    monkeypatch.setattr("argus.sources.twelvedata_client._last_twelvedata_request_time", 0.0)
    provider = TwelveDataProvider(api_key="key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "ok",
        "values": [
            {
                "datetime": "2026-05-29",
                "open": "100.00",
                "high": "105.00",
                "low": "99.00",
                "close": "101.50",
                "volume": "1000",
            }
        ],
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp)

    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    # Trigger first call (will execute 2 chunks for 2y period)
    provider.fetch_daily_ohlcv("AAPL", period="2y")

    # 2y period splits into 2 chunks -> sleep should be triggered between the chunks
    assert len(sleep_calls) == 1
    assert sleep_calls[0] > 0.0
    assert sleep_calls[0] <= 7.5


def test_factory_default_behavior_and_invalid_fallback(monkeypatch) -> None:
    # 1. Configured to nothing/empty -> defaults to yfinance
    monkeypatch.setattr(settings, "market_data_provider", "")
    p_def = get_market_data_provider()
    assert p_def.name == "yfinance"

    # 2. Configured to some junk/unknown provider -> fallback to yfinance
    monkeypatch.setattr(settings, "market_data_provider", "junk_provider_name")
    p_junk = get_market_data_provider()
    assert p_junk.name == "yfinance"


def test_provider_no_keys_raises_value_error(monkeypatch) -> None:
    # Set settings keys to blank
    monkeypatch.setattr(settings, "finnhub_api_key", "")
    monkeypatch.setattr(settings, "twelve_data_api_key", "")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", "")

    # Test Finnhub
    fh = FinnhubProvider(api_key="")
    assert fh.is_available() is False
    with pytest.raises(ValueError, match="Finnhub API key is not configured"):
        fh.fetch_daily_ohlcv("AAPL")

    # Test TwelveData
    td = TwelveDataProvider(api_key="")
    assert td.is_available() is False
    with pytest.raises(ValueError, match="Twelve Data API key is not configured"):
        td.fetch_daily_ohlcv("AAPL")

    # Test AlphaVantage
    av = AlphaVantageProvider(api_key="")
    assert av.is_available() is False
    with pytest.raises(ValueError, match="Alpha Vantage API key is not configured"):
        av.fetch_daily_ohlcv("AAPL")


def test_finnhub_provider_error_handling(monkeypatch) -> None:
    provider = FinnhubProvider(api_key="key")

    # Mock Rate Limit (429)
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp_429)
    df_429 = provider.fetch_daily_ohlcv("AAPL")
    assert df_429.empty

    # Mock bad response or 's' != 'ok'
    mock_resp_err = MagicMock()
    mock_resp_err.status_code = 200
    mock_resp_err.json.return_value = {"s": "no_data"}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp_err)
    df_err = provider.fetch_daily_ohlcv("AAPL")
    assert df_err.empty

    # Mock HTTP error (e.g. timeout / connection error)
    def mock_get_raise(*a, **k):
        raise httpx.RequestError("Connection failed")

    monkeypatch.setattr(httpx, "get", mock_get_raise)
    df_raise = provider.fetch_daily_ohlcv("AAPL")
    assert df_raise.empty


def test_twelvedata_provider_error_handling(monkeypatch) -> None:
    provider = TwelveDataProvider(api_key="key")

    # Mock Rate Limit (429)
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp_429)
    df_429 = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert df_429.empty

    # Mock 'status' != 'ok'
    mock_resp_err = MagicMock()
    mock_resp_err.status_code = 200
    mock_resp_err.json.return_value = {"status": "error", "message": "Invalid API key"}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp_err)
    df_err = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert df_err.empty

    # Mock request exception
    def mock_get_raise(*a, **k):
        raise httpx.RequestError("Connection failed")

    monkeypatch.setattr(httpx, "get", mock_get_raise)
    df_raise = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert df_raise.empty


def test_alphavantage_provider_error_handling(monkeypatch) -> None:
    # Reset pacing state
    monkeypatch.setattr("argus.sources.alphavantage_client._last_alphavantage_request_time", 0.0)
    provider = AlphaVantageProvider(api_key="key")

    # Mock Rate Limit (429)
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp_429)
    df_429 = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert df_429.empty

    # Mock json containing "Note" (Rate limit indicator)
    mock_resp_note = MagicMock()
    mock_resp_note.status_code = 200
    mock_resp_note.json.return_value = {
        "Note": "Thank you for using Alpha Vantage! Our standard API rate limit..."
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp_note)
    # Reset pacing state to guarantee call does not sleep
    monkeypatch.setattr("argus.sources.alphavantage_client._last_alphavantage_request_time", 0.0)
    df_note = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert df_note.empty

    # Mock json containing "Error Message"
    mock_resp_err = MagicMock()
    mock_resp_err.status_code = 200
    mock_resp_err.json.return_value = {"Error Message": "Invalid symbol"}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_resp_err)
    # Reset pacing state to guarantee call does not sleep
    monkeypatch.setattr("argus.sources.alphavantage_client._last_alphavantage_request_time", 0.0)
    df_err = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert df_err.empty

    # Mock request exception
    def mock_get_raise(*a, **k):
        raise httpx.RequestError("Connection failed")

    monkeypatch.setattr(httpx, "get", mock_get_raise)
    # Reset pacing state to guarantee call does not sleep
    monkeypatch.setattr("argus.sources.alphavantage_client._last_alphavantage_request_time", 0.0)
    df_raise = provider.fetch_daily_ohlcv("AAPL", period="1mo")
    assert df_raise.empty


def test_twelvedata_provider_chunk_truncation(monkeypatch) -> None:
    provider = TwelveDataProvider(api_key="key")

    # 6 years period should yield 6 chunks, but TwelveDataProvider truncates to latest 5 chunks (years)
    calls = []

    def mock_get(url, params, timeout=None):
        calls.append(params.copy())
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "ok",
            "values": [
                {
                    "datetime": params.get("start_date"),
                    "open": "100",
                    "high": "100",
                    "low": "100",
                    "close": "100",
                    "volume": "100",
                }
            ],
        }
        return mock_resp

    monkeypatch.setattr(httpx, "get", mock_get)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    df = provider.fetch_daily_ohlcv("AAPL", period="6y")
    # Verify that the length of chunks sent is exactly 5
    assert len(calls) == 5
    assert len(df) == 5
