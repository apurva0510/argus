"""Selective downside screen supported by historical 20-session outcomes."""

from __future__ import annotations

from datetime import date

import pandas as pd

DOWNSIDE_VOLATILITY_MAX = 0.35
MAX_METRIC_AGE_DAYS = 5
LOWER_RISK_SIGNAL = "Lower observed risk"
NO_SIGNAL = "No signal"
UNAVAILABLE = "Unavailable"


def downside_screen_label(
    volatility_20d: float | None,
    metrics_date: date | str | None,
    *,
    as_of: date | None = None,
    is_benchmark: bool = False,
) -> str:
    """Emit only the historically validated lower-risk signal; abstain otherwise."""
    if is_benchmark or volatility_20d is None or pd.isna(volatility_20d):
        return UNAVAILABLE
    if metrics_date is None or pd.isna(metrics_date):
        return UNAVAILABLE
    today = as_of or date.today()
    observed = pd.Timestamp(metrics_date).date()
    age = (today - observed).days
    if age < 0 or age > MAX_METRIC_AGE_DAYS:
        return UNAVAILABLE
    return LOWER_RISK_SIGNAL if float(volatility_20d) <= DOWNSIDE_VOLATILITY_MAX else NO_SIGNAL
