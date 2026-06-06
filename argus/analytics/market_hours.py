from __future__ import annotations

from datetime import time
from datetime import date as date_type
from zoneinfo import ZoneInfo

import pandas as pd

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def is_regular_market_timestamp(value, naive_tz: ZoneInfo | None = None) -> bool:
    """Return True if *value* falls within regular market hours (9:30–16:00 ET).

    Args:
        value: A timestamp-like value.
        naive_tz: The timezone to assume for timezone-naive inputs.
            Defaults to UTC (historical behaviour).
            Pass ``MARKET_TZ`` when the caller has already converted
            timestamps to ET-naive (e.g. ``tz_localize(None)`` after
            ``tz_convert("America/New_York")``).
    """
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return False
    if timestamp.tzinfo is None:
        tz = naive_tz if naive_tz is not None else ZoneInfo("UTC")
        timestamp = timestamp.tz_localize(tz)
    market_timestamp = timestamp.tz_convert(MARKET_TZ)
    market_time = market_timestamp.time()
    return market_timestamp.weekday() < 5 and MARKET_OPEN <= market_time <= MARKET_CLOSE


def market_session_date(value, naive_tz: ZoneInfo | None = None) -> date_type | None:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        tz = naive_tz if naive_tz is not None else ZoneInfo("UTC")
        timestamp = timestamp.tz_localize(tz)
    market_timestamp = timestamp.tz_convert(MARKET_TZ)
    return market_timestamp.date()


def filter_regular_market_hours(
    frame: pd.DataFrame,
    column: str = "date",
    naive_tz: ZoneInfo | None = None,
) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame
    mask = pd.to_datetime(frame[column]).apply(
        lambda v: is_regular_market_timestamp(v, naive_tz=naive_tz)
    )
    return frame.loc[mask].copy()


def filter_latest_market_sessions(
    frame: pd.DataFrame,
    sessions: int,
    column: str = "date",
    naive_tz: ZoneInfo | None = None,
) -> pd.DataFrame:
    """Filter *frame* to the most recent *sessions* trading days.

    Args:
        frame: DataFrame with a timestamp column.
        sessions: Number of most-recent market sessions to keep.
        column: Name of the timestamp column.
        naive_tz: Timezone to assume for timezone-naive timestamps.
            Defaults to UTC. Pass ``MARKET_TZ`` when the DataFrame's
            timestamps have already been converted to ET-naive form.
    """
    if frame.empty or column not in frame.columns or sessions <= 0:
        return frame

    result = filter_regular_market_hours(frame, column=column, naive_tz=naive_tz)
    if result.empty:
        return result

    result["_market_session_date"] = pd.to_datetime(result[column]).apply(
        lambda v: market_session_date(v, naive_tz=naive_tz)
    )
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


def append_market_close_markers(
    intraday_frame: pd.DataFrame,
    daily_frame: pd.DataFrame,
    *,
    value_columns: list[str],
    timeframe: str,
    date_column: str = "date",
    daily_date_column: str = "date",
) -> pd.DataFrame:
    """Append synthetic 4:00 PM ET close rows to completed intraday sessions.

    The caller must pass intraday timestamps that are already ET-naive. The
    daily frame should contain the official daily close values for the same
    columns listed in ``value_columns``.
    """
    if (
        timeframe not in {"1D", "5D"}
        or intraday_frame.empty
        or daily_frame.empty
        or date_column not in intraday_frame.columns
        or daily_date_column not in daily_frame.columns
    ):
        return intraday_frame

    frame = intraday_frame.copy()
    daily = daily_frame.copy()
    frame[date_column] = pd.to_datetime(frame[date_column])
    daily["_market_close_date"] = pd.to_datetime(daily[daily_date_column]).dt.date
    today_et = pd.Timestamp.now(tz=MARKET_TZ).date()

    rows_to_append = []
    session_dates = sorted(frame[date_column].dt.date.dropna().unique())
    if timeframe == "1D":
        session_dates = session_dates[-1:]

    for session_date in session_dates:
        if session_date >= today_et:
            continue
        session_rows = frame[frame[date_column].dt.date == session_date]
        if session_rows.empty:
            continue
        if pd.to_datetime(session_rows[date_column]).max().time() != time(15, 45):
            continue
        close_ts = pd.Timestamp(
            session_date.year,
            session_date.month,
            session_date.day,
            MARKET_CLOSE.hour,
            MARKET_CLOSE.minute,
        )
        if (frame[date_column] == close_ts).any():
            continue
        daily_match = daily[daily["_market_close_date"] == session_date]
        if daily_match.empty:
            continue

        close_row = {date_column: close_ts}
        daily_row = daily_match.iloc[-1]
        for column in value_columns:
            if column in frame.columns and column in daily.columns:
                close_row[column] = daily_row[column]
        rows_to_append.append(close_row)

    if not rows_to_append:
        return intraday_frame

    append_frame = pd.DataFrame(rows_to_append)
    return pd.concat([frame, append_frame], ignore_index=True).sort_values(date_column).reset_index(drop=True)
