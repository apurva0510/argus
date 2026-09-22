"""Expected date for daily market data in Eastern time."""

from datetime import datetime, time, timedelta, date

from argus.core.timezones import ET


def expected_daily_market_date(now: datetime) -> date:
    """Require today's daily bar after 8 PM ET; otherwise use the last weekday.

    The evening cushion gives the scheduled close refresh time to complete.
    """
    now_et = now.astimezone(ET)
    candidate = now_et.date()
    if now_et.weekday() >= 5 or now_et.time() < time(20, 0):
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate
