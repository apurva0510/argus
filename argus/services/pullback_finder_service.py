from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from argus.analytics.scoring import ScoreInputs, compute_opportunity_score
from argus.core.seed import WATCH_STATUSES
from argus.core.settings import settings


def load_pullback_candidates(engine: Engine) -> pd.DataFrame:
    with engine.connect() as conn:
        dialect_name = engine.dialect.name
        now = datetime.now(UTC).replace(tzinfo=None)
        news_start_date = now - timedelta(days=7)
        filing_start_date = (now - timedelta(days=30)).date()
        current_date = now.date()

        if dialect_name == "postgresql":
            earnings_expr = "MIN(ee.event_date - :current_date)"
        else:
            earnings_expr = "MIN(JULIANDAY(ee.event_date) - JULIANDAY(:current_date))"

        df = pd.read_sql_query(
            text(
                f"""
                SELECT
                    c.id AS company_id,
                    c.symbol AS ticker,
                    c.name AS company,
                    c.sector AS sector,
                    c.is_benchmark AS is_benchmark,
                    c.is_hyperscaler AS is_hyperscaler,
                    w.name AS theme,
                    wi.watch_status AS watch_status,
                    pb.adj_close AS price,
                    pb.date AS price_date,
                    dm.date AS metrics_date,
                    dm.drawdown_52w AS drawdown_52w,
                    dm.rsi_14 AS rsi_14,
                    dm.distance_from_200dma AS distance_from_200dma,
                    dm.relative_return_vs_qqq_3m AS relative_return_vs_qqq_3m,
                    dm.return_1w AS return_1w,
                    dm.opportunity_score AS stored_opportunity_score,
                    (
                        SELECT MAX(cte.exposure_score)
                        FROM company_theme_exposure cte
                        WHERE cte.company_id = c.id
                    ) AS theme_exposure_score,
                    (
                        SELECT COUNT(*)
                        FROM news_mentions nm
                        JOIN news_items ni ON ni.id = nm.news_id
                        WHERE nm.company_id = c.id
                            AND ni.published_at >= :news_start_date
                    ) AS recent_news_count,
                    (
                        SELECT COUNT(*)
                        FROM sec_filings sf
                        WHERE sf.company_id = c.id
                            AND sf.filing_date >= :filing_start_date
                    ) AS recent_filing_count,
                    (
                        SELECT {earnings_expr}
                        FROM earnings_events ee
                        WHERE ee.company_id = c.id
                            AND ee.event_date >= :current_date
                    ) AS upcoming_earnings_days
                FROM companies c
                JOIN watchlist_items wi ON wi.company_id = c.id
                JOIN watchlists w ON w.id = wi.watchlist_id
                LEFT JOIN price_bars pb ON pb.id = (
                    SELECT pb2.id
                    FROM price_bars pb2
                    WHERE pb2.company_id = c.id
                        AND pb2.provider = :provider
                    ORDER BY pb2.bar_time DESC, pb2.date DESC
                    LIMIT 1
                )
                LEFT JOIN daily_metrics dm ON dm.id = (
                    SELECT dm2.id
                    FROM daily_metrics dm2
                    WHERE dm2.company_id = c.id
                    ORDER BY dm2.date DESC
                    LIMIT 1
                )
                WHERE c.is_active = TRUE
                ORDER BY c.symbol, w.name
                """
            ),
            conn,
            params={
                "provider": settings.market_data_provider,
                "news_start_date": news_start_date,
                "filing_start_date": filing_start_date,
                "current_date": current_date,
            },
        )

    if df.empty:
        return df

    return _dedupe_companies(_score_candidates(df))


def _dedupe_companies(df: pd.DataFrame) -> pd.DataFrame:
    priority = {"high_priority": 4, "owned": 3, "watch": 2, "ignore": 1}
    working = df.copy()
    working["_watch_priority"] = working["watch_status"].map(priority).fillna(0)
    working = working.sort_values(["ticker", "_watch_priority"], ascending=[True, False])
    deduped = working.drop_duplicates(subset=["ticker"], keep="first").drop(columns=["_watch_priority"])
    sorted_df = deduped.sort_values(["opportunity_score", "ticker"], ascending=[False, True])
    return sorted_df.reset_index(drop=True)


