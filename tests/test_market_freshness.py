from datetime import datetime
from zoneinfo import ZoneInfo

from argus.core.market_freshness import expected_daily_market_date


def test_expected_daily_market_date_uses_eastern_close_and_weekends() -> None:
    et = ZoneInfo("America/New_York")
    assert expected_daily_market_date(datetime(2026, 9, 21, 19, 59, tzinfo=et)).isoformat() == "2026-09-18"
    assert expected_daily_market_date(datetime(2026, 9, 21, 20, 0, tzinfo=et)).isoformat() == "2026-09-21"
    assert expected_daily_market_date(datetime(2026, 9, 20, 21, 0, tzinfo=et)).isoformat() == "2026-09-18"


def test_expected_daily_market_date_converts_utc_to_eastern() -> None:
    utc = ZoneInfo("UTC")
    assert expected_daily_market_date(datetime(2026, 9, 22, 0, 30, tzinfo=utc)).isoformat() == "2026-09-21"
