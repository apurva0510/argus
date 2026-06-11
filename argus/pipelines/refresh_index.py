from __future__ import annotations

import logging
from datetime import UTC, datetime
from sqlalchemy import delete

from argus.core.db import session_scope
from argus.core.models import Company, IndexDefinition, IndexValue, PriceBar
from argus.pipelines.job_runs import create_job_run, finish_job_run
from argus.core.settings import settings
from argus.analytics.index_builder import (
    calculate_weighted_index,
    ensure_default_index_definition,
    get_index_weights,
    list_index_definitions,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def refresh_index(index_definition_id: int | None = None) -> dict[str, object]:
    """Calculate an index definition's values and persist them to the database."""
    job_id = create_job_run("refresh_index")

    rows_read = 0
    rows_written = 0
    status = "success"
    error_text = None

    try:
        with session_scope() as session:
            default_definition = ensure_default_index_definition(session)
            definition = (
                session.get(IndexDefinition, index_definition_id)
                if index_definition_id is not None
                else default_definition
            )
            if definition is None:
                raise ValueError(f"index definition {index_definition_id} not found")

            weights = get_index_weights(session, definition.id)
            symbols = list(weights)
            if symbols:
                rows_read = (
                    session.query(PriceBar)
                    .join(Company, Company.id == PriceBar.company_id)
                    .filter(
                        Company.symbol.in_(symbols),
                        PriceBar.provider == settings.market_data_provider,
                        PriceBar.interval == "1d",
                    )
                    .count()
                )

            # 1. Calculate weighted index using historical price bars
            df = calculate_weighted_index(
                session,
                definition_id=definition.id,
                use_precomputed=False,
            )
            if not df.empty:
                # 2. Clear this definition's values to support historical updates/splits
                session.execute(
                    delete(IndexValue).where(IndexValue.index_definition_id == definition.id)
                )

                # 3. Batch insert the new calculated time series
                values = [
                    {
                        "index_definition_id": definition.id,
                        "date": row["date"],
                        "index_value": float(row["index_value"]),
                    }
                    for _, row in df.iterrows()
                ]

                if values:
                    session.execute(IndexValue.__table__.insert(), values)
                    rows_written = len(values)

            logger.info(
                "Successfully refreshed %d index value rows for %s",
                rows_written,
                definition.name,
            )

    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Core Index calculation and refresh pipeline failed")
    finally:
        finish_job_run(
            job_id,
            "refresh_index",
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


def refresh_all_indexes() -> dict[str, object]:
    """Refresh every active index definition."""
    with session_scope() as session:
        definitions = list_index_definitions(session)
        definition_ids = [definition.id for definition in definitions]

    results = [refresh_index(index_definition_id=definition_id) for definition_id in definition_ids]
    failed = [result for result in results if result["status"] != "success"]
    return {
        "status": "failed" if failed else "success",
        "definitions": len(results),
        "rows_read": sum(int(result["rows_read"] or 0) for result in results),
        "rows_written": sum(int(result["rows_written"] or 0) for result in results),
        "error_text": "; ".join(
            str(result["error_text"]) for result in failed if result["error_text"]
        )
        or None,
        "results": results,
    }
