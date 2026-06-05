from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def is_regular_market_timestamp(value) -> bool:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    market_timestamp = timestamp.tz_convert(MARKET_TZ)
    market_time = market_timestamp.time()
    return market_timestamp.weekday() < 5 and MARKET_OPEN <= market_time <= MARKET_CLOSE


def filter_regular_market_hours(frame: pd.DataFrame, column: str = "date") -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame
    mask = pd.to_datetime(frame[column]).apply(is_regular_market_timestamp)
    return frame.loc[mask].copy()
