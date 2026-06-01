from __future__ import annotations

import pandas as pd
import streamlit as st

from datetime import UTC, datetime
from app.components.sidebar import render_sidebar_navigation

from argus.core.app_engine import create_migrated_database_engine
from argus.core.seed import WATCH_STATUSES
from argus.core.settings import settings
from argus.services.dashboard_service import build_stale_reasons
from argus.services.pullback_finder_service import (
    apply_pullback_filters,
    get_filter_options,
    load_pullback_candidates,
)
from app.components.tables import style_positive_green_negative_red


@st.cache_resource
def get_pullback_engine():
    return create_migrated_database_engine(settings.database_url)


@st.cache_data(ttl=300)
def load_pullback_data() -> pd.DataFrame:
    return load_pullback_candidates(get_pullback_engine())


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:+.{digits}f}%"


def _fmt_score(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.1f}"


def render_explanation_card(ticker: str, company: str, explanation: str, score: float) -> str:
    """Renders a custom HTML/CSS card for displaying pullback explanation and reason."""
    return f"""
    <div style="
        background: rgba(22, 27, 34, 0.7);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(56, 139, 253, 0.4);
        border-radius: 12px;
        padding: 20px;
        margin-top: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
    ">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(240, 246, 252, 0.1); padding-bottom: 8px;">
            <div style="font-size: 18px; font-weight: 600; color: #58a6ff;">
                🔍 Candidate Detail: <span style="color: #f0f6fc;">{ticker}</span> <span style="font-size: 14px; font-weight: normal; color: #8b949e;">({company})</span>
            </div>
            <div style="background: rgba(56, 139, 253, 0.15); color: #58a6ff; font-weight: 600; font-size: 14px; padding: 4px 10px; border-radius: 20px; border: 1px solid rgba(56, 139, 253, 0.3);">
                Score: {score:.1f}
            </div>
        </div>
        <div style="color: #c9d1d9; font-size: 15px; line-height: 1.6; white-space: pre-wrap;">
            {explanation}
        </div>
    </div>
    """


