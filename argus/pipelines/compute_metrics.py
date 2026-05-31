from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sqlalchemy import inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from argus.analytics.indicators import (
    annualized_volatility,
    compute_return,
    compute_rsi,
    compute_ytd_return,
    distance_from_ma,
    drawdown_from_rolling_high,
    moving_average,
    rolling_high,
    rolling_low,
)
from argus.analytics.relative_strength import relative_return
from argus.core.db import session_scope
from argus.core.models import Company, DailyMetric, JobRun, PriceBar, utc_now
from argus.core.settings import settings

logger = logging.getLogger(__name__)

METRIC_COLUMNS = [
    "return_1d",
    "return_1w",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_ytd",
    "ma_50",
    "ma_200",
    "rsi_14",
    "high_52w",
    "low_52w",
    "drawdown_52w",
    "distance_from_50dma",
    "distance_from_200dma",
    "relative_return_vs_qqq_1m",
    "relative_return_vs_qqq_3m",
    "relative_return_vs_nvda_1m",
    "relative_return_vs_nvda_3m",
    "volatility_20d",
]


def _create_job_run() -> int:
    with session_scope() as session:
        job = JobRun(job_name="compute_daily_metrics", started_at=utc_now(), status="running")
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
            job = JobRun(
                id=job_id,
                job_name="compute_daily_metrics",
                started_at=utc_now(),
                status=status,
            )
            session.add(job)

        job.finished_at = utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        if error_text:
            job.error_text = error_text
        elif failed_symbols:
            job.error_text = f"Failed symbols: {', '.join(sorted(failed_symbols))}"


