from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from argus.core.db import session_scope
from argus.core.settings import settings
from argus.core.models import Company, DailyMetric, NewsItem, PriceBar, SecFiling, WatchlistItem
from argus.core.seed import AI_INFRA_CORE_INDEX_SYMBOLS

STALE_DAYS_THRESHOLD = 3
LOW_RSI_THRESHOLD = 40.0


def load_dashboard_data_from_engine(engine: Engine) -> dict[str, object]:
    with engine.connect() as conn:
        latest_dates = pd.read_sql_query(
            text(
                """
                SELECT
                    (SELECT MAX(date) FROM price_bars WHERE provider = :provider AND interval = '1d') AS latest_price_date,
                    (SELECT MAX(date) FROM daily_metrics) AS latest_metrics_date,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_prices') AS last_price_refresh_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'compute_daily_metrics') AS last_metrics_refresh_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_news') AS last_news_refresh_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_filings') AS last_filings_refresh_at
                """
            ),
            conn,
            params={"provider": settings.market_data_provider},
        )
        latest_metrics_date = latest_dates.at[0, "latest_metrics_date"]

        if latest_metrics_date is None or pd.isna(latest_metrics_date):
            latest_metrics = pd.DataFrame()
        else:
            latest_metrics = pd.read_sql_query(
                text(
                    """
                    SELECT
                        c.symbol,
                        c.name,
                        dm.date,
                        dm.return_1d,
                        dm.return_1w,
                        dm.return_1m,
                        dm.rsi_14,
                        dm.drawdown_52w
                    FROM daily_metrics dm
                    JOIN companies c ON c.id = dm.company_id
                    WHERE c.is_active = 1
                        AND dm.date = (
                            SELECT MAX(dm2.date)
                            FROM daily_metrics dm2
                            WHERE dm2.company_id = c.id
                        )
                    ORDER BY c.symbol
                    """
                ),
                conn,
            )

        active_symbol_count = pd.read_sql_query(
            text("SELECT COUNT(*) AS count FROM companies WHERE is_active = 1"),
            conn,
        ).at[0, "count"]
        news_count = pd.read_sql_query(text("SELECT COUNT(*) AS count FROM news_items"), conn).at[0, "count"]
        filings_count = pd.read_sql_query(text("SELECT COUNT(*) AS count FROM sec_filings"), conn).at[0, "count"]
        earnings_count = pd.read_sql_query(
            text("SELECT COUNT(*) AS count FROM earnings_events WHERE event_date >= DATE('now')"),
            conn,
        ).at[0, "count"]
        recent_news = pd.read_sql_query(
            text(
                """
                SELECT
                    ni.published_at,
                    ni.title,
                    ni.url,
                    ni.source_name,
                    ni.provider,
                    (
                        SELECT group_concat(DISTINCT nm2.ticker)
                        FROM news_mentions nm2
                        WHERE nm2.news_id = ni.id
                    ) AS tickers
                FROM news_items ni
                ORDER BY ni.published_at DESC
                LIMIT 5
                """
            ),
            conn,
        )
        recent_filings = pd.read_sql_query(
            text(
                """
                SELECT
                    sf.filing_date,
                    c.symbol,
                    c.name,
                    sf.form,
                    sf.filing_detail_url,
                    sf.primary_doc_url
                FROM sec_filings sf
                JOIN companies c ON c.id = sf.company_id
                ORDER BY sf.filing_date DESC, sf.acceptance_datetime DESC
                LIMIT 5
                """
            ),
            conn,
        )
        upcoming_earnings = pd.read_sql_query(
            text(
                """
                SELECT
                    ee.event_date,
                    c.symbol,
                    c.name,
                    ee.fiscal_period,
                    ee.source
                FROM earnings_events ee
                JOIN companies c ON c.id = ee.company_id
                WHERE ee.event_date >= DATE('now')
                ORDER BY ee.event_date ASC, c.symbol ASC
                LIMIT 5
                """
            ),
            conn,
        )

        # Calculate stale tickers count
        stale_threshold_str = f"-{STALE_DAYS_THRESHOLD} days"
        stale_tickers_count = pd.read_sql_query(
            text(
                """
                SELECT COUNT(DISTINCT symbol) AS count
                FROM companies
                WHERE is_active = 1 AND id NOT IN (
                    SELECT DISTINCT company_id
                    FROM price_bars
                    WHERE provider = :provider
                      AND date >= DATE('now', :stale_threshold)
                )
                """
            ),
            conn,
            params={
                "provider": settings.market_data_provider,
                "stale_threshold": stale_threshold_str,
            },
        ).at[0, "count"]

        # Fetch latest failed job
        failed_job_df = pd.read_sql_query(
            text(
                """
                SELECT job_name, finished_at, error_text
                FROM job_runs
                WHERE status = 'failed'
                ORDER BY id DESC LIMIT 1
                """
            ),
            conn,
        )
        failed_job = failed_job_df.iloc[0].to_dict() if not failed_job_df.empty else None

        provider_status = {
            "active_provider": settings.market_data_provider,
            "yfinance_available": True,
            "finnhub_available": bool(settings.finnhub_api_key),
            "twelvedata_available": bool(settings.twelve_data_api_key),
            "alphavantage_available": bool(settings.alpha_vantage_api_key),
        }

    return {
        "latest_dates": latest_dates.iloc[0].to_dict(),
        "latest_metrics": latest_metrics,
        "index_symbol_count": int(active_symbol_count),
        "news_count": int(news_count),
        "filings_count": int(filings_count),
        "earnings_count": int(earnings_count),
        "recent_news": recent_news,
        "recent_filings": recent_filings,
        "upcoming_earnings": upcoming_earnings,
        "stale_tickers_count": int(stale_tickers_count),
        "failed_job": failed_job,
        "provider_status": provider_status,
    }


