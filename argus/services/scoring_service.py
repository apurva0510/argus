from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Any
from sqlalchemy import text


def load_scoring_inputs_for_active_companies(session_or_conn) -> dict[int, dict[str, Any]]:
    """Load scoring inputs (theme exposure, news, filings, earnings) for all active companies.

    Returns a dictionary mapping company_id (int) to a dict of inputs:
      - theme_exposure_score (float | None)
      - recent_news_count (int)
      - recent_filing_count (int)
      - upcoming_earnings_days (float | None)
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    news_start_date = now - timedelta(days=7)
    filing_start_date = (now - timedelta(days=30)).date()
    current_date = now.date()

    if hasattr(session_or_conn, "bind") and session_or_conn.bind is not None:
        dialect_name = session_or_conn.bind.dialect.name
    else:
        dialect = getattr(session_or_conn, "dialect", None)
        dialect_name = dialect.name if dialect is not None else "sqlite"

    if dialect_name == "postgresql":
        earnings_expr = "MIN(ee.event_date - :current_date)"
    else:
        earnings_expr = "MIN(JULIANDAY(ee.event_date) - JULIANDAY(:current_date))"

    query_str = f"""
        SELECT
            c.id AS company_id,
            (
                SELECT MAX(cte.exposure_score)
                FROM company_theme_exposure cte
                WHERE cte.company_id = c.id
            ) AS theme_exposure_score,
            (
                SELECT COUNT(*)
                FROM news_mentions nm
                JOIN news_items ni ON ni.id = nm.news_id
                WHERE nm.company_id = c.id
                    AND ni.published_at >= :news_start_date
            ) AS recent_news_count,
            (
                SELECT COUNT(*)
                FROM sec_filings sf
                WHERE sf.company_id = c.id
                    AND sf.filing_date >= :filing_start_date
            ) AS recent_filing_count,
            (
                SELECT {earnings_expr}
                FROM earnings_events ee
                WHERE ee.company_id = c.id
                    AND ee.event_date >= :current_date
            ) AS upcoming_earnings_days
        FROM companies c
        WHERE c.is_active = TRUE
    """

    rows = session_or_conn.execute(
        text(query_str),
        {
            "news_start_date": news_start_date,
            "filing_start_date": filing_start_date,
            "current_date": current_date,
        },
    ).mappings()

    result = {}
    for row in rows:
        row_dict = dict(row)
        cid = row_dict.pop("company_id")
        result[cid] = row_dict
    return result