def render_pullback_finder() -> None:
    render_sidebar_navigation()
    st.title("Pullback Finder")
    st.caption(
        "Research support only. This page ranks pullback candidates and explains the score components. "
        "It does not provide trading recommendations or execute trades."
    )
    st.info(
        "Scores combine theme exposure, pullback depth, technical setup, relative strength, "
        "catalysts, watchlist priority, and risk penalties. Missing metrics are handled safely "
        "and reduce the score rather than crashing the page."
    )

    if st.button("Refresh candidates"):
        load_pullback_data.clear()
        st.rerun()

    candidates = load_pullback_data()
    if candidates.empty:
        st.warning("No candidate data found. Run price ingestion and metrics computation first.")
        return

    # Check for stale data warning
    metrics_dates = pd.to_datetime(candidates["metrics_date"]).dt.date.dropna()
    price_dates = pd.to_datetime(candidates["price_date"]).dt.date.dropna()
    latest_metrics_date = metrics_dates.max() if not metrics_dates.empty else None
    latest_price_date = price_dates.max() if not price_dates.empty else None

    stale_reasons = build_stale_reasons(
        latest_price_date,
        latest_metrics_date,
        today=datetime.now(UTC).date(),
    )
    if stale_reasons:
        st.warning("Data warning: " + " ".join(stale_reasons))

    options = get_filter_options(candidates)

    filter1, filter2, filter3 = st.columns(3)
    with filter1:
        selected_sector = st.selectbox("Sector", ["All"] + options["sectors"])
    with filter2:
        selected_theme = st.selectbox("Theme", ["All"] + options["themes"])
    with filter3:
        selected_statuses = st.multiselect(
            "Watch Status",
            sorted(WATCH_STATUSES),
            default=sorted(WATCH_STATUSES),
        )

    filter4, filter5, filter6 = st.columns(3)
    with filter4:
        min_drawdown_pct = st.slider("Minimum drawdown from 52W high (%)", 0, 40, 10)
    with filter5:
        rsi_min, rsi_max = st.slider("RSI 14 range", 0, 100, (0, 55))
    with filter6:
        dma_position = st.selectbox("200DMA position", ["Any", "Above", "Below"])

    filter7, filter8 = st.columns(2)
    with filter7:
        exclude_benchmarks = st.checkbox("Exclude Benchmarks (NVDA, QQQ, MSFT, etc.)", value=True)
    with filter8:
        exclude_hyperscalers = st.checkbox("Exclude Hyperscalers (AMZN, GOOGL, META, MSFT)", value=False)

    filtered = apply_pullback_filters(
        candidates,
        sector=None if selected_sector == "All" else selected_sector,
        theme=None if selected_theme == "All" else selected_theme,
        watch_statuses=selected_statuses or None,
        min_drawdown=min_drawdown_pct / 100.0 if min_drawdown_pct > 0 else None,
        rsi_min=float(rsi_min),
        rsi_max=float(rsi_max),
        dma_position=selected_dma_position(dma_position),
        exclude_benchmarks=exclude_benchmarks,
        exclude_hyperscalers=exclude_hyperscalers,
    )

    if filtered.empty:
        st.info("No candidates match the current filters.")
        return

    display_df = filtered.copy()
    display_df["rank"] = range(1, len(display_df) + 1)
    display_df["ticker"] = display_df["ticker"].apply(lambda t: f"/Company_Detail?ticker={t}")
    display_df["score"] = display_df["opportunity_score"].round(1)
    display_df["drawdown"] = display_df["drawdown_52w"].apply(_fmt_pct)
    display_df["rsi"] = display_df["rsi_14"].apply(lambda value: "n/a" if pd.isna(value) else f"{value:.1f}")
    display_df["vs QQQ 3M"] = display_df["relative_return_vs_qqq_3m"].apply(_fmt_pct)
    display_df["200DMA"] = display_df["distance_from_200dma"].apply(_fmt_pct)
    display_df["theme score"] = display_df["theme_exposure_score"].apply(
        lambda value: "n/a" if pd.isna(value) else f"{value:.1f}/5"
    )

    table_df = display_df[
        [
            "rank",
            "ticker",
            "company",
            "sector",
            "theme",
            "watch_status",
            "score",
            "drawdown",
            "rsi",
            "200DMA",
            "vs QQQ 3M",
            "theme score",
        ]
    ]

    st.subheader("Ranked pullback candidates")
    styled_table_df = table_df.style.map(
        style_positive_green_negative_red,
        subset=["drawdown", "200DMA", "vs QQQ 3M"]
    )
    event = st.dataframe(
        styled_table_df,
        hide_index=True,
        width="stretch",
        column_config={
            "rank": st.column_config.NumberColumn("rank", width="small"),
            "score": st.column_config.NumberColumn("score", format="%.1f"),
            "ticker": st.column_config.LinkColumn("ticker", display_text=r"ticker=(.*)"),
        },
        on_select="rerun",
        selection_mode="single-row",
    )

    st.caption("💡 *Tip: Click on any row in the table above to view the full, wrapped reason/explanation below.*")

    if event and event.selection and event.selection.rows:
        selected_row_idx = event.selection.rows[0]
        selected_row = display_df.iloc[selected_row_idx]
        
        # Extract symbol from link
        import re
        ticker_symbol = selected_row["ticker"]
        match = re.search(r"ticker=(.*)", ticker_symbol)
        if match:
            ticker_symbol = match.group(1)
            
        company_name = selected_row["company"]
        explanation_text = selected_row["explanation"]
        score_val = selected_row["score"]
        
        st.html(render_explanation_card(ticker_symbol, company_name, explanation_text, score_val))

    with st.expander("Score component breakdown"):
        breakdown_df = display_df[
            [
                "ticker",
                "score",
                "score_theme_exposure",
                "score_pullback",
                "score_technical_setup",
                "score_relative_strength",
                "score_catalyst",
                "score_watchlist_priority",
                "score_risk_penalty",
            ]
        ].rename(
            columns={
                "score_theme_exposure": "theme",
                "score_pullback": "pullback",
                "score_technical_setup": "technical",
                "score_relative_strength": "rel strength",
                "score_catalyst": "catalyst",
                "score_watchlist_priority": "watchlist",
                "score_risk_penalty": "risk penalty",
            }
        )
        styled_breakdown_df = breakdown_df.style.map(
            style_positive_green_negative_red,
            subset=["risk penalty"]
        )
        st.dataframe(
            styled_breakdown_df, 
            hide_index=True, 
            width="stretch",
            column_config={"ticker": st.column_config.LinkColumn("ticker", display_text=r"ticker=(.*)")}
        )


def selected_dma_position(label: str) -> str | None:
    mapping = {"Any": "any", "Above": "above", "Below": "below"}
    return mapping.get(label, "any")


render_pullback_finder()
