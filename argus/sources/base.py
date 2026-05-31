from __future__ import annotations
from abc import ABC, abstractmethod
import pandas as pd

class BaseMarketDataProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the market data provider."""
        pass

    @abstractmethod
    def fetch_daily_ohlcv(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        """Fetch daily OHLCV bars for the given symbol.
        
        Returned DataFrame must contain columns:
        ['date', 'open', 'high', 'low', 'close', 'adj_close', 'volume']
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is configured and available (e.g. key exists)."""
        pass


def period_to_timestamps(period: str) -> tuple[int, int]:
    """Convert period (e.g. '2y', '6mo') to unix timestamps."""
    import time
    end_ts = int(time.time())
    if period.endswith("y"):
        years = int(period[:-1])
        start_ts = end_ts - years * 365 * 24 * 60 * 60
    elif period.endswith("mo"):
        months = int(period[:-2])
        start_ts = end_ts - months * 30 * 24 * 60 * 60
    elif period.endswith("d"):
        days = int(period[:-1])
        start_ts = end_ts - days * 24 * 60 * 60
    else:
        # default to 2 years
        start_ts = end_ts - 2 * 365 * 24 * 60 * 60
    return start_ts, end_ts

