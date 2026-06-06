from datetime import datetime

import pandas as pd

from argus.core.timezones import format_et_datetime, to_et_naive_series


def test_to_et_naive_series_converts_utc_values_to_et() -> None:
    values = pd.Series([datetime(2026, 6, 5, 13, 30), datetime(2026, 6, 5, 20, 0)])

    result = to_et_naive_series(values)

    assert result.iloc[0] == pd.Timestamp("2026-06-05 09:30:00")
    assert result.iloc[1] == pd.Timestamp("2026-06-05 16:00:00")


def test_format_et_datetime_returns_never_for_missing_values() -> None:
    assert format_et_datetime(None) == "Never"
