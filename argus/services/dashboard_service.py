from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from argus.core.settings import settings
from argus.core.seed import AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS, AI_INFRA_CORE_INDEX_SYMBOLS
from argus.analytics.market_hours import filter_regular_market_hours, market_session_date
from argus.services.macro_capex_service import load_macro_capex_context_from_engine

STALE_DAYS_THRESHOLD = 3
LOW_RSI_THRESHOLD = 40.0
DASHBOARD_EXCLUDED_SYMBOLS = frozenset({"DLR", "EQIX"})


def _dashboard_company_filter(alias: str = "c") -> str:
    return f"{alias}.is_active = TRUE AND {alias}.symbol NOT IN :dashboard_excluded_symbols"


def _dashboard_params(**params: object) -> dict[str, object]:
    return {**params, "dashboard_excluded_symbols": sorted(DASHBOARD_EXCLUDED_SYMBOLS)}


def load_dashboard_data_from_engine(engine: Engine) -> dict[str, object]:
    with engine.connect() as conn:
        dialect_name = engine.dialect.name
        today = datetime.now(UTC).date()
        latest_dates = pd.read_sql_query(
            text(
                """
                SELECT
                    (SELECT MAX(date) FROM price_bars WHERE provider = :provider AND interval = '1d') AS latest_price_date,
                    (SELECT MAX(bar_time) FROM price_bars WHERE provider = :provider AND interval = '15m') AS latest_intraday_price_time,
                    (SELECT MAX(date) FROM daily_metrics) AS latest_metrics_date,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_prices') AS last_price_attempt_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'compute_daily_metrics') AS last_metrics_attempt_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_news') AS last_news_attempt_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_filings') AS last_filings_attempt_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_macro') AS last_macro_attempt_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_prices' AND status IN ('success', 'partial_success')) AS last_price_refresh_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'compute_daily_metrics' AND status IN ('success', 'partial_success')) AS last_metrics_refresh_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_news' AND status IN ('success', 'partial_success')) AS last_news_refresh_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_filings' AND status IN ('success', 'partial_success')) AS last_filings_refresh_at,
                    (SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'refresh_macro' AND status IN ('success', 'partial_success')) AS last_macro_refresh_at
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
                        dm.drawdown_52w,
                        dm.opportunity_score
                    FROM daily_metrics dm
                    JOIN companies c ON c.id = dm.company_id
                    WHERE c.is_active = TRUE
                        AND c.symbol NOT IN :dashboard_excluded_symbols
                        AND dm.date = (
                            SELECT MAX(dm2.date)
                            FROM daily_metrics dm2
                            WHERE dm2.company_id = c.id
                        )
                    ORDER BY c.symbol
                    """
                ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
                conn,
                params=_dashboard_params(),
            )

        active_symbol_count = pd.read_sql_query(
            text(
                f"SELECT COUNT(*) AS count FROM companies WHERE {_dashboard_company_filter('companies')}"
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
        ).at[0, "count"]
        active_symbols = pd.read_sql_query(
            text(
                f"SELECT symbol FROM companies WHERE {_dashboard_company_filter('companies')}"
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
        )["symbol"].tolist()
        index_constituent_count = len(
            [
                symbol
                for symbol in active_symbols
                if symbol not in AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS
            ]
        )
        news_count = pd.read_sql_query(
            text(
                """
                SELECT COUNT(*) AS count
                FROM news_items ni
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM news_mentions nm
                    JOIN companies c ON c.id = nm.company_id
                    WHERE nm.news_id = ni.id
                      AND c.symbol IN :dashboard_excluded_symbols
                )
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
        ).at[0, "count"]
        filings_count = pd.read_sql_query(
            text(
                """
                SELECT COUNT(*) AS count
                FROM sec_filings sf
                JOIN companies c ON c.id = sf.company_id
                WHERE c.is_active = TRUE
                  AND c.symbol NOT IN :dashboard_excluded_symbols
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
        ).at[0, "count"]
        earnings_count = pd.read_sql_query(
            text(
                """
                SELECT COUNT(*) AS count
                FROM earnings_events ee
                JOIN companies c ON c.id = ee.company_id
                WHERE ee.event_date >= CURRENT_DATE
                  AND c.is_active = TRUE
                  AND c.symbol NOT IN :dashboard_excluded_symbols
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
        ).at[0, "count"]
        theme_counts = pd.read_sql_query(
            text(
                """
                SELECT
                    COALESCE(parent.name, t.name) AS theme_family,
                    t.name AS theme,
                    COUNT(DISTINCT c.id) AS company_count
                FROM company_theme_exposure cte
                JOIN companies c ON c.id = cte.company_id
                JOIN themes t ON t.id = cte.theme_id
                LEFT JOIN themes parent ON parent.id = t.parent_theme_id
                WHERE c.is_active = TRUE
                    AND c.symbol NOT IN :dashboard_excluded_symbols
                GROUP BY COALESCE(parent.name, t.name), t.name
                ORDER BY COALESCE(parent.name, t.name), t.name
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
        )
        if dialect_name == "postgresql":
            tickers_expr = "string_agg(DISTINCT nm2.ticker, ',')"
        else:
            tickers_expr = "group_concat(DISTINCT nm2.ticker)"
        recent_news = pd.read_sql_query(
            text(
                f"""
                SELECT
                    ni.published_at,
                    ni.title,
                    ni.url,
                    ni.source_name,
                    ni.provider,
                    (
                        SELECT {tickers_expr}
                        FROM news_mentions nm2
                        WHERE nm2.news_id = ni.id
                    ) AS tickers
                FROM news_items ni
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM news_mentions nm3
                    JOIN companies c3 ON c3.id = nm3.company_id
                    WHERE nm3.news_id = ni.id
                      AND c3.symbol IN :dashboard_excluded_symbols
                )
                ORDER BY ni.published_at DESC
                LIMIT 5
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
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
                WHERE c.is_active = TRUE
                    AND c.symbol NOT IN :dashboard_excluded_symbols
                ORDER BY sf.filing_date DESC, sf.acceptance_datetime DESC
                LIMIT 5
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
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
                WHERE ee.event_date >= CURRENT_DATE
                    AND c.is_active = TRUE
                    AND c.symbol NOT IN :dashboard_excluded_symbols
                ORDER BY ee.event_date ASC, c.symbol ASC
                LIMIT 5
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
        )

        # Calculate stale tickers count
        stale_threshold_date = today - timedelta(days=STALE_DAYS_THRESHOLD)
        stale_tickers_count = pd.read_sql_query(
            text(
                """
                SELECT COUNT(DISTINCT symbol) AS count
                FROM companies
                WHERE is_active = TRUE
                  AND symbol NOT IN :dashboard_excluded_symbols
                  AND id NOT IN (
                    SELECT DISTINCT company_id
                    FROM price_bars
                    WHERE provider = :provider
                      AND date >= :stale_threshold_date
                )
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(
                provider=settings.market_data_provider,
                stale_threshold_date=stale_threshold_date,
            ),
        ).at[0, "count"]

        intraday_stale_tickers_count = pd.read_sql_query(
            text(
                """
                SELECT COUNT(DISTINCT symbol) AS count
                FROM companies
                WHERE is_active = TRUE
                  AND symbol NOT IN :dashboard_excluded_symbols
                  AND id NOT IN (
                    SELECT DISTINCT company_id
                    FROM price_bars
                    WHERE provider = :provider
                      AND interval = '15m'
                      AND date >= :stale_threshold_date
                )
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(
                provider=settings.market_data_provider,
                stale_threshold_date=stale_threshold_date,
            ),
        ).at[0, "count"]

        # Fetch latest failed job (only if its most recent run was a failure)
        failed_job_df = pd.read_sql_query(
            text(
                """
                SELECT jr.job_name, jr.finished_at, jr.error_text
                FROM job_runs jr
                JOIN (
                    SELECT job_name, MAX(id) AS max_id
                    FROM job_runs
                    GROUP BY job_name
                ) latest ON jr.id = latest.max_id
                WHERE jr.status = 'failed'
                ORDER BY jr.id DESC LIMIT 1
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

        latest_signals = pd.read_sql_query(
            text(
                """
                SELECT
                    c.symbol,
                    sd.sentiment_proxy_7d,
                    sd.news_relevance_7d,
                    sd.corr_nvda_60d,
                    sd.corr_hyperscaler_60d,
                    sd.earnings_sensitivity,
                    sd.power_signal,
                    sd.capex_signal
                FROM signal_daily sd
                JOIN companies c ON c.id = sd.company_id
                WHERE c.is_active = TRUE
                    AND c.symbol NOT IN :dashboard_excluded_symbols
                    AND sd.date = (
                        SELECT MAX(sd2.date)
                        FROM signal_daily sd2
                    )
                """
            ).bindparams(bindparam("dashboard_excluded_symbols", expanding=True)),
            conn,
            params=_dashboard_params(),
        )

    return {
        "latest_dates": latest_dates.iloc[0].to_dict(),
        "latest_metrics": latest_metrics,
        "latest_signals": latest_signals,
        "active_company_count": int(active_symbol_count),
        "index_constituent_count": int(index_constituent_count),
        "index_symbol_count": int(active_symbol_count),
        "news_count": int(news_count),
        "filings_count": int(filings_count),
        "earnings_count": int(earnings_count),
        "theme_counts": theme_counts,
        "recent_news": recent_news,
        "recent_filings": recent_filings,
        "upcoming_earnings": upcoming_earnings,
        "stale_tickers_count": int(stale_tickers_count),
        "intraday_stale_tickers_count": int(intraday_stale_tickers_count),
        "failed_job": failed_job,
        "provider_status": provider_status,
        "macro_capex_context": load_macro_capex_context_from_engine(engine),
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


def calculate_intraday_core_return_from_engine(engine: Engine) -> float | None:
    with engine.connect() as conn:
        price_df = pd.read_sql_query(
            text(
                """
                SELECT
                    c.symbol,
                    pb.bar_time,
                    pb.adj_close
                FROM price_bars pb
                JOIN companies c ON c.id = pb.company_id
                WHERE c.is_active = TRUE
                    AND c.symbol IN :symbols
                    AND pb.provider = :provider
                    AND pb.interval = '15m'
                    AND pb.adj_close IS NOT NULL
                ORDER BY pb.bar_time ASC
                """
            ).bindparams(bindparam("symbols", expanding=True)),
            conn,
            params={
                "provider": settings.market_data_provider,
                "symbols": sorted(AI_INFRA_CORE_INDEX_SYMBOLS),
            },
        )

    return calculate_intraday_core_return(price_df)


def calculate_intraday_core_return(price_df: pd.DataFrame) -> float | None:
    if price_df.empty or not {"symbol", "bar_time", "adj_close"}.issubset(price_df.columns):
        return None

    df = price_df.copy()
    df["bar_time"] = pd.to_datetime(df["bar_time"])
    df["adj_close"] = pd.to_numeric(df["adj_close"], errors="coerce")
    df = df.dropna(subset=["bar_time", "adj_close"])
    if df.empty:
        return None

    df = df.rename(columns={"bar_time": "date"})
    df = filter_regular_market_hours(df, column="date")
    if df.empty:
        return None

    df["session_date"] = pd.to_datetime(df["date"]).apply(market_session_date)
    latest_session = df["session_date"].dropna().max()
    if latest_session is None:
        return None

    session_df = df[df["session_date"] == latest_session].sort_values(["symbol", "date"])
    returns: list[float] = []
    for _symbol, sym_df in session_df.groupby("symbol"):
        if len(sym_df) < 2:
            continue
        first_price = float(sym_df.iloc[0]["adj_close"])
        latest_price = float(sym_df.iloc[-1]["adj_close"])
        if first_price > 0:
            returns.append((latest_price / first_price) - 1.0)

    if not returns:
        return None
    return float(pd.Series(returns).mean(skipna=True))


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
    rsi = rsi[~rsi["symbol"].isin(DASHBOARD_EXCLUDED_SYMBOLS)]
    return rsi[rsi["rsi_14"] < threshold].sort_values("rsi_14", ascending=True).head(limit)


def _rank_by_metric(
    metrics_df: pd.DataFrame, metric: str, *, limit: int, ascending: bool
) -> pd.DataFrame:
    columns = ["symbol", "name", metric]
    if metrics_df.empty or not set(columns).issubset(metrics_df.columns):
        return pd.DataFrame(columns=columns)

    ranked = (
        metrics_df[columns]
        .dropna(subset=[metric])
        .loc[lambda df: ~df["symbol"].isin(DASHBOARD_EXCLUDED_SYMBOLS)]
        .sort_values(metric, ascending=ascending)
    )
    return ranked.head(limit)


def _mean_or_none(metrics_df: pd.DataFrame, column: str) -> float | None:
    if column not in metrics_df:
        return None
    value = metrics_df[column].mean(skipna=True)
    if pd.isna(value):
        return None
    return float(value)

