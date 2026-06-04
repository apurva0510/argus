from __future__ import annotations

import logging
from datetime import UTC, datetime
from sqlalchemy import select
from argus.core.db import session_scope, get_insert_statement_producer
from argus.core.models import Company, JobRun, SecFiling
from argus.core.settings import settings
from argus.sources.sec_client import (
    SecSubmissionNotFoundError,
    fetch_filings,
    fetch_ticker_identities,
    sec_identity_matches_company,
)
from argus.pipelines.provider_health import execute_provider_request

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

    accession_numbers = [filing["accession_no"] for filing in filings]
    existing = set(
        session.scalars(
            select(SecFiling.accession_no).where(
                SecFiling.accession_no.in_(accession_numbers)
            )
        ).all()
    )
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
    return len(set(accession_numbers) - existing)


def _persist_company_filings(company_id: int, cik: str, filings: list[dict]) -> int:
    with session_scope() as session:
        company = session.get(Company, company_id)
        if company is None:
            raise RuntimeError(f"Company {company_id} no longer exists")
        company.cik = cik
        return _upsert_filing_rows(session, company_id, filings)


def refresh_filings() -> dict[str, object]:
    """Refresh SEC EDGAR filings for all active companies.

    This function coordinates fetching, filtering, and inserting filings.
    It registers a JobRun and reports status.
    """
    job_id = _create_job_run()
    rows_written = 0
    rows_read = 0
    failed_symbols: list[str] = []
    operational_failed_symbols: list[str] = []
    not_found_symbols: list[str] = []
    missing_cik_symbols: list[str] = []
    identity_conflicts: list[str] = []
    remapped_symbols: list[str] = []
    successful_symbols: list[str] = []
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
            "operational_failed_symbols": [],
            "not_found_symbols": [],
            "missing_cik_symbols": [],
            "identity_conflicts": [],
            "remapped_symbols": [],
            "error_text": error_msg,
        }

    try:
        with session_scope() as session:
            companies = [
                {
                    "id": company.id,
                    "symbol": company.symbol,
                    "name": company.name,
                    "cik": company.cik,
                }
                for company in session.scalars(
                    select(Company).where(Company.is_active.is_(True))
                ).all()
            ]
        ticker_identities = None
        for company in companies:
            symbol = str(company["symbol"])
            company_cik = company["cik"]
            if not company_cik:
                logger.warning("Skipping filing refresh for %s: CIK not configured.", symbol)
                missing_cik_symbols.append(symbol)
                continue

            try:
                with session_scope() as req_session:
                    filings = execute_provider_request(
                        req_session,
                        "sec",
                        fetch_filings,
                        company_cik,
                    )
            except SecSubmissionNotFoundError:
                not_found_symbols.append(symbol)
                if ticker_identities is None:
                    try:
                        with session_scope() as req_session:
                            ticker_identities = execute_provider_request(
                                req_session,
                                "sec",
                                fetch_ticker_identities,
                            )
                    except Exception:
                        logger.exception(
                            "Failed to refresh SEC ticker mapping after 404 for %s",
                            symbol,
                        )
                        failed_symbols.append(symbol)
                        continue

                identity = ticker_identities.get(symbol.strip().upper())
                if identity is None or identity.cik == company_cik:
                    logger.error(
                        "SEC submissions remain unavailable for %s with CIK %s",
                        symbol,
                        company_cik,
                    )
                    failed_symbols.append(symbol)
                    continue
                if not sec_identity_matches_company(identity, str(company["name"])):
                    logger.error(
                        "Refusing SEC CIK remap for %s because SEC issuer %r conflicts with %r",
                        symbol,
                        identity.name,
                        company["name"],
                    )
                    failed_symbols.append(symbol)
                    identity_conflicts.append(symbol)
                    continue

                old_cik = company_cik
                company_cik = identity.cik
                remapped_symbols.append(symbol)
                logger.warning(
                    "Retrying SEC filings for %s after remapping CIK %s to %s",
                    symbol,
                    old_cik,
                    company_cik,
                )
                try:
                    with session_scope() as req_session:
                        filings = execute_provider_request(
                            req_session,
                            "sec",
                            fetch_filings,
                            company_cik,
                        )
                except SecSubmissionNotFoundError:
                    logger.error(
                        "SEC submissions remain unavailable for %s after remapping to CIK %s",
                        symbol,
                        company_cik,
                    )
                    failed_symbols.append(symbol)
                    continue
                except Exception:
                    logger.exception("Failed to fetch filings for %s after CIK remap", symbol)
                    failed_symbols.append(symbol)
                    operational_failed_symbols.append(symbol)
                    continue
            except Exception:
                logger.exception("Failed to fetch filings for %s", symbol)
                failed_symbols.append(symbol)
                operational_failed_symbols.append(symbol)
                continue

            rows_read += len(filings)
            rows_written += _persist_company_filings(int(company["id"]), str(company_cik), filings)
            successful_symbols.append(symbol)

        if not_found_symbols:
            status = "partial_success"
        elif operational_failed_symbols and not successful_symbols:
            status = "failed"
        elif operational_failed_symbols or missing_cik_symbols:
            status = "partial_success"
        if failed_symbols or missing_cik_symbols:
            logger.warning(
                "Filing refresh incomplete for symbols: %s",
                ",".join(failed_symbols + missing_cik_symbols),
            )
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Filing refresh failed")
    finally:
        if error_text is None:
            details = []
            if failed_symbols:
                details.append(f"Failed symbols: {', '.join(sorted(failed_symbols))}")
            if not_found_symbols:
                details.append(
                    f"SEC submission 404s: {', '.join(sorted(not_found_symbols))}"
                )
            if missing_cik_symbols:
                details.append(f"Missing CIKs: {', '.join(sorted(missing_cik_symbols))}")
            error_text = "; ".join(details) or None
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
        "operational_failed_symbols": operational_failed_symbols,
        "not_found_symbols": not_found_symbols,
        "missing_cik_symbols": missing_cik_symbols,
        "identity_conflicts": identity_conflicts,
        "remapped_symbols": remapped_symbols,
        "error_text": error_text,
    }
