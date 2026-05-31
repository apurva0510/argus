from __future__ import annotations

from datetime import UTC, datetime
import logging

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from argus.core.db import session_scope
from argus.core.models import Company, JobRun, PriceBar
from argus.sources.factory import get_market_data_provider

def fetch_daily_ohlcv(symbol: str, period: str = "2y") -> pd.DataFrame:
    provider = get_market_data_provider()
    return provider.fetch_daily_ohlcv(symbol, period)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _create_job_run() -> int:
    with session_scope() as session:
        job = JobRun(job_name="refresh_prices", started_at=_utc_now(), status="running")
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
            job = JobRun(id=job_id, job_name="refresh_prices", started_at=_utc_now(), status=status)
            session.add(job)

        job.finished_at = _utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        if error_text:
            job.error_text = error_text
        elif failed_symbols:
            job.error_text = f"Failed symbols: {', '.join(sorted(failed_symbols))}"


def _upsert_price_bar_rows(session, company_id: int, rows: list[dict], provider: str) -> int:
    if not rows:
        return 0

    values = []
    for row in rows:
        values.append(
            {
                "company_id": company_id,
                "date": row["date"],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "adj_close": row.get("adj_close") or row.get("close"),
                "volume": row.get("volume"),
                "provider": provider,
                "interval": "1d",
            }
        )

    statement = sqlite_insert(PriceBar).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "date", "provider", "interval"],
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "adj_close": statement.excluded.adj_close,
            "volume": statement.excluded.volume,
        },
    )
    session.execute(statement)
    return len(values)


def refresh_prices(period: str = "2y") -> dict[str, object]:
    """Refresh daily yfinance prices for active companies.

    ``rows_written`` is the number of rows submitted to the idempotent SQLite
    upsert. On reruns, existing rows may be updated rather than newly inserted.
    """
    job_id = _create_job_run()
    rows_written = 0
    rows_read = 0
    failed_symbols: list[str] = []
    status = "success"
    error_text: str | None = None

    provider = get_market_data_provider()

    try:
        with session_scope() as session:
            companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
            for company in companies:
                try:
                    frame = fetch_daily_ohlcv(company.symbol, period=period)
                except Exception:
                    logger.exception("Failed to fetch prices for %s", company.symbol)
                    failed_symbols.append(company.symbol)
                    continue

                if frame.empty:
                    logger.warning("No price data returned for %s", company.symbol)
                    failed_symbols.append(company.symbol)
                    continue

                records = frame.to_dict(orient="records")
                rows_read += len(records)
                rows_written += _upsert_price_bar_rows(session, company.id, records, provider.name)

            if failed_symbols:
                status = "partial_success"
                logger.warning("Price refresh failed for symbols: %s", ",".join(failed_symbols))
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Price refresh failed")
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
