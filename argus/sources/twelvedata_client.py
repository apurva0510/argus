from __future__ import annotations
import logging
import time
import datetime as dt_mod
from datetime import datetime, timezone
import httpx
import pandas as pd

from argus.core.settings import settings
from argus.sources.base import BaseMarketDataProvider, period_to_timestamps

logger = logging.getLogger(__name__)

_last_twelvedata_request_time = 0.0
TWELVEDATA_MIN_INTERVAL = 7.5


class TwelveDataProvider(BaseMarketDataProvider):
    @property
    def name(self) -> str:
        return "twelvedata"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.twelve_data_api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def fetch_daily_ohlcv(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        if not self.is_available():
            raise ValueError("Twelve Data API key is not configured.")

        start_ts, end_ts = period_to_timestamps(period)
        start_dt = datetime.fromtimestamp(start_ts, timezone.utc).date()
        end_dt = datetime.fromtimestamp(end_ts, timezone.utc).date()

        # Split requested period into 365-day chunks to prevent API constraints on large ranges
        chunks = []
        curr_start = start_dt
        while curr_start <= end_dt:
            curr_end = min(curr_start + dt_mod.timedelta(days=365), end_dt)
            chunks.append((curr_start.strftime("%Y-%m-%d"), curr_end.strftime("%Y-%m-%d")))
            curr_start = curr_end + dt_mod.timedelta(days=1)

        # Restrict to latest 5 chunks (years) to avoid excessive API requests
        if len(chunks) > 5:
            logger.warning("Twelve Data request spans %d years; truncating to latest 5 years to avoid hitting free-tier constraints.", len(chunks))
            chunks = chunks[-5:]

        all_values = []
        global _last_twelvedata_request_time

        url = "https://api.twelvedata.com/time_series"
        for c_start, c_end in chunks:
            # Enforce pacing between requests
            now = time.time()
            elapsed = now - _last_twelvedata_request_time
            if elapsed < TWELVEDATA_MIN_INTERVAL:
                wait_time = TWELVEDATA_MIN_INTERVAL - elapsed
                logger.info("Twelve Data pacing: waiting %.2f seconds", wait_time)
                time.sleep(wait_time)

            params = {
                "symbol": symbol,
                "interval": "1day",
                "start_date": c_start,
                "end_date": c_end,
                "apikey": self.api_key,
                "outputsize": 5000,
            }

            _last_twelvedata_request_time = time.time()
            try:
                response = httpx.get(url, params=params, timeout=15.0)
                if response.status_code == 429:
                    logger.warning("Twelve Data API rate limit hit for symbol %s", symbol)
                    break
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.exception("Error fetching daily OHLCV from Twelve Data for symbol %s: %s", symbol, e)
                break

            if not data or data.get("status") != "ok" or "values" not in data:
                logger.warning("Twelve Data returned no or unsuccessful data for symbol %s: %s", symbol, data.get("message", "no status"))
                break

            all_values.extend(data["values"])

        if not all_values:
            return pd.DataFrame()

        df = pd.DataFrame(all_values)
        
        # Twelve Data returns strings; cast and rename
        df = df.rename(columns={"datetime": "date"})
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["adj_close"] = df["close"]  # Twelve Data free tier doesn't have split-adjusted close in base candles
        df["volume"] = df["volume"].astype(float)

        # Drop duplicates from chunk boundary alignments
        df = df.drop_duplicates(subset=["date"])
        # Sort ascending by date to be consistent
        df = df.sort_values("date").reset_index(drop=True)
        return df
