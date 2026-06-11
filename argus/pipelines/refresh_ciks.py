from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from argus.core.db import session_scope
from argus.core.models import Company
from argus.pipelines.job_runs import job_run_context
from argus.sources.sec_client import fetch_ticker_identities, sec_identity_matches_company

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def refresh_ciks() -> dict[str, object]:
    """Synchronize active-company CIKs from the official SEC ticker mapping."""
    missing_symbols: list[str] = []
    identity_conflicts: list[str] = []
    updated_symbols: list[str] = []

    with job_run_context("refresh_ciks") as state:
        identities = fetch_ticker_identities()
        if not isinstance(identities, dict):
            raise TypeError(f"SEC ticker identities mapping is not a dictionary: got {type(identities)}")
        if not identities:
            raise ValueError("SEC ticker identities mapping is empty")

        state.rows_read = len(identities)
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
                    state.rows_written += 1
            if identity_conflicts:
                state.status = "partial_success"

        if state.error_text is None:
            details = []
            if missing_symbols:
                details.append(f"Unmatched active symbols: {', '.join(sorted(missing_symbols))}")
            if identity_conflicts:
                details.append(f"Identity conflicts: {', '.join(sorted(identity_conflicts))}")
            state.error_text = "; ".join(details) or None

    return {
        "status": state.status,
        "rows_read": state.rows_read,
        "rows_written": state.rows_written,
        "updated_symbols": updated_symbols,
        "missing_symbols": missing_symbols,
        "identity_conflicts": identity_conflicts,
        "error_text": state.error_text,
    }
