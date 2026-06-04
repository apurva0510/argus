from __future__ import annotations

import logging
from datetime import UTC, datetime, date
from sqlalchemy import select
import yfinance as yf

from argus.core.db import session_scope, get_insert_statement_producer
from argus.core.models import Company, JobRun, EarningsEvent
from argus.pipelines.provider_health import execute_provider_request

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _create_job_run() -> int:
    with session_scope() as session:
        job = JobRun(job_name="refresh_earnings", started_at=_utc_now(), status="running")
        session.add(job)
        session.flush()
        return job.id


def _finish_job_run(
    job_id: int,
    *,
    status: str,
    rows_read: int,
    rows_written: int,
    failed_symbols: list[str],
    error_text: str | None = None,
) -> None:
    with session_scope() as session:
        job = session.get(JobRun, job_id)
        if job is None:
            job = JobRun(id=job_id, job_name="refresh_earnings", started_at=_utc_now(), status=status)
            session.add(job)

        job.finished_at = _utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        if error_text:
            job.error_text = error_text
        elif failed_symbols:
            job.error_text = f"Failed symbols: {', '.join(sorted(failed_symbols))}"


def _upsert_earnings_event_rows(session, company_id: int, events: list[dict]) -> int:
    if not events:
        return 0

    values = []
    for ev in events:
        values.append({
            "company_id": company_id,
            "event_date": ev["event_date"],
            "fiscal_period": ev.get("fiscal_period"),
            "eps_estimate": ev.get("eps_estimate"),
            "eps_actual": ev.get("eps_actual"),
            "revenue_estimate": ev.get("revenue_estimate"),
            "revenue_actual": ev.get("revenue_actual"),
            "source": ev.get("source", "yfinance"),
        })

    insert_fn = get_insert_statement_producer(session)
    statement = insert_fn(EarningsEvent).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "event_date", "source"],
        set_={
            "fiscal_period": statement.excluded.fiscal_period,
            "eps_estimate": statement.excluded.eps_estimate,
            "revenue_estimate": statement.excluded.revenue_estimate,
        },
    )
    session.execute(statement)
    return len(values)


def refresh_earnings() -> dict[str, object]:
    """Refresh upcoming earnings dates from yfinance for active companies."""
    job_id = _create_job_run()
    rows_read = 0
    rows_written = 0
    failed_symbols: list[str] = []
    status = "success"
    error_text: str | None = None

    try:
        with session_scope() as session:
            companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
            for company in companies:
                try:
                    ticker = yf.Ticker(company.symbol)
                    calendar = execute_provider_request(
                        session,
                        "yfinance",
                        lambda: ticker.calendar,
                    )
                    
                    if not calendar or not isinstance(calendar, dict):
                        logger.debug("No calendar data returned for %s", company.symbol)
                        continue

                    earnings_dates = calendar.get("Earnings Date")
                    if not earnings_dates:
                        continue

                    # Handle single date or list of dates safely
                    if not isinstance(earnings_dates, (list, tuple, set)):
                        dates_list = [earnings_dates]
                    else:
                        dates_list = list(earnings_dates)

                    events = []
                    for d in dates_list:
                        if isinstance(d, datetime):
                            d = d.date()
                        if isinstance(d, date):
                            events.append({
                                "event_date": d,
                                "eps_estimate": calendar.get("Earnings Average"),
                                "revenue_estimate": calendar.get("Revenue Average"),
                                "source": "yfinance",
                            })

                    if events:
                        rows_read += len(events)
                        rows_written += _upsert_earnings_event_rows(session, company.id, events)

                except Exception as exc:
                    logger.warning("Failed to fetch earnings for %s: %s", company.symbol, exc)
                    failed_symbols.append(company.symbol)
                    continue

            if failed_symbols:
                status = "partial_success"
                logger.warning("Earnings refresh failed for symbols: %s", ",".join(failed_symbols))
                
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Earnings refresh pipeline failed")
    finally:
        _finish_job_run(
            job_id,
            status=status,
            rows_read=rows_read,
            rows_written=rows_written,
            failed_symbols=failed_symbols,
            error_text=error_text,
        )

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "failed_symbols": failed_symbols,
        "error_text": error_text,
    }
