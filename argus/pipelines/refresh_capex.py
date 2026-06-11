from __future__ import annotations

import logging

from sqlalchemy import select

from argus.core.db import get_insert_statement_producer, session_scope
from argus.core.models import CapexObservation, Company
from argus.pipelines.job_runs import create_job_run, finish_job_run
from argus.pipelines.provider_health import execute_provider_request
from argus.sources.sec_client import fetch_company_facts, parse_capex_facts

logger = logging.getLogger(__name__)

HYPERSCALER_SYMBOLS = ("MSFT", "AMZN", "GOOGL", "META")


def refresh_capex() -> dict[str, object]:
    """Ingest capex observations from SEC CompanyFacts for hyperscaler companies.

    Automated observations use source='sec_companyfacts'.
    Manually entered observations (source='manual') are never overwritten.
    """
    job_id = create_job_run("refresh_capex")
    rows_read = 0
    rows_written = 0
    status = "success"
    error_text: str | None = None
    failed_symbols: list[str] = []

    try:
        with session_scope() as session:
            companies = (
                session.execute(
                    select(Company).where(
                        Company.symbol.in_(HYPERSCALER_SYMBOLS),
                        Company.is_active.is_(True),
                    )
                )
                .scalars()
                .all()
            )

            for company in companies:
                if not company.cik:
                    logger.warning(
                        "Skipping capex ingestion for %s: no CIK configured",
                        company.symbol,
                    )
                    failed_symbols.append(company.symbol)
                    continue

                try:
                    facts = execute_provider_request(
                        session,
                        "sec",
                        fetch_company_facts,
                        company.cik,
                    )
                    capex_entries = parse_capex_facts(facts)
                    rows_read += len(capex_entries)

                    for entry in capex_entries:
                        # Check if a manual observation exists for this period
                        existing = (
                            session.query(CapexObservation)
                            .filter(
                                CapexObservation.company_id == company.id,
                                CapexObservation.fiscal_period_end == entry["fiscal_period_end"],
                                CapexObservation.source == "manual",
                            )
                            .one_or_none()
                        )
                        if existing is not None:
                            logger.debug(
                                "Skipping SEC capex for %s %s: manual observation exists",
                                company.symbol,
                                entry["fiscal_period_end"],
                            )
                            continue

                        insert_fn = get_insert_statement_producer(session)
                        stmt = insert_fn(CapexObservation).values(
                            {
                                "company_id": company.id,
                                "fiscal_period_end": entry["fiscal_period_end"],
                                "capex_amount": entry["capex_amount"],
                                "currency": "USD",
                                "source_label": f"SEC CompanyFacts ({entry['form']})",
                                "source_url": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company.cik}.json",
                                "source": "sec_companyfacts",
                            }
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["company_id", "fiscal_period_end"],
                            set_={
                                "capex_amount": stmt.excluded.capex_amount,
                                "source_label": stmt.excluded.source_label,
                                "source_url": stmt.excluded.source_url,
                                "source": stmt.excluded.source,
                            },
                        )
                        session.execute(stmt)
                        rows_written += 1

                    logger.info(
                        "Ingested %d capex observations for %s",
                        len(capex_entries),
                        company.symbol,
                    )

                except Exception as exc:
                    logger.warning(
                        "Failed capex ingestion for %s: %s",
                        company.symbol,
                        exc,
                    )
                    failed_symbols.append(company.symbol)

        if failed_symbols:
            status = "partial_success" if rows_written else "failed"
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Capex refresh pipeline failed")
    finally:
        if error_text is None and failed_symbols:
            error_text = f"Failed symbols: {', '.join(sorted(failed_symbols))}"
        finish_job_run(
            job_id,
            "refresh_capex",
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
