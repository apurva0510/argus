from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Any

import pandas as pd
from sqlalchemy import text

from argus.analytics.scoring import ScoreInputs


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


def build_score_inputs(row: dict[str, Any], *, macro_pressure_level: int = 0) -> ScoreInputs:
    earnings_days = _optional_non_negative_int(row.get("upcoming_earnings_days"))
    return ScoreInputs(
        theme_exposure_score=row.get("theme_exposure_score"),
        drawdown_52w=row.get("drawdown_52w"),
        rsi_14=row.get("rsi_14"),
        distance_from_200dma=row.get("distance_from_200dma"),
        relative_return_vs_qqq_3m=row.get("relative_return_vs_qqq_3m"),
        watch_status=row.get("watch_status"),
        recent_news_count=_optional_int(row.get("recent_news_count")),
        recent_filing_count=_optional_int(row.get("recent_filing_count")),
        upcoming_earnings_days=earnings_days,
        return_1w=row.get("return_1w"),
        macro_pressure_level=macro_pressure_level,
        sector=row.get("sector"),
        valuation_flag=row.get("valuation_flag"),
        revenue_growth=row.get("revenue_growth"),
    )


def _is_missing(value: Any) -> bool:
    return value is None or pd.isna(value)


def _optional_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    return int(value)


def _optional_non_negative_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    return max(0, int(round(float(value))))