def _load_price_frame(session, company_id: int) -> pd.DataFrame:
    rows = (
        session.query(PriceBar.date, PriceBar.adj_close)
        .filter(
            PriceBar.company_id == company_id,
            PriceBar.provider == settings.market_data_provider,
            PriceBar.interval == "1d",
        )
        .order_by(PriceBar.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["date", "adj_close"])
    frame = pd.DataFrame(rows, columns=["date", "adj_close"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.dropna(subset=["adj_close"])
    return frame


def _compute_company_metrics(frame: pd.DataFrame, qqq: pd.Series | None, nvda: pd.Series | None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    series = frame.set_index("date")["adj_close"].astype(float).sort_index()
    ma_50 = moving_average(series, 50)
    ma_200 = moving_average(series, 200)

    metrics = pd.DataFrame(index=series.index)
    metrics["return_1d"] = compute_return(series, 1)
    metrics["return_1w"] = compute_return(series, 5)
    metrics["return_1m"] = compute_return(series, 21)
    metrics["return_3m"] = compute_return(series, 63)
    metrics["return_6m"] = compute_return(series, 126)
    metrics["return_ytd"] = compute_ytd_return(series)
    metrics["ma_50"] = ma_50
    metrics["ma_200"] = ma_200
    metrics["rsi_14"] = compute_rsi(series, 14)
    metrics["high_52w"] = rolling_high(series, 252)
    metrics["low_52w"] = rolling_low(series, 252)
    metrics["drawdown_52w"] = drawdown_from_rolling_high(series, 252)
    metrics["distance_from_50dma"] = distance_from_ma(series, ma_50)
    metrics["distance_from_200dma"] = distance_from_ma(series, ma_200)
    metrics["volatility_20d"] = annualized_volatility(series, window=20)

    if qqq is not None and not qqq.empty:
        metrics["relative_return_vs_qqq_1m"] = relative_return(series, qqq, 21)
        metrics["relative_return_vs_qqq_3m"] = relative_return(series, qqq, 63)
    else:
        metrics["relative_return_vs_qqq_1m"] = pd.NA
        metrics["relative_return_vs_qqq_3m"] = pd.NA

    if nvda is not None and not nvda.empty:
        metrics["relative_return_vs_nvda_1m"] = relative_return(series, nvda, 21)
        metrics["relative_return_vs_nvda_3m"] = relative_return(series, nvda, 63)
    else:
        metrics["relative_return_vs_nvda_1m"] = pd.NA
        metrics["relative_return_vs_nvda_3m"] = pd.NA

    metrics = metrics.reset_index().rename(columns={"index": "date"})
    return metrics


def _clean_metric_value(value):
    if value is pd.NA or value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _metric_date(value):
    if hasattr(value, "date"):
        return value.date()
    return value


def _metric_payload(row: dict) -> dict:
    return {key: _clean_metric_value(row.get(key)) for key in METRIC_COLUMNS}


def _upsert_daily_metrics(session, company_id: int, metrics_frame: pd.DataFrame) -> int:
    if metrics_frame.empty:
        return 0

    rows_written = 0
    for row in metrics_frame.to_dict(orient="records"):
        metric_date = _metric_date(row["date"])
        payload = _metric_payload(row)

        existing = (
            session.query(DailyMetric)
            .filter(DailyMetric.company_id == company_id, DailyMetric.date == metric_date)
            .one_or_none()
        )
        if existing is None:
            session.add(
                DailyMetric(
                    company_id=company_id,
                    date=metric_date,
                    **payload,
                )
            )
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
        rows_written += 1

    return rows_written


def _bulk_upsert_daily_metrics(session, company_id: int, metrics_frame: pd.DataFrame) -> int:
    if metrics_frame.empty:
        return 0

    rows = []
    for row in metrics_frame.to_dict(orient="records"):
        rows.append(
            {
                "company_id": company_id,
                "date": _metric_date(row["date"]),
                **_metric_payload(row),
            }
        )

    statement = sqlite_insert(DailyMetric).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "date"],
        set_={
            "return_1d": statement.excluded.return_1d,
            "return_1w": statement.excluded.return_1w,
            "return_1m": statement.excluded.return_1m,
            "return_3m": statement.excluded.return_3m,
            "return_6m": statement.excluded.return_6m,
            "return_ytd": statement.excluded.return_ytd,
            "ma_50": statement.excluded.ma_50,
            "ma_200": statement.excluded.ma_200,
            "rsi_14": statement.excluded.rsi_14,
            "high_52w": statement.excluded.high_52w,
            "low_52w": statement.excluded.low_52w,
            "drawdown_52w": statement.excluded.drawdown_52w,
            "distance_from_50dma": statement.excluded.distance_from_50dma,
            "distance_from_200dma": statement.excluded.distance_from_200dma,
            "relative_return_vs_qqq_1m": statement.excluded.relative_return_vs_qqq_1m,
            "relative_return_vs_qqq_3m": statement.excluded.relative_return_vs_qqq_3m,
            "relative_return_vs_nvda_1m": statement.excluded.relative_return_vs_nvda_1m,
            "relative_return_vs_nvda_3m": statement.excluded.relative_return_vs_nvda_3m,
            "volatility_20d": statement.excluded.volatility_20d,
        },
    )
    session.execute(statement)
    return len(rows)


def _supports_daily_metrics_unique_key(session) -> bool:
    inspector = inspect(session.get_bind())
    for constraint in inspector.get_unique_constraints("daily_metrics"):
        columns = constraint.get("column_names") or []
        if columns == ["company_id", "date"]:
            return True
    return False


def compute_daily_metrics() -> dict[str, object]:
    job_id = _create_job_run()
    rows_read = 0
    rows_written = 0
    failed_symbols: list[str] = []
    status = "success"
    error_text: str | None = None

    try:
        with session_scope() as session:
            company_rows = session.query(Company).filter(Company.is_active.is_(True)).all()
            company_by_symbol = {company.symbol: company for company in company_rows}

            qqq_series = None
            nvda_series = None
            if "QQQ" in company_by_symbol:
                qqq_df = _load_price_frame(session, company_by_symbol["QQQ"].id)
                if not qqq_df.empty:
                    qqq_series = qqq_df.set_index("date")["adj_close"].astype(float).sort_index()
            if "NVDA" in company_by_symbol:
                nvda_df = _load_price_frame(session, company_by_symbol["NVDA"].id)
                if not nvda_df.empty:
                    nvda_series = nvda_df.set_index("date")["adj_close"].astype(float).sort_index()

            if qqq_series is None:
                logger.warning("QQQ data missing; relative_return_vs_qqq_* metrics will be null.")
            if nvda_series is None:
                logger.warning("NVDA data missing; relative_return_vs_nvda_* metrics will be null.")

            use_bulk_upsert = _supports_daily_metrics_unique_key(session)
            if not use_bulk_upsert:
                logger.warning(
                    "daily_metrics unique key missing; falling back to row-level upsert."
                )

            for company in company_rows:
                try:
                    frame = _load_price_frame(session, company.id)
                    rows_read += len(frame)
                    metrics_frame = _compute_company_metrics(frame, qqq_series, nvda_series)
                    if use_bulk_upsert:
                        rows_written += _bulk_upsert_daily_metrics(session, company.id, metrics_frame)
                    else:
                        rows_written += _upsert_daily_metrics(session, company.id, metrics_frame)
                except Exception:
                    logger.exception("Failed computing metrics for %s", company.symbol)
                    failed_symbols.append(company.symbol)

            if failed_symbols:
                status = "partial_success"
                logger.warning("Metric computation failed for symbols: %s", ",".join(failed_symbols))
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Metric computation failed")
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
