from __future__ import annotations

from datetime import time
from datetime import date as date_type
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


def market_session_date(value) -> date_type | None:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    market_timestamp = timestamp.tz_convert(MARKET_TZ)
    return market_timestamp.date()


def filter_regular_market_hours(frame: pd.DataFrame, column: str = "date") -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame
    mask = pd.to_datetime(frame[column]).apply(is_regular_market_timestamp)
    return frame.loc[mask].copy()


def filter_latest_market_sessions(
    frame: pd.DataFrame,
    sessions: int,
    column: str = "date",
) -> pd.DataFrame:
    if frame.empty or column not in frame.columns or sessions <= 0:
        return frame

    result = filter_regular_market_hours(frame, column=column)
    if result.empty:
        return result

    result["_market_session_date"] = pd.to_datetime(result[column]).apply(market_session_date)
    session_dates = (
        result["_market_session_date"]
        .dropna()
        .drop_duplicates()
        .sort_values()
        .tail(sessions)
        .tolist()
    )
    if not session_dates:
        return result.drop(columns=["_market_session_date"])

    result = result[result["_market_session_date"].isin(session_dates)].copy()
    return result.drop(columns=["_market_session_date"])
