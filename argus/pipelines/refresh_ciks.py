from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from argus.core.db import session_scope
from argus.core.models import Company, JobRun
from argus.sources.sec_client import fetch_ticker_identities, sec_identity_matches_company

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def refresh_ciks() -> dict[str, object]:
    """Synchronize active-company CIKs from the official SEC ticker mapping."""
    with session_scope() as session:
        job = JobRun(job_name="refresh_ciks", started_at=_utc_now(), status="running")
        session.add(job)
        session.flush()
        job_id = job.id

    rows_read = 0
    rows_written = 0
    missing_symbols: list[str] = []
    identity_conflicts: list[str] = []
    updated_symbols: list[str] = []
    status = "success"
    error_text: str | None = None

    try:
        identities = fetch_ticker_identities()
        rows_read = len(identities)
        with session_scope() as session:
            companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
            for company in companies:
                identity = identities.get(company.symbol.strip().upper())
                if identity is None:
                    missing_symbols.append(company.symbol)
                    continue
                if company.cik == identity.cik:
                    continue
                if not sec_identity_matches_company(identity, company.name):
                    identity_conflicts.append(company.symbol)
                    logger.error(
                        "Refusing SEC CIK change for %s: configured name %r conflicts with SEC issuer %r",
                        company.symbol,
                        company.name,
                        identity.name,
                    )
                    continue
                if company.cik != identity.cik:
                    company.cik = identity.cik
                    updated_symbols.append(company.symbol)
                    rows_written += 1
            if identity_conflicts:
                status = "partial_success"
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("SEC ticker-to-CIK synchronization failed")
    finally:
        if error_text is None:
            details = []
            if missing_symbols:
                details.append(f"Unmatched active symbols: {', '.join(sorted(missing_symbols))}")
            if identity_conflicts:
                details.append(
                    f"Identity conflicts: {', '.join(sorted(identity_conflicts))}"
                )
            error_text = "; ".join(details) or None
        with session_scope() as session:
            job = session.get(JobRun, job_id)
            if job is not None:
                job.finished_at = _utc_now()
                job.status = status
                job.rows_read = rows_read
                job.rows_written = rows_written
                job.error_text = error_text

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "updated_symbols": updated_symbols,
        "missing_symbols": missing_symbols,
        "identity_conflicts": identity_conflicts,
        "error_text": error_text,
    }
