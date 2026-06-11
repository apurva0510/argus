from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from app.components import formatting


def test_format_as_of_date_handles_dates_and_utc_datetimes() -> None:
    assert formatting.format_as_of_date("2026-05-29") == "2026-05-29"
    assert (
        formatting.format_as_of_date(datetime(2026, 5, 29, 20, 30, tzinfo=UTC))
        == "2026-05-29 04:30 PM ET"
    )
    assert formatting.format_as_of_date(None) == "n/a"


def test_percentage_and_bps_formatters_handle_missing_and_color_direction() -> None:
    assert formatting.format_pct(0.1234) == "+12.34%"
    assert formatting.format_plain_pct(0.1234, digits=1) == "12.3%"
    assert formatting.format_bps(-25.4) == "-25 bps"
    assert formatting.format_pct(pd.NA) == "n/a"

    assert "#3fb950" in formatting.format_pct_colored(0.01)
    assert "#f85149" in formatting.format_pct_colored(0.01, positive_is_bad=True)
    assert "#8b949e" in formatting.format_bps_colored(0)


def test_currency_price_and_large_number_formatters() -> None:
    assert formatting.format_currency(1_250_000_000) == "$1.25B"
    assert formatting.format_currency(-2_000_000) == "-$2.00M"
    assert formatting.format_price(123.456) == "$123.46"
    assert formatting.format_price_range(10, 20) == "&#36;10.00 - &#36;20.00"
    assert formatting.format_multiple(15.678) == "15.68"
    assert formatting.format_large_number(-1_500_000_000_000) == "-$1.50T"


def test_yield_observation_formatter() -> None:
    assert formatting.format_yield_observation({"value": "4.25"}) == "4.25%"
    assert formatting.format_yield_observation({}) == "n/a"
    assert formatting.format_yield_observation("4.25") == "n/a"
