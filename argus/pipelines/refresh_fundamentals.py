from __future__ import annotations

import logging
from sqlalchemy import select
import yfinance as yf

from argus.core.db import session_scope, get_insert_statement_producer
from argus.core.models import Company, FundamentalsSnapshot
from argus.pipelines.job_runs import create_job_run, finish_job_run, utc_now
from argus.pipelines.provider_health import execute_provider_request

logger = logging.getLogger(__name__)


def _upsert_fundamentals_snapshot(session, company_id: int, snapshot: dict) -> int:
    insert_fn = get_insert_statement_producer(session)
    statement = insert_fn(FundamentalsSnapshot).values(snapshot)
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "as_of_date", "provider"],
        set_={
            "market_cap": statement.excluded.market_cap,
            "enterprise_value": statement.excluded.enterprise_value,
            "trailing_pe": statement.excluded.trailing_pe,
            "forward_pe": statement.excluded.forward_pe,
            "price_to_sales": statement.excluded.price_to_sales,
            "ev_to_sales": statement.excluded.ev_to_sales,
            "ev_to_ebitda": statement.excluded.ev_to_ebitda,
            "revenue_growth": statement.excluded.revenue_growth,
            "gross_margin": statement.excluded.gross_margin,
            "operating_margin": statement.excluded.operating_margin,
            "free_cash_flow": statement.excluded.free_cash_flow,
        },
    )
    session.execute(statement)
    return 1


def refresh_fundamentals() -> dict[str, object]:
    """Refresh company key fundamentals metrics from yfinance for active companies."""
    job_id = create_job_run("refresh_fundamentals")
    rows_read = 0
    rows_written = 0
    failed_symbols: list[str] = []
    status = "success"
    error_text: str | None = None
    today = utc_now().date()

    try:
        with session_scope() as session:
            companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
            for company in companies:
                try:
                    ticker = yf.Ticker(company.symbol)
                    info = execute_provider_request(
                        session,
                        "yfinance",
                        lambda: ticker.info,
                    )

                    if not info or not isinstance(info, dict):
                        logger.debug("No info data returned for %s", company.symbol)
                        continue

                    snapshot = {
                        "company_id": company.id,
                        "as_of_date": today,
                        "market_cap": info.get("marketCap"),
                        "enterprise_value": info.get("enterpriseValue"),
                        "trailing_pe": info.get("trailingPE"),
                        "forward_pe": info.get("forwardPE"),
                        "price_to_sales": info.get("priceToSalesTrailing12Months"),
                        "ev_to_sales": info.get("enterpriseToRevenue"),
                        "ev_to_ebitda": info.get("enterpriseToEbitda"),
                        "revenue_growth": info.get("revenueGrowth"),
                        "gross_margin": info.get("grossMargins"),
                        "operating_margin": info.get("operatingMargins"),
                        "free_cash_flow": info.get("freeCashflow"),
                        "provider": "yfinance",
                    }

                    rows_read += 1
                    rows_written += _upsert_fundamentals_snapshot(session, company.id, snapshot)

                except Exception as exc:
                    logger.warning("Failed to fetch fundamentals for %s: %s", company.symbol, exc)
                    failed_symbols.append(company.symbol)
                    continue

            if failed_symbols:
                status = "partial_success"
                logger.warning(
                    "Fundamentals refresh failed for symbols: %s", ",".join(failed_symbols)
                )

    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Fundamentals refresh pipeline failed")
    finally:
        finish_job_run(
            job_id,
            "refresh_fundamentals",
            status=status,
            rows_read=rows_read,
            rows_written=rows_written,
            error_text=error_text
            or (
                f"Failed symbols: {', '.join(sorted(failed_symbols))}"
                if failed_symbols
                else None
            ),
        )

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "failed_symbols": failed_symbols,
        "error_text": error_text,
    }
