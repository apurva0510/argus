from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import yfinance as yf

REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def _normalize_daily_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def fetch_daily_ohlcv(symbol: str, period: str = "2y") -> pd.DataFrame:
    """Fetch daily yfinance OHLCV bars.

    The returned frame stores both raw close and adjusted close. Downstream return
    calculations should use ``adj_close``. For daily bars, dates are treated as
    provider-supplied exchange dates and are not converted across time zones.
    """
    history = yf.download(
        tickers=symbol,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if history.empty:
        return pd.DataFrame()

    if isinstance(history.columns, pd.MultiIndex):
        history.columns = history.columns.get_level_values(0)

    history = history.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    if "adj_close" not in history.columns:
        history["adj_close"] = history.get("close")

    frame = history.reset_index()
    date_column = "Date" if "Date" in frame.columns else frame.columns[0]
    missing_columns = REQUIRED_COLUMNS - set(frame.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"yfinance response for {symbol} missing columns: {missing}")

    frame["date"] = frame[date_column].apply(_normalize_daily_date)
    frame = frame[["date", "open", "high", "low", "close", "adj_close", "volume"]].copy()
    return frame


from argus.sources.base import BaseMarketDataProvider  # noqa: E402

class YFinanceProvider(BaseMarketDataProvider):
    @property
    def name(self) -> str:
        return "yfinance"

    def is_available(self) -> bool:
        return True

    def fetch_daily_ohlcv(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        return fetch_daily_ohlcv(symbol, period)

