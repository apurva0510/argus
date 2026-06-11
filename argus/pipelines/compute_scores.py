from __future__ import annotations

from datetime import datetime, timedelta, UTC
import logging

from sqlalchemy import text

from argus.analytics.scoring import ScoreInputs, compute_opportunity_score
from argus.core.db import session_scope
from argus.core.models import DailyMetric
from argus.pipelines.job_runs import create_job_run, finish_job_run

logger = logging.getLogger(__name__)


def _load_score_inputs(session) -> list[dict]:
    # Calculate dates in Python to remain DB-agnostic
    now = datetime.now(UTC).replace(tzinfo=None)
    news_start_date = now - timedelta(days=7)
    filing_start_date = (now - timedelta(days=30)).date()
    current_date = now.date()

    dialect_name = session.bind.dialect.name
    if dialect_name == "postgresql":
        earnings_expr = "MIN(ee.event_date - :current_date)"
    else:
        earnings_expr = "MIN(JULIANDAY(ee.event_date) - JULIANDAY(:current_date))"

    query_str = f"""
            SELECT
                dm.id AS daily_metric_id,
                c.symbol AS symbol,
                c.sector AS sector,
                (
                    SELECT wi.watch_status
                    FROM watchlist_items wi
                    WHERE wi.company_id = c.id
                    ORDER BY CASE wi.watch_status
                        WHEN 'high_priority' THEN 4
                        WHEN 'owned' THEN 3
                        WHEN 'watch' THEN 2
                        WHEN 'ignore' THEN 1
                        ELSE 0
                    END DESC
                    LIMIT 1
                ) AS watch_status,
                dm.drawdown_52w AS drawdown_52w,
                dm.rsi_14 AS rsi_14,
                dm.distance_from_200dma AS distance_from_200dma,
                dm.relative_return_vs_qqq_3m AS relative_return_vs_qqq_3m,
                dm.return_1w AS return_1w,
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
            FROM daily_metrics dm
            JOIN companies c ON c.id = dm.company_id
            WHERE c.is_active = TRUE
                AND dm.date = (
                    SELECT MAX(dm2.date)
                    FROM daily_metrics dm2
                    WHERE dm2.company_id = c.id
                )
    """

    rows = session.execute(
        text(query_str),
        {
            "news_start_date": news_start_date,
            "filing_start_date": filing_start_date,
            "current_date": current_date,
        },
    ).mappings()

    return [dict(row) for row in rows]


def compute_opportunity_scores() -> dict[str, object]:
    job_id = create_job_run("compute_opportunity_scores")
    rows_read = 0
    rows_written = 0
    status = "success"
    error_text: str | None = None

    try:
        with session_scope() as session:
            from argus.services.macro_capex_service import load_macro_capex_context_from_engine

            try:
                macro_ctx = load_macro_capex_context_from_engine(session.bind)
                pressure_level = int(macro_ctx.get("pressure_level", 0))
            except Exception:
                pressure_level = 0

            rows = _load_score_inputs(session)
            rows_read = len(rows)

            for row in rows:
                earnings_days = row.get("upcoming_earnings_days")
                if earnings_days is None:
                    earnings_days_value = None
                else:
                    earnings_days_value = max(0, int(round(float(earnings_days))))

                breakdown = compute_opportunity_score(
                    ScoreInputs(
                        theme_exposure_score=row.get("theme_exposure_score"),
                        drawdown_52w=row.get("drawdown_52w"),
                        rsi_14=row.get("rsi_14"),
                        distance_from_200dma=row.get("distance_from_200dma"),
                        relative_return_vs_qqq_3m=row.get("relative_return_vs_qqq_3m"),
                        watch_status=row.get("watch_status"),
                        recent_news_count=_safe_int(row.get("recent_news_count")),
                        recent_filing_count=_safe_int(row.get("recent_filing_count")),
                        upcoming_earnings_days=earnings_days_value,
                        return_1w=row.get("return_1w"),
                        macro_pressure_level=pressure_level,
                        sector=row.get("sector"),
                    )
                )

                metric = session.get(DailyMetric, row["daily_metric_id"])
                if metric is None:
                    logger.warning(
                        "Daily metric %s missing during score update", row["daily_metric_id"]
                    )
                    continue

                metric.opportunity_score = breakdown.opportunity_score
                rows_written += 1
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Opportunity score computation failed")
    finally:
        finish_job_run(
            job_id,
            "compute_opportunity_scores",
            status=status,
            rows_read=rows_read,
            rows_written=rows_written,
            error_text=error_text,
        )

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "error_text": error_text,
    }


def _safe_int(value) -> int | None:
    if value is None:
        return None
    return int(value)
