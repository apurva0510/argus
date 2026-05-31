from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from app.components.sidebar import render_sidebar_navigation
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


def _render_recent_news(news_df: pd.DataFrame) -> None:
    if news_df.empty:
        st.info("No recent news found. Run `python scripts/refresh_news.py` to ingest catalyst headlines.")
        return

    view = news_df.rename(
        columns={
            "published_at": "Published",
            "title": "Headline",
            "source_name": "Source",
            "tickers": "Tickers",
            "url": "Link",
        }
    ).copy()
    view["Published"] = pd.to_datetime(view["Published"]).dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(
        view[["Published", "Headline", "Source", "Tickers", "Link"]],
        hide_index=True,
        width="stretch",
        column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open")},
    )


def _render_recent_filings(filings_df: pd.DataFrame) -> None:
    if filings_df.empty:
        st.info("No recent SEC filings found. Run `python scripts/refresh_filings.py` after setting SEC_USER_AGENT.")
        return

    view = filings_df.rename(
        columns={
            "symbol": "Ticker",
            "name": "Company",
            "form": "Form",
            "filing_date": "Filed",
            "filing_detail_url": "Filing",
        }
    ).copy()
    view["Filed"] = pd.to_datetime(view["Filed"]).dt.strftime("%Y-%m-%d")
    st.dataframe(
        view[["Filed", "Ticker", "Company", "Form", "Filing"]],
        hide_index=True,
        width="stretch",
        column_config={"Filing": st.column_config.LinkColumn("Filing", display_text="Open")},
    )


def _render_upcoming_earnings(earnings_df: pd.DataFrame) -> None:
    if earnings_df.empty:
        st.info("No upcoming earnings found in the database.")
        return

    view = earnings_df.rename(
        columns={
            "event_date": "Date",
            "symbol": "Ticker",
            "name": "Company",
            "fiscal_period": "Fiscal Period",
            "source": "Source",
        }
    ).copy()
    view["Date"] = pd.to_datetime(view["Date"]).dt.strftime("%Y-%m-%d")
    st.dataframe(
        view[["Date", "Ticker", "Company", "Fiscal Period", "Source"]],
        hide_index=True,
        width="stretch",
    )


def render_dashboard() -> None:
    render_sidebar_navigation()
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
            gainers_view["Ticker"] = gainers_view["Ticker"].apply(lambda t: f"/Company_Detail?ticker={t}")
            gainers_view["1D %"] = gainers_view["1D %"].apply(_fmt_pct)
            st.dataframe(
                gainers_view,
                hide_index=True,
                width="stretch",
                column_config={"Ticker": st.column_config.LinkColumn("Ticker", display_text=r"ticker=(.*)")}
            )
        st.subheader("Biggest Drawdowns From 52W High")
        if drawdowns.empty:
            st.info("No 52-week drawdown data available for the latest metrics date.")
        else:
            drawdowns_view = drawdowns.rename(
                columns={"symbol": "Ticker", "name": "Company", "drawdown_52w": "Drawdown %"}
            ).copy()
            drawdowns_view["Ticker"] = drawdowns_view["Ticker"].apply(lambda t: f"/Company_Detail?ticker={t}")
            drawdowns_view["Drawdown %"] = drawdowns_view["Drawdown %"].apply(_fmt_pct)
            st.dataframe(
                drawdowns_view,
                hide_index=True,
                width="stretch",
                column_config={"Ticker": st.column_config.LinkColumn("Ticker", display_text=r"ticker=(.*)")}
            )
    with right:
        st.subheader("Top 5 Losers (1D)")
        if losers.empty:
            st.info("No 1D return data available for the latest metrics date.")
        else:
            losers_view = losers.rename(columns={"symbol": "Ticker", "name": "Company", "return_1d": "1D %"}).copy()
            losers_view["Ticker"] = losers_view["Ticker"].apply(lambda t: f"/Company_Detail?ticker={t}")
            losers_view["1D %"] = losers_view["1D %"].apply(_fmt_pct)
            st.dataframe(
                losers_view,
                hide_index=True,
                width="stretch",
                column_config={"Ticker": st.column_config.LinkColumn("Ticker", display_text=r"ticker=(.*)")}
            )
        st.subheader("RSI Below 40")
        if rsi_below_40.empty:
            st.info("No symbols with RSI below 40 on the latest metrics date.")
        else:
            rsi_view = rsi_below_40.rename(columns={"symbol": "Ticker", "name": "Company", "rsi_14": "RSI 14"}).copy()
            rsi_view["Ticker"] = rsi_view["Ticker"].apply(lambda t: f"/Company_Detail?ticker={t}")
            rsi_view["RSI 14"] = rsi_view["RSI 14"].round(1)
            st.dataframe(
                rsi_view,
                hide_index=True,
                width="stretch",
                column_config={"Ticker": st.column_config.LinkColumn("Ticker", display_text=r"ticker=(.*)")}
            )

    st.subheader("Recent News")
    _render_recent_news(data["recent_news"])

    st.subheader("Recent Filings")
    _render_recent_filings(data["recent_filings"])

    st.subheader("Upcoming Earnings")
    _render_upcoming_earnings(data["upcoming_earnings"])


render_dashboard()
