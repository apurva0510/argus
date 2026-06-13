from datetime import date, datetime

import pandas as pd
import pytest

from argus.sources.yfinance_client import (
    YFinanceProvider,
    fetch_daily_ohlcv,
    fetch_earnings_calendar,
    fetch_fundamentals,
    fetch_ohlcv_batch,
)


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @property
    def info(self) -> dict:
        return {"symbol": self.symbol, "marketCap": 123.0}

    @property
    def calendar(self) -> dict:
        return {"Earnings Date": [date(2026, 7, 30)]}


def test_fetch_fundamentals_delegates_to_yfinance_ticker(monkeypatch) -> None:
    monkeypatch.setattr("argus.sources.yfinance_client.yf.Ticker", FakeTicker)

    assert fetch_fundamentals("AAPL") == {"symbol": "AAPL", "marketCap": 123.0}


def test_fetch_earnings_calendar_delegates_to_yfinance_ticker(monkeypatch) -> None:
    monkeypatch.setattr("argus.sources.yfinance_client.yf.Ticker", FakeTicker)

    assert fetch_earnings_calendar("AAPL") == {"Earnings Date": [date(2026, 7, 30)]}


def test_yfinance_provider_exposes_company_data_methods(monkeypatch) -> None:
    monkeypatch.setattr("argus.sources.yfinance_client.yf.Ticker", FakeTicker)
    provider = YFinanceProvider()

    assert provider.fetch_fundamentals("AAPL") == {"symbol": "AAPL", "marketCap": 123.0}
    assert provider.fetch_earnings_calendar("AAPL") == {
        "Earnings Date": [date(2026, 7, 30)]
    }


def test_fetch_daily_ohlcv_preserves_adjusted_close(monkeypatch) -> None:
    history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [100.5],
            "Volume": [1000],
        },
        index=pd.Index([pd.Timestamp("2025-01-02")], name="Date"),
    )

    monkeypatch.setattr("argus.sources.yfinance_client.yf.download", lambda **_kwargs: history)

    frame = fetch_daily_ohlcv("NVDA")

    assert frame.to_dict(orient="records") == [
        {
            "date": date(2025, 1, 2),
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "adj_close": 100.5,
            "volume": 1000,
        }
    ]


def test_fetch_daily_ohlcv_calls_yfinance_with_expected_daily_arguments(monkeypatch) -> None:
    history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [100.5],
            "Volume": [1000],
        },
        index=pd.Index([pd.Timestamp("2025-01-02")], name="Date"),
    )
    captured_kwargs = {}

    def fake_download(**kwargs):
        captured_kwargs.update(kwargs)
        return history

    monkeypatch.setattr("argus.sources.yfinance_client.yf.download", fake_download)

    fetch_daily_ohlcv("NVDA", period="6mo")

    assert captured_kwargs == {
        "tickers": "NVDA",
        "period": "6mo",
        "interval": "1d",
        "auto_adjust": False,
        "progress": False,
        "threads": False,
    }


def test_fetch_ohlcv_batch_calls_yfinance_once_for_15m_multi_ticker(monkeypatch) -> None:
    index = pd.Index(
        [pd.Timestamp("2026-05-29 09:30:00", tz="America/New_York")],
        name="Datetime",
    )
    history = pd.DataFrame(
        [[100.0, 200.0, 101.0, 202.0, 99.0, 198.0, 100.5, 201.0, 100.5, 201.0, 1000, 2000]],
        columns=pd.MultiIndex.from_product(
            [["Open", "High", "Low", "Close", "Adj Close", "Volume"], ["NVDA", "MSFT"]]
        ),
        index=index,
    )
    captured_kwargs = {}

    def fake_download(**kwargs):
        captured_kwargs.update(kwargs)
        return history

    monkeypatch.setattr("argus.sources.yfinance_client.yf.download", fake_download)

    frames = fetch_ohlcv_batch(["NVDA", "MSFT"], period="5d", interval="15m")

    assert captured_kwargs == {
        "tickers": ["NVDA", "MSFT"],
        "period": "5d",
        "interval": "15m",
        "auto_adjust": False,
        "progress": False,
        "threads": True,
        "group_by": "column",
    }
    assert set(frames) == {"NVDA", "MSFT"}
    assert frames["NVDA"].loc[0, "bar_time"] == datetime(2026, 5, 29, 13, 30)
    assert frames["NVDA"].loc[0, "date"] == date(2026, 5, 29)
    assert frames["MSFT"].loc[0, "close"] == 201.0


