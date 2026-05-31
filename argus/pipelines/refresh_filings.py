from __future__ import annotations

import logging
from datetime import UTC, datetime
from sqlalchemy import select
from argus.core.db import session_scope, get_insert_statement_producer
from argus.core.models import Company, JobRun, SecFiling
from argus.core.settings import settings
from argus.sources.sec_client import fetch_filings

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _create_job_run() -> int:
    with session_scope() as session:
        job = JobRun(job_name="refresh_filings", started_at=_utc_now(), status="running")
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
            job = JobRun(id=job_id, job_name="refresh_filings", started_at=_utc_now(), status=status)
            session.add(job)

        job.finished_at = _utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        if error_text:
            job.error_text = error_text
        elif failed_symbols:
            job.error_text = f"Failed symbols: {', '.join(sorted(failed_symbols))}"


def _upsert_filing_rows(session, company_id: int, filings: list[dict]) -> int:
    if not filings:
        return 0

    values = []
    for f in filings:
        values.append({
            "company_id": company_id,
            "accession_no": f["accession_no"],
            "form": f["form"],
            "filing_date": f["filing_date"],
            "acceptance_datetime": f["acceptance_datetime"],
            "primary_doc_url": f["primary_doc_url"],
            "filing_detail_url": f["filing_detail_url"],
            "is_new": True,
        })

    insert_fn = get_insert_statement_producer(session)
    statement = insert_fn(SecFiling).values(values)
    # We update metadata on conflict, but do not overwrite is_new so we don't
    # mark already-read filings back to "new" on subsequent runs.
    statement = statement.on_conflict_do_update(
        index_elements=["accession_no"],
        set_={
            "form": statement.excluded.form,
            "filing_date": statement.excluded.filing_date,
            "acceptance_datetime": statement.excluded.acceptance_datetime,
            "primary_doc_url": statement.excluded.primary_doc_url,
            "filing_detail_url": statement.excluded.filing_detail_url,
        },
    )
    session.execute(statement)
    return len(values)


def refresh_filings() -> dict[str, object]:
    """Refresh SEC EDGAR filings for all active companies.

    This function coordinates fetching, filtering, and inserting filings.
    It registers a JobRun and reports status.
    """
    job_id = _create_job_run()
    rows_written = 0
    rows_read = 0
    failed_symbols: list[str] = []
    status = "success"
    error_text: str | None = None

    # Check settings first
    user_agent = settings.sec_user_agent
    if not user_agent or not user_agent.strip():
        error_msg = "SEC_USER_AGENT is not configured. Ingestion aborted."
        logger.error(error_msg)
        _finish_job_run(
            job_id,
            status="failed",
            rows_read=0,
            rows_written=0,
            failed_symbols=[],
            error_text=error_msg,
        )
        return {
            "status": "failed",
            "rows_read": 0,
            "rows_written": 0,
            "failed_symbols": [],
            "error_text": error_msg,
        }

    try:
        with session_scope() as session:
            companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
            for company in companies:
                if not company.cik:
                    logger.debug("Skipping filing refresh for %s: CIK not configured.", company.symbol)
                    continue

                try:
                    filings = fetch_filings(company.cik)
                except Exception:
                    logger.exception("Failed to fetch filings for %s", company.symbol)
                    failed_symbols.append(company.symbol)
                    continue

                rows_read += len(filings)
                if filings:
                    rows_written += _upsert_filing_rows(session, company.id, filings)

            if failed_symbols:
                status = "partial_success"
                logger.warning("Filing refresh failed for symbols: %s", ",".join(failed_symbols))
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Filing refresh failed")
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
