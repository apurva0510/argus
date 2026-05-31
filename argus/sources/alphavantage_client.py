from __future__ import annotations
import logging
import time
from datetime import datetime, timezone
import httpx
import pandas as pd

from argus.core.settings import settings
from argus.sources.base import BaseMarketDataProvider, period_to_timestamps

logger = logging.getLogger(__name__)

_last_alphavantage_request_time = 0.0
ALPHAVANTAGE_MIN_INTERVAL = 12.5


class AlphaVantageProvider(BaseMarketDataProvider):
    @property
    def name(self) -> str:
        return "alphavantage"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.alpha_vantage_api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def fetch_daily_ohlcv(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        if not self.is_available():
            raise ValueError("Alpha Vantage API key is not configured.")

        # Enforce rate-limit pacing for Alpha Vantage
        global _last_alphavantage_request_time
        now = time.time()
        elapsed = now - _last_alphavantage_request_time
        if elapsed < ALPHAVANTAGE_MIN_INTERVAL:
            wait_time = ALPHAVANTAGE_MIN_INTERVAL - elapsed
            logger.info("Alpha Vantage pacing: waiting %.2f seconds", wait_time)
            time.sleep(wait_time)

        _last_alphavantage_request_time = time.time()

        url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "full",
            "apikey": self.api_key,
        }

        try:
            response = httpx.get(url, params=params, timeout=15.0)
            if response.status_code == 429:
                logger.warning("Alpha Vantage API rate limit hit for symbol %s", symbol)
                return pd.DataFrame()
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.exception("Error fetching daily OHLCV from Alpha Vantage for symbol %s: %s", symbol, e)
            return pd.DataFrame()

        # Check for rate limit message in response JSON
        if "Note" in data:
            logger.warning("Alpha Vantage API rate limit note: %s", data["Note"])
            return pd.DataFrame()

        if "Error Message" in data:
            logger.error("Alpha Vantage error for symbol %s: %s", symbol, data["Error Message"])
            return pd.DataFrame()

        time_series = data.get("Time Series (Daily)")
        if not time_series:
            logger.warning("Alpha Vantage response missing Time Series (Daily) for symbol %s", symbol)
            return pd.DataFrame()

        records = []
        for date_str, metrics in time_series.items():
            records.append({
                "date": pd.to_datetime(date_str).date(),
                "open": float(metrics.get("1. open", 0)),
                "high": float(metrics.get("2. high", 0)),
                "low": float(metrics.get("3. low", 0)),
                "close": float(metrics.get("4. close", 0)),
                "adj_close": float(metrics.get("4. close", 0)), # Alpha Vantage TIME_SERIES_DAILY returns raw close; set adj_close to raw close
                "volume": float(metrics.get("5. volume", 0)),
            })

        df = pd.DataFrame(records)
        if df.empty:
            return df

        # Filter by start date based on period
        start_ts, end_ts = period_to_timestamps(period)
        start_date = datetime.fromtimestamp(start_ts, timezone.utc).date()
        df = df[df["date"] >= start_date]

        # Sort ascending by date to be consistent
        df = df.sort_values("date").reset_index(drop=True)
        return df
