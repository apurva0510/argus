from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import text

from argus.analytics.scoring import compute_opportunity_score
from argus.analytics.valuation import FUNDAMENTALS_MAX_AGE_DAYS
from argus.core.db import session_scope
from argus.core.models import DailyMetric
from argus.pipelines.job_runs import job_run_context
from argus.services.scoring_service import build_score_inputs, load_scoring_inputs_for_active_companies

logger = logging.getLogger(__name__)


def _load_score_inputs(session) -> list[dict]:
    query_str = """
            SELECT
                dm.id AS daily_metric_id,
                c.id AS company_id,
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
                vps_ev.valuation_flag AS valuation_flag,
                fs.revenue_growth AS revenue_growth
            FROM daily_metrics dm
            JOIN companies c ON c.id = dm.company_id
            LEFT JOIN valuation_peer_snapshot vps_ev ON vps_ev.id = (
                SELECT vps_ev2.id
                FROM valuation_peer_snapshot vps_ev2
                WHERE vps_ev2.company_id = c.id
                    AND vps_ev2.peer_group_type = 'sector'
                    AND vps_ev2.metric_name = 'ev_to_sales'
                    AND vps_ev2.as_of_date >= :min_snapshot_date
                ORDER BY vps_ev2.as_of_date DESC, vps_ev2.id DESC
                LIMIT 1
            )
            LEFT JOIN fundamentals_snapshot fs ON fs.id = (
                SELECT fs2.id
                FROM fundamentals_snapshot fs2
                WHERE fs2.company_id = c.id
                    AND fs2.as_of_date >= :min_snapshot_date
                ORDER BY fs2.as_of_date DESC, fs2.id DESC
                LIMIT 1
            )
            WHERE c.is_active = TRUE
                AND dm.date = (
                    SELECT MAX(dm2.date)
                    FROM daily_metrics dm2
                    WHERE dm2.company_id = c.id
                )
    """

    rows = session.execute(
        text(query_str),
        {"min_snapshot_date": date.today() - timedelta(days=FUNDAMENTALS_MAX_AGE_DAYS)},
    ).mappings()
    inputs = load_scoring_inputs_for_active_companies(session)

    results = []
    for row in rows:
        row_dict = dict(row)
        company_id = row_dict["company_id"]
        comp_inputs = inputs.get(company_id, {})
        row_dict["theme_exposure_score"] = comp_inputs.get("theme_exposure_score")
        row_dict["recent_news_count"] = comp_inputs.get("recent_news_count", 0)
        row_dict["recent_filing_count"] = comp_inputs.get("recent_filing_count", 0)
        row_dict["upcoming_earnings_days"] = comp_inputs.get("upcoming_earnings_days")
        results.append(row_dict)

    return results


def compute_opportunity_scores() -> dict[str, object]:
    with job_run_context("compute_opportunity_scores") as state:
        with session_scope() as session:
            from argus.services.macro_capex_service import load_macro_capex_context_from_engine

            try:
                macro_ctx = load_macro_capex_context_from_engine(session.bind)
                pressure_level = int(macro_ctx.get("pressure_level", 0))
            except Exception:
                pressure_level = 0

            rows = _load_score_inputs(session)
            state.rows_read = len(rows)

            for row in rows:
                breakdown = compute_opportunity_score(
                    build_score_inputs(row, macro_pressure_level=pressure_level)
                )

                metric = session.get(DailyMetric, row["daily_metric_id"])
                if metric is None:
                    logger.warning(
                        "Daily metric %s missing during score update", row["daily_metric_id"]
                    )
                    continue

                metric.opportunity_score = breakdown.opportunity_score
                state.rows_written += 1

    return {
        "status": state.status,
        "rows_read": state.rows_read,
        "rows_written": state.rows_written,
        "error_text": state.error_text,
    }
