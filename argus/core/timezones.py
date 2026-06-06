from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")


def to_et(value) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    try:
        dt = pd.to_datetime(value)
    except Exception:
        return None
    if pd.isna(dt):
        return None
    if dt.tzinfo is None:
        dt = dt.tz_localize(UTC_TZ)
    else:
        dt = dt.tz_convert(UTC_TZ)
    return dt.tz_convert(ET).to_pydatetime()


def to_et_naive_series(values) -> pd.Series:
    dates = pd.to_datetime(values)
    if dates.dt.tz is None:
        dates = dates.dt.tz_localize(UTC_TZ)
    else:
        dates = dates.dt.tz_convert(UTC_TZ)
    return dates.dt.tz_convert(ET).dt.tz_localize(None)


def format_et_datetime(value, fmt: str = "%Y-%m-%d %I:%M %p ET") -> str:
    dt = to_et(value)
    if dt is None:
        return "Never"
    return dt.strftime(fmt)
