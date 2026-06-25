from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from argus.analytics.scoring import compute_opportunity_score
from argus.core.settings import settings
from argus.services.scoring_service import build_score_inputs, load_scoring_inputs_for_active_companies


def load_pullback_candidates(engine: Engine) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(
                """
                SELECT
                    c.id AS company_id,
                    c.symbol AS ticker,
                    c.name AS company,
                    c.sector AS sector,
                    c.is_benchmark AS is_benchmark,
                    c.is_hyperscaler AS is_hyperscaler,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM company_theme_exposure cte_family
                            JOIN themes t_family ON t_family.id = cte_family.theme_id
                            LEFT JOIN themes p_family ON p_family.id = t_family.parent_theme_id
                            WHERE cte_family.company_id = c.id
                                AND (
                                    t_family.code = 'emerging_compute'
                                    OR p_family.code = 'emerging_compute'
                                )
                        )
                        THEN 'Emerging Compute'
                        ELSE 'AI Infrastructure'
                    END AS theme_family,
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
                    vps_ev.valuation_flag AS valuation_flag,
                    vps_ev.premium_discount_pct AS ev_sales_premium_discount_pct,
                    vps_fpe.percentile_rank AS forward_pe_percentile_rank,
                    fs.revenue_growth AS revenue_growth
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
                LEFT JOIN valuation_peer_snapshot vps_ev ON vps_ev.id = (
                    SELECT vps_ev2.id
                    FROM valuation_peer_snapshot vps_ev2
                    WHERE vps_ev2.company_id = c.id
                        AND vps_ev2.peer_group_type = 'sector'
                        AND vps_ev2.metric_name = 'ev_to_sales'
                    ORDER BY vps_ev2.as_of_date DESC, vps_ev2.id DESC
                    LIMIT 1
                )
                LEFT JOIN valuation_peer_snapshot vps_fpe ON vps_fpe.id = (
                    SELECT vps_fpe2.id
                    FROM valuation_peer_snapshot vps_fpe2
                    WHERE vps_fpe2.company_id = c.id
                        AND vps_fpe2.peer_group_type = 'sector'
                        AND vps_fpe2.metric_name = 'forward_pe'
                    ORDER BY vps_fpe2.as_of_date DESC, vps_fpe2.id DESC
                    LIMIT 1
                )
                LEFT JOIN fundamentals_snapshot fs ON fs.id = (
                    SELECT fs2.id
                    FROM fundamentals_snapshot fs2
                    WHERE fs2.company_id = c.id
                    ORDER BY fs2.as_of_date DESC, fs2.id DESC
                    LIMIT 1
                )
                WHERE c.is_active = TRUE
                ORDER BY c.symbol, w.name
                """
            ),
            conn,
            params={
                "provider": settings.market_data_provider,
            },
        )

        if not df.empty:
            inputs = load_scoring_inputs_for_active_companies(conn)
            df["theme_exposure_score"] = df["company_id"].map(lambda cid: inputs.get(cid, {}).get("theme_exposure_score"))
            df["recent_news_count"] = df["company_id"].map(lambda cid: inputs.get(cid, {}).get("recent_news_count", 0))
            df["recent_filing_count"] = df["company_id"].map(lambda cid: inputs.get(cid, {}).get("recent_filing_count", 0))
            df["upcoming_earnings_days"] = df["company_id"].map(lambda cid: inputs.get(cid, {}).get("upcoming_earnings_days"))

    if df.empty:
        return df

    from argus.services.macro_capex_service import load_macro_capex_context_from_engine

    try:
        macro_ctx = load_macro_capex_context_from_engine(engine)
        pressure_level = int(macro_ctx.get("pressure_level", 0))
    except Exception:
        pressure_level = 0

    return _dedupe_companies(_score_candidates(df, pressure_level=pressure_level))


def _dedupe_companies(df: pd.DataFrame) -> pd.DataFrame:
    priority = {"high_priority": 4, "owned": 3, "watch": 2, "ignore": 1}
    working = df.copy()
    working["_watch_priority"] = working["watch_status"].map(priority).fillna(0)
    working = working.sort_values(["ticker", "_watch_priority"], ascending=[True, False])
    deduped = working.drop_duplicates(subset=["ticker"], keep="first").drop(
        columns=["_watch_priority"]
    )
    sorted_df = deduped.sort_values(["opportunity_score", "ticker"], ascending=[False, True])
    return sorted_df.reset_index(drop=True)


def _score_candidates(df: pd.DataFrame, pressure_level: int = 0) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in df.to_dict(orient="records"):
        breakdown = compute_opportunity_score(
            build_score_inputs(record, macro_pressure_level=pressure_level)
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
                "score_macro_penalty": breakdown.macro_penalty,
                "score_valuation_adjustment": breakdown.valuation_adjustment,
                "explanation": breakdown.explanation,
            }
        )

    scored = pd.DataFrame(rows)
    return scored.sort_values("opportunity_score", ascending=False).reset_index(drop=True)


def apply_pullback_filters(
    df: pd.DataFrame,
    *,
    sector: str | None = None,
    theme_family: str | None = None,
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

    if theme_family:
        filtered = filtered[filtered["theme_family"] == theme_family]

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
        filtered = filtered[
            filtered["distance_from_200dma"].notna() & (filtered["distance_from_200dma"] >= 0)
        ]
    elif dma_position == "below":
        filtered = filtered[
            filtered["distance_from_200dma"].notna() & (filtered["distance_from_200dma"] < 0)
        ]

    return filtered.reset_index(drop=True)


def get_filter_options(df: pd.DataFrame) -> dict[str, list[str]]:
    if df.empty:
        return {"sectors": [], "theme_families": [], "themes": []}

    return {
        "sectors": _sorted_unique(df, "sector"),
        "theme_families": _sorted_unique(df, "theme_family"),
        "themes": _sorted_unique(df, "theme"),
    }


def _sorted_unique(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df:
        return []
    return sorted(df[column].dropna().unique().tolist())


def _drawdown_magnitude(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return abs(min(0.0, float(value)))
