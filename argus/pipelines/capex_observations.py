from __future__ import annotations

from datetime import date

from argus.core.db import get_insert_statement_producer, session_scope
from argus.core.models import CapexObservation, Company


def upsert_capex_observation(
    *,
    ticker: str,
    fiscal_period_end: date,
    capex_amount: float,
    currency: str = "USD",
    source_label: str | None = None,
    source_url: str | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Ticker is required")
    if capex_amount < 0:
        raise ValueError("Capex amount must be non-negative")

    with session_scope() as session:
        company = session.query(Company).filter(Company.symbol == symbol).one_or_none()
        if company is None:
            raise ValueError(f"Unknown ticker: {symbol}")

        insert_fn = get_insert_statement_producer(session)
        statement = insert_fn(CapexObservation).values(
            {
                "company_id": company.id,
                "fiscal_period_end": fiscal_period_end,
                "capex_amount": capex_amount,
                "currency": currency.strip().upper() or "USD",
                "source_label": source_label,
                "source_url": source_url,
                "notes": notes,
            }
        )
        statement = statement.on_conflict_do_update(
            index_elements=["company_id", "fiscal_period_end"],
            set_={
                "capex_amount": statement.excluded.capex_amount,
                "currency": statement.excluded.currency,
                "source_label": statement.excluded.source_label,
                "source_url": statement.excluded.source_url,
                "notes": statement.excluded.notes,
            },
        )
        session.execute(statement)
        return {
            "status": "success",
            "ticker": symbol,
            "fiscal_period_end": fiscal_period_end,
            "capex_amount": capex_amount,
        }
