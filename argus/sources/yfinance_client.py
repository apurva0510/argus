from __future__ import annotations

from datetime import UTC, date, datetime
from collections.abc import Sequence

import pandas as pd
import yfinance as yf

REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def _normalize_daily_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _normalize_bar_time(value) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(UTC).tz_localize(None)
    return timestamp.to_pydatetime()


def _normalize_ohlcv_frame(history: pd.DataFrame, symbol: str, *, interval: str) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()

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
    time_column = (
        "Datetime"
        if "Datetime" in frame.columns
        else "Date"
        if "Date" in frame.columns
        else frame.columns[0]
    )
    missing_columns = REQUIRED_COLUMNS - set(frame.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"yfinance response for {symbol} missing columns: {missing}")

    if interval == "1d":
        frame["date"] = frame[time_column].apply(_normalize_daily_date)
        frame["bar_time"] = frame["date"].apply(
            lambda value: datetime.combine(value, datetime.min.time())
        )
    else:
        frame["bar_time"] = frame[time_column].apply(_normalize_bar_time)
        frame["date"] = frame["bar_time"].apply(lambda value: value.date())

    return frame[["date", "bar_time", "open", "high", "low", "close", "adj_close", "volume"]].copy()


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

    return _normalize_ohlcv_frame(history, symbol, interval="1d").drop(columns=["bar_time"])


def fetch_ohlcv_batch(
    symbols: Sequence[str],
    *,
    period: str,
    interval: str,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV bars for many symbols with one yfinance download call."""
    normalized_symbols = [symbol.upper().strip() for symbol in symbols if symbol.strip()]
    if not normalized_symbols:
        return {}

    history = yf.download(
        tickers=normalized_symbols,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if history.empty:
        return {symbol: pd.DataFrame() for symbol in normalized_symbols}

    frames_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in normalized_symbols:
        try:
            frames_by_symbol[symbol] = _normalize_ohlcv_frame(
                _extract_symbol_history(history, symbol, normalized_symbols),
                symbol,
                interval=interval,
            )
        except ValueError:
            frames_by_symbol[symbol] = pd.DataFrame()
    return frames_by_symbol


def _extract_symbol_history(
    history: pd.DataFrame,
    symbol: str,
    symbols: Sequence[str],
) -> pd.DataFrame:
    if not isinstance(history.columns, pd.MultiIndex):
        return history.copy() if len(symbols) == 1 else pd.DataFrame()

    if symbol in history.columns.get_level_values(1):
        return history.xs(symbol, axis=1, level=1, drop_level=True).dropna(how="all")
    if symbol in history.columns.get_level_values(0):
        return history.xs(symbol, axis=1, level=0, drop_level=True).dropna(how="all")
    return pd.DataFrame()


from argus.sources.base import BaseMarketDataProvider  # noqa: E402


class YFinanceProvider(BaseMarketDataProvider):
    @property
    def name(self) -> str:
        return "yfinance"

    def is_available(self) -> bool:
        return True

    @property
    def supports_intraday_batch(self) -> bool:
        return True

    def fetch_daily_ohlcv(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        return fetch_daily_ohlcv(symbol, period)

    def fetch_ohlcv_batch(
        self,
        symbols: Sequence[str],
        *,
        period: str,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        return fetch_ohlcv_batch(symbols, period=period, interval=interval)
