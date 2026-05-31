from __future__ import annotations
import logging
import pandas as pd
import httpx
from datetime import datetime, UTC

from argus.core.settings import settings
from argus.sources.base import BaseMarketDataProvider, period_to_timestamps

logger = logging.getLogger(__name__)

class FinnhubProvider(BaseMarketDataProvider):
    @property
    def name(self) -> str:
        return "finnhub"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.finnhub_api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def fetch_daily_ohlcv(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        if not self.is_available():
            raise ValueError("Finnhub API key is not configured.")

        start_ts, end_ts = period_to_timestamps(period)
        url = "https://finnhub.io/api/v1/stock/candle"
        params = {
            "symbol": symbol,
            "resolution": "D",
            "from": start_ts,
            "to": end_ts,
            "token": self.api_key,
        }

        try:
            response = httpx.get(url, params=params, timeout=15.0)
            if response.status_code == 429:
                logger.warning("Finnhub API rate limit hit for symbol %s", symbol)
                return pd.DataFrame()
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.exception("Error fetching daily OHLCV from Finnhub for symbol %s: %s", symbol, e)
            return pd.DataFrame()

        if not data or data.get("s") != "ok":
            logger.warning("Finnhub returned no or unsuccessful data for symbol %s: %s", symbol, data.get("s", "no status"))
            return pd.DataFrame()

        # Build dataframe
        df = pd.DataFrame({
            "date": pd.to_datetime(data["t"], unit="s").date,
            "open": [float(x) for x in data["o"]],
            "high": [float(x) for x in data["h"]],
            "low": [float(x) for x in data["l"]],
            "close": [float(x) for x in data["c"]],
            "adj_close": [float(x) for x in data["c"]], # Finnhub free doesn't have split-adjusted in candles
            "volume": [float(x) for x in data["v"]],
        })
        return df
