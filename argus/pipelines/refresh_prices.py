from __future__ import annotations

from datetime import UTC, datetime, time
import logging

import pandas as pd
from sqlalchemy import select
from argus.core.db import session_scope, get_insert_statement_producer
from argus.core.models import Company, JobRun, PriceBar
from argus.sources.factory import get_market_data_provider
from argus.sources.yfinance_client import YFinanceProvider
from argus.pipelines.provider_health import execute_provider_request


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


def _row_bar_time(row: dict) -> datetime:
    if row.get("bar_time") is not None:
        value = pd.Timestamp(row["bar_time"]).to_pydatetime()
        return value.replace(tzinfo=None)
    return datetime.combine(row["date"], time.min)


def _upsert_price_bar_rows(
    session,
    company_id: int,
    rows: list[dict],
    provider: str,
    *,
    interval: str,
) -> int:
    if not rows:
        return 0

    values = []
    for row in rows:
        bar_time = _row_bar_time(row)
        values.append(
            {
                "company_id": company_id,
                "date": row["date"],
                "bar_time": bar_time,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "adj_close": row.get("adj_close") or row.get("close"),
                "volume": row.get("volume"),
                "provider": provider,
                "interval": interval,
            }
        )

    statement = get_insert_statement_producer(session)(PriceBar).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "bar_time", "provider", "interval"],
        set_={
            "date": statement.excluded.date,
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


def _default_period_for_interval(interval: str) -> str:
    return "5d" if interval == "15m" else "2y"


def _validate_period_for_interval(period: str, interval: str) -> None:
    if interval != "15m":
        return
    if not period.endswith("d"):
        raise ValueError("15m refreshes must use a short day-based period, such as '5d'")
    try:
        days = int(period[:-1])
    except ValueError as exc:
        raise ValueError("15m refresh period must be a day count, such as '5d'") from exc
    if days < 1 or days > 60:
        raise ValueError("15m refresh period must be between 1d and 60d")


def refresh_prices(period: str | None = None, *, interval: str = "1d") -> dict[str, object]:
    """Refresh yfinance prices for active companies.

    ``rows_written`` is the number of rows submitted to the idempotent SQLite
    upsert. On reruns, existing rows may be updated rather than newly inserted.
    """
    interval = interval.strip().lower()
    if interval not in {"1d", "15m"}:
        raise ValueError("refresh_prices supports interval='1d' or interval='15m'")
    period = period or _default_period_for_interval(interval)
    _validate_period_for_interval(period, interval)
    job_id = _create_job_run()
    rows_written = 0
    rows_read = 0
    failed_symbols: list[str] = []
    status = "success"
    error_text: str | None = None

    provider = get_market_data_provider()
    if interval == "15m" and not hasattr(provider, "fetch_ohlcv_batch"):
        logger.warning(
            "Provider '%s' does not support intraday batch fetching. Falling back to yfinance.",
            provider.name,
        )
        provider = YFinanceProvider()

    try:
        with session_scope() as session:
            companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
            if interval == "15m":
                symbols = [company.symbol for company in companies]
                try:
                    frames_by_symbol = execute_provider_request(
                        session,
                        provider.name,
                        provider.fetch_ohlcv_batch,
                        symbols,
                        period=period,
                        interval=interval,
                    )
                except Exception as exc:
                    failed_symbols = symbols
                    raise RuntimeError(f"batched yfinance refresh failed: {exc}") from exc

                companies_by_symbol = {company.symbol: company for company in companies}
                for symbol in symbols:
                    frame = frames_by_symbol.get(symbol, pd.DataFrame())
                    if frame.empty:
                        logger.warning("No price data returned for %s", symbol)
                        failed_symbols.append(symbol)
                        continue

                    records = frame.to_dict(orient="records")
                    rows_read += len(records)
                    rows_written += _upsert_price_bar_rows(
                        session,
                        companies_by_symbol[symbol].id,
                        records,
                        provider.name,
                        interval=interval,
                    )

                if failed_symbols:
                    status = "partial_success"
                    logger.warning("Price refresh failed for symbols: %s", ",".join(failed_symbols))
                return {
                    "status": status,
                    "rows_read": rows_read,
                    "rows_written": rows_written,
                    "failed_symbols": failed_symbols,
                    "error_text": error_text,
                }

            for company in companies:
                try:
                    frame = execute_provider_request(
                        session,
                        provider.name,
                        fetch_daily_ohlcv,
                        company.symbol,
                        period=period,
                    )
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
                rows_written += _upsert_price_bar_rows(
                    session,
                    company.id,
                    records,
                    provider.name,
                    interval="1d",
                )

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