def _score_candidates(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in df.to_dict(orient="records"):
        earnings_days = record.get("upcoming_earnings_days")
        if pd.isna(earnings_days):
            earnings_days_value = None
        else:
            earnings_days_value = max(0, int(round(float(earnings_days))))

        breakdown = compute_opportunity_score(
            ScoreInputs(
                theme_exposure_score=record.get("theme_exposure_score"),
                drawdown_52w=record.get("drawdown_52w"),
                rsi_14=record.get("rsi_14"),
                distance_from_200dma=record.get("distance_from_200dma"),
                relative_return_vs_qqq_3m=record.get("relative_return_vs_qqq_3m"),
                watch_status=record.get("watch_status"),
                recent_news_count=_safe_int(record.get("recent_news_count")),
                recent_filing_count=_safe_int(record.get("recent_filing_count")),
                upcoming_earnings_days=earnings_days_value,
                return_1w=record.get("return_1w"),
            )
        )
        rows.append(
            {
                **record,
                "opportunity_score": breakdown.opportunity_score,
                "score_theme_exposure": breakdown.theme_exposure,
                "score_pullback": breakdown.pullback,
                "score_technical_setup": breakdown.technical_setup,
                "score_relative_strength": breakdown.relative_strength,
                "score_catalyst": breakdown.catalyst,
                "score_watchlist_priority": breakdown.watchlist_priority,
                "score_risk_penalty": breakdown.risk_penalty,
                "explanation": breakdown.explanation,
            }
        )

    scored = pd.DataFrame(rows)
    return scored.sort_values("opportunity_score", ascending=False).reset_index(drop=True)


def apply_pullback_filters(
    df: pd.DataFrame,
    *,
    sector: str | None = None,
    theme: str | None = None,
    watch_statuses: list[str] | None = None,
    min_drawdown: float | None = None,
    rsi_min: float | None = None,
    rsi_max: float | None = None,
    dma_position: str | None = None,
    exclude_benchmarks: bool = False,
    exclude_hyperscalers: bool = False,
) -> pd.DataFrame:
    if df.empty:
        return df

    filtered = df.copy()

    if sector:
        filtered = filtered[filtered["sector"] == sector]

    if theme:
        filtered = filtered[filtered["theme"] == theme]

    if watch_statuses:
        filtered = filtered[filtered["watch_status"].isin(watch_statuses)]

    if min_drawdown is not None and min_drawdown > 0:
        drawdown_magnitude = filtered["drawdown_52w"].apply(_drawdown_magnitude)
        filtered = filtered[drawdown_magnitude >= min_drawdown]

    if rsi_min is not None:
        filtered = filtered[filtered["rsi_14"].isna() | (filtered["rsi_14"] >= rsi_min)]

    if rsi_max is not None:
        filtered = filtered[filtered["rsi_14"].isna() | (filtered["rsi_14"] <= rsi_max)]

    if exclude_benchmarks:
        filtered = filtered[filtered["is_benchmark"] != 1]

    if exclude_hyperscalers:
        filtered = filtered[filtered["is_hyperscaler"] != 1]

    dma_position = (dma_position or "any").lower()
    if dma_position == "above":
        filtered = filtered[filtered["distance_from_200dma"].notna() & (filtered["distance_from_200dma"] >= 0)]
    elif dma_position == "below":
        filtered = filtered[filtered["distance_from_200dma"].notna() & (filtered["distance_from_200dma"] < 0)]

    return filtered.reset_index(drop=True)


def get_filter_options(df: pd.DataFrame) -> dict[str, list[str]]:
    if df.empty:
        return {"sectors": [], "themes": []}

    return {
        "sectors": sorted(df["sector"].dropna().unique().tolist()),
        "themes": sorted(df["theme"].dropna().unique().tolist()),
    }


def _drawdown_magnitude(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return abs(min(0.0, float(value)))


def _safe_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def validate_watch_statuses(statuses: list[str]) -> list[str]:
    return [status for status in statuses if status in WATCH_STATUSES]