def parse_optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    return pd.to_datetime(value).date()


def parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    dt = pd.to_datetime(value).to_pydatetime()
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def build_stale_reasons(
    latest_price_date: date | None,
    latest_metrics_date: date | None,
    *,
    today: date | None = None,
    stale_days_threshold: int = STALE_DAYS_THRESHOLD,
) -> list[str]:
    today = today or datetime.now(UTC).date()
    stale_reasons = []

    if latest_price_date is None:
        stale_reasons.append("No price data found.")
    elif (today - latest_price_date).days > stale_days_threshold:
        stale_reasons.append(f"Prices are stale (latest date: {latest_price_date.isoformat()}).")

    if latest_metrics_date is None:
        stale_reasons.append("No metrics data found.")
    elif (today - latest_metrics_date).days > stale_days_threshold:
        stale_reasons.append(f"Metrics are stale (latest date: {latest_metrics_date.isoformat()}).")

    return stale_reasons


def summarize_core_returns(metrics_df: pd.DataFrame) -> dict[str, float | None]:
    empty_summary = {"return_1d": None, "return_1w": None, "return_1m": None}
    if metrics_df.empty or "symbol" not in metrics_df:
        return empty_summary

    core_metrics = metrics_df[metrics_df["symbol"].isin(AI_INFRA_CORE_INDEX_SYMBOLS)]
    if core_metrics.empty:
        return empty_summary

    return {
        "return_1d": _mean_or_none(core_metrics, "return_1d"),
        "return_1w": _mean_or_none(core_metrics, "return_1w"),
        "return_1m": _mean_or_none(core_metrics, "return_1m"),
    }


def rank_top_gainers(metrics_df: pd.DataFrame, *, limit: int = 5) -> pd.DataFrame:
    return _rank_by_metric(metrics_df, "return_1d", limit=limit, ascending=False)


def rank_top_losers(metrics_df: pd.DataFrame, *, limit: int = 5) -> pd.DataFrame:
    return _rank_by_metric(metrics_df, "return_1d", limit=limit, ascending=True)


def rank_biggest_drawdowns(metrics_df: pd.DataFrame, *, limit: int = 5) -> pd.DataFrame:
    return _rank_by_metric(metrics_df, "drawdown_52w", limit=limit, ascending=True)


def filter_low_rsi(
    metrics_df: pd.DataFrame,
    *,
    threshold: float = LOW_RSI_THRESHOLD,
    limit: int = 10,
) -> pd.DataFrame:
    columns = ["symbol", "name", "rsi_14"]
    if metrics_df.empty or not set(columns).issubset(metrics_df.columns):
        return pd.DataFrame(columns=columns)

    rsi = metrics_df[columns].dropna(subset=["rsi_14"])
    return rsi[rsi["rsi_14"] < threshold].sort_values("rsi_14", ascending=True).head(limit)


def _rank_by_metric(metrics_df: pd.DataFrame, metric: str, *, limit: int, ascending: bool) -> pd.DataFrame:
    columns = ["symbol", "name", metric]
    if metrics_df.empty or not set(columns).issubset(metrics_df.columns):
        return pd.DataFrame(columns=columns)

    ranked = metrics_df[columns].dropna(subset=[metric]).sort_values(metric, ascending=ascending)
    return ranked.head(limit)


def _mean_or_none(metrics_df: pd.DataFrame, column: str) -> float | None:
    if column not in metrics_df:
        return None
    value = metrics_df[column].mean(skipna=True)
    if pd.isna(value):
        return None
    return float(value)


def get_dashboard_overview() -> dict[str, int]:
    with session_scope() as session:
        return {
            "tracked_companies": session.query(Company).filter(Company.is_active.is_(True)).count(),
            "high_priority_count": session.query(WatchlistItem).filter(WatchlistItem.watch_status == "high_priority").count(),
            "owned_count": session.query(WatchlistItem).filter(WatchlistItem.watch_status == "owned").count(),
            "price_bar_count": session.query(PriceBar).count(),
            "metrics_count": session.query(DailyMetric).count(),
            "news_count": session.query(NewsItem).count(),
            "filings_count": session.query(SecFiling).count(),
        }
