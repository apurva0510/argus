from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import logging

from argus.core.db import session_scope
from argus.core.models import JobRun
from argus.core.settings import settings
from argus.pipelines.compute_metrics import compute_daily_metrics
from argus.pipelines.compute_scores import compute_opportunity_scores
from argus.pipelines.refresh_filings import refresh_filings
from argus.pipelines.refresh_news import refresh_news
from argus.pipelines.refresh_prices import refresh_prices
from argus.pipelines.refresh_earnings import refresh_earnings
from argus.pipelines.refresh_fundamentals import refresh_fundamentals
from argus.pipelines.refresh_index import refresh_index
from argus.pipelines.refresh_macro import refresh_macro
from argus.pipelines.run_alerts import run_alerts


logger = logging.getLogger(__name__)

PipelineStep = tuple[str, Callable[[], dict[str, object]]]


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _create_job_run() -> int:
    with session_scope() as session:
        job = JobRun(job_name="run_daily_refresh", started_at=_utc_now(), status="running")
        session.add(job)
        session.flush()
        return job.id


def _finish_job_run(
    job_id: int,
    *,
    status: str,
    rows_read: int,
    rows_written: int,
    error_text: str | None = None,
) -> None:
    with session_scope() as session:
        job = session.get(JobRun, job_id)
        if job is None:
            job = JobRun(
                id=job_id,
                job_name="run_daily_refresh",
                started_at=_utc_now(),
                status=status,
            )
            session.add(job)

        job.finished_at = _utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        job.error_text = error_text


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
            steps.append(("refresh_filings", refresh_filings))
        else:
            logger.info("Skipping SEC filings refresh because SEC_USER_AGENT is not configured.")

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
    job_id = _create_job_run()
    rows_read = 0
    rows_written = 0
    status = "success"
    errors: list[str] = []
    results: dict[str, dict[str, object]] = {}

    try:
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
            rows_read += int(result.get("rows_read") or 0)
            rows_written += int(result.get("rows_written") or 0)

            step_status = str(result.get("status") or "unknown")
            if step_status == "failed":
                errors.append(f"{step_name}: {result.get('error_text') or 'failed'}")
            elif step_status not in {"success", "skipped"}:
                status = "partial_success"

        if errors:
            status = "failed" if len(errors) == len(results) else "partial_success"
    except Exception as exc:
        status = "failed"
        errors.append(str(exc))
        logger.exception("Daily refresh orchestrator failed")
    finally:
        error_text = "; ".join(errors) if errors else None
        _finish_job_run(
            job_id,
            status=status,
            rows_read=rows_read,
            rows_written=rows_written,
            error_text=error_text,
        )

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "results": results,
        "error_text": "; ".join(errors) if errors else None,
    }
