from datetime import date, timedelta

from argus.analytics.downside_screen import (
    LOWER_RISK_SIGNAL,
    NO_SIGNAL,
    UNAVAILABLE,
    downside_screen_label,
)


def test_downside_screen_abstains_when_volatility_exceeds_threshold():
    today = date(2026, 9, 21)
    assert downside_screen_label(0.35, today, as_of=today) == LOWER_RISK_SIGNAL
    assert downside_screen_label(0.36, today, as_of=today) == NO_SIGNAL


def test_downside_screen_requires_fresh_nonbenchmark_metrics():
    today = date(2026, 9, 21)
    assert downside_screen_label(None, today, as_of=today) == UNAVAILABLE
    assert downside_screen_label(0.20, today - timedelta(days=6), as_of=today) == UNAVAILABLE
    assert downside_screen_label(0.20, today, as_of=today, is_benchmark=True) == UNAVAILABLE
