from __future__ import annotations

from datetime import date

import pandas as pd

from argus.analytics.market_hours import append_market_close_markers


def test_append_market_close_markers_adds_completed_5d_sessions() -> None:
    intraday = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-06-04 15:30"), "adj_close": 99.0},
            {"date": pd.Timestamp("2026-06-04 15:45"), "adj_close": 100.0},
            {"date": pd.Timestamp("2026-06-05 15:45"), "adj_close": 101.0},
        ]
    )
    daily = pd.DataFrame(
        [
            {"date": date(2026, 6, 4), "adj_close": 100.5},
            {"date": date(2026, 6, 5), "adj_close": 102.0},
        ]
    )

    result = append_market_close_markers(
        intraday,
        daily,
        value_columns=["adj_close"],
        timeframe="5D",
    )

    close_rows = result[pd.to_datetime(result["date"]).dt.strftime("%H:%M") == "16:00"]
    assert close_rows["adj_close"].tolist() == [100.5, 102.0]
