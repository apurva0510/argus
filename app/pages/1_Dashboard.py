from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from argus.core.db import create_database_engine

from argus.core.settings import settings
from argus.services.dashboard_service import (
    build_stale_reasons,
    filter_low_rsi,
    load_dashboard_data_from_engine,
    parse_optional_date,
    parse_optional_datetime,
    rank_biggest_drawdowns,
    rank_top_gainers,
    rank_top_losers,
    summarize_core_returns,
)


@st.cache_resource
def get_dashboard_engine():
    return create_database_engine(settings.database_url)


@st.cache_data(ttl=300)
def load_dashboard_data() -> dict[str, object]:
    return load_dashboard_data_from_engine(get_dashboard_engine())


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:+.{digits}f}%"


def _fmt_plain_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:.{digits}f}%"


def render_dashboard() -> None:
    st.title("Dashboard")

    if st.button("Refresh dashboard"):
        load_dashboard_data.clear()
        st.rerun()

    data = load_dashboard_data()
    latest_dates = data["latest_dates"]
    metrics_df: pd.DataFrame = data["latest_metrics"]

    last_price_refresh = parse_optional_datetime(latest_dates.get("last_price_refresh_at"))
    last_metrics_refresh = parse_optional_datetime(latest_dates.get("last_metrics_refresh_at"))
    latest_price_date = parse_optional_date(latest_dates.get("latest_price_date"))
    latest_metrics_date = parse_optional_date(latest_dates.get("latest_metrics_date"))

    st.caption(
        f"Last price refresh: {last_price_refresh.isoformat() if last_price_refresh else 'not available'} | "
        f"Last metrics refresh: {last_metrics_refresh.isoformat() if last_metrics_refresh else 'not available'}"
    )

    stale_reasons = build_stale_reasons(
        latest_price_date,
        latest_metrics_date,
        today=datetime.now(UTC).date(),
    )
    if stale_reasons:
        st.warning("Data warning: " + " ".join(stale_reasons))
    else:
        st.success("Data freshness looks good.")

    if metrics_df.empty:
        st.info("No daily metrics available yet. Run price backfill and metrics computation scripts.")
        st.subheader("Recent News")
        st.info("News feed will appear here after news ingestion is implemented.")
        st.subheader("Recent Filings")
        st.info("SEC filings will appear here after filings ingestion is implemented.")
        st.subheader("Upcoming Earnings")
        st.info("Earnings events will appear here after earnings ingestion is implemented.")
        return

    core_returns = summarize_core_returns(metrics_df)
    core_1d = core_returns["return_1d"]
    core_1w = core_returns["return_1w"]
    core_1m = core_returns["return_1m"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tracked Symbols", int(data["index_symbol_count"]))
    col2.metric("AI Infra Core 1D", _fmt_plain_pct(core_1d), delta=_fmt_pct(core_1d), delta_color="normal")
    col3.metric("AI Infra Core 1W", _fmt_plain_pct(core_1w), delta=_fmt_pct(core_1w), delta_color="normal")
    col4.metric("AI Infra Core 1M", _fmt_plain_pct(core_1m), delta=_fmt_pct(core_1m), delta_color="normal")

    st.caption("AI Infra Core is a simple equal-weight average excluding benchmarks and optional aggressive names.")

    gainers = rank_top_gainers(metrics_df)
    losers = rank_top_losers(metrics_df)
    drawdowns = rank_biggest_drawdowns(metrics_df)
    rsi_below_40 = filter_low_rsi(metrics_df)

    left, right = st.columns(2)
    with left:
        st.subheader("Top 5 Gainers (1D)")
        if gainers.empty:
            st.info("No 1D return data available for the latest metrics date.")
        else:
            gainers_view = gainers.rename(columns={"symbol": "Ticker", "name": "Company", "return_1d": "1D %"}).copy()
            gainers_view["1D %"] = gainers_view["1D %"].apply(_fmt_pct)
            st.dataframe(
                gainers_view,
                hide_index=True,
                width="stretch",
            )
        st.subheader("Biggest Drawdowns From 52W High")
        if drawdowns.empty:
            st.info("No 52-week drawdown data available for the latest metrics date.")
        else:
            drawdowns_view = drawdowns.rename(
                columns={"symbol": "Ticker", "name": "Company", "drawdown_52w": "Drawdown %"}
            ).copy()
            drawdowns_view["Drawdown %"] = drawdowns_view["Drawdown %"].apply(_fmt_pct)
            st.dataframe(
                drawdowns_view,
                hide_index=True,
                width="stretch",
            )
    with right:
        st.subheader("Top 5 Losers (1D)")
        if losers.empty:
            st.info("No 1D return data available for the latest metrics date.")
        else:
            losers_view = losers.rename(columns={"symbol": "Ticker", "name": "Company", "return_1d": "1D %"}).copy()
            losers_view["1D %"] = losers_view["1D %"].apply(_fmt_pct)
            st.dataframe(
                losers_view,
                hide_index=True,
                width="stretch",
            )
        st.subheader("RSI Below 40")
        if rsi_below_40.empty:
            st.info("No symbols with RSI below 40 on the latest metrics date.")
        else:
            rsi_view = rsi_below_40.rename(columns={"symbol": "Ticker", "name": "Company", "rsi_14": "RSI 14"}).copy()
            rsi_view["RSI 14"] = rsi_view["RSI 14"].round(1)
            st.dataframe(rsi_view, hide_index=True, width="stretch")

    st.subheader("Recent News")
    if data["news_count"] == 0:
        st.info("News feed placeholder. News ingestion is not implemented yet.")
    else:
        st.info(f"News data exists ({data['news_count']} rows). News dashboard section is coming next phase.")

    st.subheader("Recent Filings")
    if data["filings_count"] == 0:
        st.info("Filings placeholder. SEC filings dashboard section is not implemented yet.")
    else:
        st.info(
            f"Filings data exists ({data['filings_count']} rows). Filings dashboard section is coming next phase."
        )

    st.subheader("Upcoming Earnings")
    if data["earnings_count"] == 0:
        st.info("Earnings placeholder. Earnings dashboard section is not implemented yet.")
    else:
        st.info(
            f"Upcoming earnings data exists ({data['earnings_count']} rows). Earnings section is coming next phase."
        )


render_dashboard()