def test_fetch_ohlcv_batch_returns_empty_frames_for_empty_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "argus.sources.yfinance_client.yf.download", lambda **_kwargs: pd.DataFrame()
    )

    frames = fetch_ohlcv_batch(["BAD", "EMPTY"], period="5d", interval="15m")

    assert set(frames) == {"BAD", "EMPTY"}
    assert frames["BAD"].empty
    assert frames["EMPTY"].empty


def test_fetch_ohlcv_batch_isolates_malformed_ticker_payload(monkeypatch) -> None:
    index = pd.Index([pd.Timestamp("2026-05-29 09:30:00", tz="America/New_York")], name="Datetime")
    history = pd.DataFrame(
        [[100.0, 200.0, 101.0, 202.0, 99.0, 198.0, 100.5, 1000]],
        columns=pd.MultiIndex.from_tuples(
            [
                ("Open", "GOOD"),
                ("Open", "BAD"),
                ("High", "GOOD"),
                ("High", "BAD"),
                ("Low", "GOOD"),
                ("Low", "BAD"),
                ("Close", "GOOD"),
                ("Volume", "GOOD"),
            ]
        ),
        index=index,
    )

    monkeypatch.setattr("argus.sources.yfinance_client.yf.download", lambda **_kwargs: history)

    frames = fetch_ohlcv_batch(["GOOD", "BAD"], period="5d", interval="15m")

    assert not frames["GOOD"].empty
    assert frames["BAD"].empty


def test_fetch_daily_ohlcv_falls_back_to_close_when_adjusted_close_missing(monkeypatch) -> None:
    history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Volume": [1000],
        },
        index=pd.Index([pd.Timestamp("2025-01-02")], name="Date"),
    )

    monkeypatch.setattr("argus.sources.yfinance_client.yf.download", lambda **_kwargs: history)

    frame = fetch_daily_ohlcv("NVDA")

    assert frame.loc[0, "adj_close"] == 101.0


def test_fetch_daily_ohlcv_handles_multiindex_columns(monkeypatch) -> None:
    history = pd.DataFrame(
        [[100.0, 102.0, 99.0, 101.0, 100.5, 1000]],
        columns=pd.MultiIndex.from_product(
            [["Open", "High", "Low", "Close", "Adj Close", "Volume"], ["NVDA"]]
        ),
        index=pd.Index([pd.Timestamp("2025-01-02")], name="Date"),
    )

    monkeypatch.setattr("argus.sources.yfinance_client.yf.download", lambda **_kwargs: history)

    frame = fetch_daily_ohlcv("NVDA")

    assert frame.loc[0, "date"] == date(2025, 1, 2)
    assert frame.loc[0, "adj_close"] == 100.5


def test_fetch_daily_ohlcv_keeps_provider_daily_date_for_timezone_aware_index(monkeypatch) -> None:
    history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [100.5],
            "Volume": [1000],
        },
        index=pd.Index([pd.Timestamp("2025-01-02 23:30:00", tz="America/New_York")], name="Date"),
    )

    monkeypatch.setattr("argus.sources.yfinance_client.yf.download", lambda **_kwargs: history)

    frame = fetch_daily_ohlcv("NVDA")

    assert frame.loc[0, "date"] == date(2025, 1, 2)


def test_fetch_daily_ohlcv_returns_empty_frame_for_empty_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "argus.sources.yfinance_client.yf.download", lambda **_kwargs: pd.DataFrame()
    )

    frame = fetch_daily_ohlcv("BAD")

    assert frame.empty


def test_fetch_daily_ohlcv_rejects_missing_required_columns(monkeypatch) -> None:
    history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Volume": [1000],
        },
        index=pd.Index([pd.Timestamp("2025-01-02")], name="Date"),
    )

    monkeypatch.setattr("argus.sources.yfinance_client.yf.download", lambda **_kwargs: history)

    with pytest.raises(ValueError, match="missing columns: close"):
        fetch_daily_ohlcv("BAD")
