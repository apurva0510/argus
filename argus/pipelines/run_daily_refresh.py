from __future__ import annotations

from collections.abc import Callable
import logging

from argus.pipelines.job_runs import job_run_context
from argus.core.settings import settings
from argus.pipelines.compute_metrics import compute_daily_metrics
from argus.pipelines.compute_scores import compute_opportunity_scores
from argus.pipelines.compute_signals import compute_signals
from argus.pipelines.refresh_capex import refresh_capex
from argus.pipelines.refresh_ciks import refresh_ciks
from argus.pipelines.refresh_filings import refresh_filings
from argus.pipelines.refresh_news import refresh_news
from argus.pipelines.refresh_prices import refresh_prices
from argus.pipelines.refresh_earnings import refresh_earnings
from argus.pipelines.refresh_fundamentals import refresh_fundamentals
from argus.pipelines.refresh_index import refresh_index
from argus.pipelines.refresh_macro import refresh_macro
from argus.pipelines.refresh_release_calendar import refresh_release_calendar
from argus.pipelines.run_alerts import run_alerts


logger = logging.getLogger(__name__)

PipelineStep = tuple[str, Callable[[], dict[str, object]]]



def build_daily_refresh_steps(
    *,
    period: str = "2y",
    include_news: bool = True,
    include_filings: bool = True,
    include_alerts: bool = True,
    include_fundamentals: bool = True,
    include_earnings: bool = True,
    include_macro: bool = True,
) -> list[PipelineStep]:
    steps: list[PipelineStep] = [
        ("refresh_prices", lambda: refresh_prices(period=period)),
    ]

    if include_macro:
        steps.append(("refresh_macro", refresh_macro))
        if settings.fred_api_key.strip():
            steps.append(("refresh_release_calendar", refresh_release_calendar))

    if settings.sec_user_agent.strip():
        steps.append(("refresh_capex", refresh_capex))

    if include_fundamentals:
        steps.append(("refresh_fundamentals", refresh_fundamentals))

    if include_earnings:
        steps.append(("refresh_earnings", refresh_earnings))

    steps.extend(
        [
            ("compute_daily_metrics", compute_daily_metrics),
            ("compute_opportunity_scores", compute_opportunity_scores),
            ("refresh_index", refresh_index),
        ]
    )

    if include_news:
        steps.append(("refresh_news", refresh_news))

    if include_filings:
        if settings.sec_user_agent.strip():
            steps.append(("refresh_ciks", refresh_ciks))
            steps.append(("refresh_filings", refresh_filings))
        else:
            logger.info("Skipping SEC filings refresh because SEC_USER_AGENT is not configured.")

    steps.append(("compute_signals", compute_signals))

    if include_alerts:
        steps.append(("run_alerts", run_alerts))

    return steps


def run_daily_refresh(
    *,
    period: str = "2y",
    include_news: bool = True,
    include_filings: bool = True,
    include_alerts: bool = True,
    include_fundamentals: bool = True,
    include_earnings: bool = True,
    include_macro: bool = True,
    steps: list[PipelineStep] | None = None,
) -> dict[str, object]:
    """Run the daily refresh workflow without requiring Streamlit page load jobs."""
    errors: list[str] = []
    results: dict[str, dict[str, object]] = {}

    with job_run_context("run_daily_refresh") as state:
        for step_name, step_fn in steps or build_daily_refresh_steps(
            period=period,
            include_news=include_news,
            include_filings=include_filings,
            include_alerts=include_alerts,
            include_fundamentals=include_fundamentals,
            include_earnings=include_earnings,
            include_macro=include_macro,
        ):
            try:
                result = step_fn()
            except Exception as exc:
                logger.exception("Daily refresh step failed: %s", step_name)
                result = {"status": "failed", "error_text": str(exc)}

            results[step_name] = result
            state.rows_read += int(result.get("rows_read") or 0)
            state.rows_written += int(result.get("rows_written") or 0)

            step_status = str(result.get("status") or "unknown")
            if step_status == "failed":
                errors.append(f"{step_name}: {result.get('error_text') or 'failed'}")
            elif step_status not in {"success", "skipped"}:
                state.status = "partial_success"

        if errors:
            state.status = "failed" if len(errors) == len(results) else "partial_success"
            state.error_text = "; ".join(errors)

    return {
        "status": state.status,
        "rows_read": state.rows_read,
        "rows_written": state.rows_written,
        "results": results,
        "error_text": state.error_text,
    }
