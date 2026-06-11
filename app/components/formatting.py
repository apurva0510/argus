from __future__ import annotations

from datetime import datetime

import pandas as pd

from argus.core.timezones import format_et_datetime


def format_et_or_never(value) -> str:
    if value is None or pd.isna(value):
        return "Never"
    formatted = format_et_datetime(value)
    return formatted if formatted != "Never" else str(value)


def format_as_of_date(value) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    try:
        dt = pd.to_datetime(value)
    except Exception:
        return str(value)
    if getattr(dt, "tzinfo", None) is not None:
        return dt.tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p ET")
    if isinstance(value, datetime) or (" " in str(value) or "T" in str(value)):
        return dt.tz_localize("UTC").tz_convert("America/New_York").strftime(
            "%Y-%m-%d %I:%M %p ET"
        )
    return dt.strftime("%Y-%m-%d")


def format_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:+.{digits}f}%"


def format_plain_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:.{digits}f}%"


def format_bps(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.0f} bps"


def format_pct_colored(value: float | None, *, positive_is_bad: bool = False) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    pct_val = value * 100
    formatted = f"{pct_val:+.2f}%"
    if pct_val == 0:
        return f"<span style='color: #8b949e; font-weight: 600;'>{formatted}</span>"
    is_bad = pct_val > 0 if positive_is_bad else pct_val < 0
    color = "#f85149" if is_bad else "#3fb950"
    return f"<span style='color: {color}; font-weight: 600;'>{formatted}</span>"


def format_bps_colored(value: float | None, *, positive_is_bad: bool = False) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    formatted = f"{value:+.0f} bps"
    if value == 0:
        return f"<span style='color: #8b949e; font-weight: 600;'>{formatted}</span>"
    is_bad = value > 0 if positive_is_bad else value < 0
    color = "#f85149" if is_bad else "#3fb950"
    return f"<span style='color: {color}; font-weight: 600;'>{formatted}</span>"


def format_yield_observation(observation: object) -> str:
    if not isinstance(observation, dict) or observation.get("value") is None:
        return "n/a"
    return f"{float(observation['value']):.2f}%"


def format_currency(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    abs_value = abs(float(value))
    sign = "-" if float(value) < 0 else ""
    if abs_value >= 1_000_000_000_000:
        return f"{sign}${abs_value / 1_000_000_000_000:.2f}T"
    if abs_value >= 1_000_000_000:
        return f"{sign}${abs_value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{sign}${abs_value / 1_000_000:.2f}M"
    return f"{sign}${abs_value:,.0f}"


def format_price(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"${value:.2f}"


def format_price_range(low: float | None, high: float | None) -> str:
    if low is None or high is None or pd.isna(low) or pd.isna(high):
        return "n/a"
    # Two literal dollar signs are parsed as inline LaTeX by st.markdown.
    return f"&#36;{low:.2f} - &#36;{high:.2f}"


def format_multiple(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.2f}"


def format_large_number(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    is_neg = value < 0
    abs_val = abs(value)
    if abs_val >= 1e12:
        formatted = f"${abs_val / 1e12:.2f}T"
    elif abs_val >= 1e9:
        formatted = f"${abs_val / 1e9:.2f}B"
    elif abs_val >= 1e6:
        formatted = f"${abs_val / 1e6:.2f}M"
    else:
        formatted = f"${abs_val:,.2f}"
    return f"-{formatted}" if is_neg else formatted
