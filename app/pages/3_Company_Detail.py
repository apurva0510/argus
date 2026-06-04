from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from app.components.sidebar import render_sidebar_navigation

from argus.core.seed import WATCH_STATUSES
from argus.services.company_service import (
    build_relative_performance_frame,
    get_company_options,
    get_company_by_symbol,
    get_company_metrics,
    get_company_price_history,
    get_company_fundamentals,
    get_company_news,
    get_company_filings,
    get_company_notes,
    add_company_note,
    get_watch_status,
    update_watch_status,
    get_watchlist_notes,
)
from app.components.metrics import render_metric_card, render_plain_metric_card

get_relative_perf_df = build_relative_performance_frame


@st.cache_data(ttl=300)
def load_price_history(company_id: int) -> pd.DataFrame:
    return get_company_price_history(company_id)


@st.cache_data(ttl=300)
def load_index_relative_returns(start_date) -> pd.DataFrame:
    from argus.core.app_engine import create_migrated_database_engine
    from argus.core.settings import settings
    from sqlalchemy.orm import sessionmaker
    from argus.analytics.index_builder import (
        calculate_equal_weight_index,
        calculate_relative_performance,
    )

    engine = create_migrated_database_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        index_df = calculate_equal_weight_index(session)
        if index_df.empty:
            return pd.DataFrame()
        rel_df = calculate_relative_performance(session, index_df, start_date)
        return rel_df


@st.cache_data(ttl=300)
def load_company_fundamentals(company_id: int) -> dict | None:
    return get_company_fundamentals(company_id)


@st.cache_data(ttl=300)
def load_company_news(company_id: int) -> list[dict]:
    return get_company_news(company_id)


@st.cache_data(ttl=300)
def load_company_filings(company_id: int) -> list[dict]:
    return get_company_filings(company_id)


def _fmt_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:+.2f}%"


def _fmt_pct_colored(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    pct_val = value * 100
    formatted = f"{pct_val:+.2f}%"
    if pct_val > 0:
        return f"<span style='color: #3fb950; font-weight: 600;'>{formatted}</span>"
    elif pct_val < 0:
        return f"<span style='color: #f85149; font-weight: 600;'>{formatted}</span>"
    else:
        return f"<span style='color: #8b949e; font-weight: 600;'>{formatted}</span>"


def _fmt_price(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"${value:.2f}"


def _fmt_price_range(low: float | None, high: float | None) -> str:
    if low is None or high is None or pd.isna(low) or pd.isna(high):
        return "n/a"
    return f"{_fmt_price(low)} - {_fmt_price(high)}"


def _fmt_multiple(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.2f}"


def _fmt_large_num(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    is_neg = value < 0
    abs_val = abs(value)
    if abs_val >= 1e12:
        formatted = f"${abs_val / 1e12:.2f}T"
    elif abs_val >= 1e9:
        formatted = f"${abs_val / 1e9:.2f}B"
    elif abs_val >= 1e6:
        formatted = f"${abs_val / 1e6:.2f}M"
    else:
        formatted = f"${abs_val:,.2f}"
    return f"-{formatted}" if is_neg else formatted


def render_company_detail() -> None:
    st.set_page_config(page_title="Argus - Company Detail", layout="wide")
    render_sidebar_navigation()

    st.title("🔍 Company Detail")

    symbols = get_company_options()
    if not symbols:
        st.warning("No active companies found in the database. Please seed the database first.")
        return

    # Check query parameters for ticker
    qp = st.query_params
    if "ticker" in qp:
        qp_ticker = qp["ticker"].strip().upper()
        if qp_ticker in symbols:
            st.session_state.selected_ticker = qp_ticker
            st.session_state.ticker_selector_selectbox = qp_ticker

    # Check if a ticker is in session_state or default to first
    if "selected_ticker" not in st.session_state:
        st.session_state.selected_ticker = symbols[0]

    selected_ticker = st.selectbox(
        "Select Ticker",
        symbols,
        index=symbols.index(st.session_state.selected_ticker)
        if st.session_state.selected_ticker in symbols
        else 0,
        key="ticker_selector_selectbox",
    )
    st.session_state.selected_ticker = selected_ticker

    # Load company details
    company = get_company_by_symbol(selected_ticker)
    if not company:
        st.error(f"Company {selected_ticker} not found.")
        return

    # Headline Information
    st.subheader(f"{company['name']} ({company['symbol']})")
    st.caption(
        f"Exchange: {company['exchange']} | Sector: {company['sector']} | Industry: {company['industry']} | Country: {company['country']}"
    )

    metrics = get_company_metrics(company["id"])

    # 8 Metric Cards Layout
    st.write("---")
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)

    # Latest price from price history or metrics
    df_price = load_price_history(company["id"]).copy()
    latest_price = None
    if not df_price.empty:
        df_price["date"] = pd.to_datetime(df_price["date"]).dt.date
        latest_price = df_price.iloc[-1]["adj_close"]

    # Fetch returns from metrics
    ret_1d = metrics.get("return_1d") if metrics else None
    ret_1m = metrics.get("return_1m") if metrics else None
    ret_ytd = metrics.get("return_ytd") if metrics else None
    rsi = metrics.get("rsi_14") if metrics else None
    drawdown = metrics.get("drawdown_52w") if metrics else None
    ma_50 = metrics.get("ma_50") if metrics else None
    ma_200 = metrics.get("ma_200") if metrics else None

    with m_col1:
        st.markdown(
            render_plain_metric_card("Price", latest_price, "${:.2f}"), unsafe_allow_html=True
        )
        st.write("")
        st.markdown(render_metric_card("1D Return", ret_1d), unsafe_allow_html=True)
    with m_col2:
        st.markdown(render_metric_card("1M Return", ret_1m), unsafe_allow_html=True)
        st.write("")
        st.markdown(render_metric_card("YTD Return", ret_ytd), unsafe_allow_html=True)
    with m_col3:
        st.markdown(render_plain_metric_card("RSI (14)", rsi, "{:.1f}"), unsafe_allow_html=True)
        st.write("")
        st.markdown(render_metric_card("52W Drawdown", drawdown), unsafe_allow_html=True)
    with m_col4:
        st.markdown(render_plain_metric_card("50 DMA", ma_50, "${:.2f}"), unsafe_allow_html=True)
        st.write("")
        st.markdown(render_plain_metric_card("200 DMA", ma_200, "${:.2f}"), unsafe_allow_html=True)

    st.write("---")

    # Main split layout: Charts on Left (7), Notes/Watch Status on Right (3)
    main_col1, main_col2 = st.columns([7, 3])

    with main_col1:
        chart_tabs = st.tabs(["Price Chart", "Relative Performance"])

        with chart_tabs[0]:
            # Timeframe selector
            tf = st.radio(
                "Timeframe",
                ["1M", "3M", "6M", "1Y", "All"],
                index=3,
                horizontal=True,
                key="timeframe_radio",
            )

            if df_price.empty:
                st.info("No price history available for this company.")
            else:
                # Calculate rolling MAs on entire history first, so they are accurate at the beginning of the plot
                df_chart = df_price.sort_values("date").copy()
                df_chart["50DMA"] = df_chart["adj_close"].rolling(50).mean()
                df_chart["200DMA"] = df_chart["adj_close"].rolling(200).mean()

                latest_date = df_chart["date"].max()
                if tf == "1M":
                    start_date = latest_date - pd.Timedelta(days=30)
                elif tf == "3M":
                    start_date = latest_date - pd.Timedelta(days=90)
                elif tf == "6M":
                    start_date = latest_date - pd.Timedelta(days=180)
                elif tf == "1Y":
                    start_date = latest_date - pd.Timedelta(days=365)
                else:
                    start_date = df_chart["date"].min()

                df_filtered = df_chart[df_chart["date"] >= start_date]

                # Plotly Chart
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=df_filtered["date"],
                        y=df_filtered["adj_close"],
                        name="Adj Close",
                        line=dict(color="#1f77b4", width=2.5),
                    )
                )

                # Overlay moving averages if they exist in the filtered range
                if not df_filtered["50DMA"].isna().all():
                    fig.add_trace(
                        go.Scatter(
                            x=df_filtered["date"],
                            y=df_filtered["50DMA"],
                            name="50 DMA",
                            line=dict(color="#ff7f0e", width=1.5, dash="dash"),
                        )
                    )
                if not df_filtered["200DMA"].isna().all():
                    fig.add_trace(
                        go.Scatter(
                            x=df_filtered["date"],
                            y=df_filtered["200DMA"],
                            name="200 DMA",
                            line=dict(color="#d62728", width=1.5, dash="dash"),
                        )
                    )

                fig.update_layout(
                    title=f"{company['symbol']} Historical Price",
                    xaxis_title="Date",
                    yaxis_title="Price ($)",
                    template="plotly_white",
                    margin=dict(l=40, r=40, t=40, b=40),
                    height=450,
                    hovermode="x unified",
                )
                st.plotly_chart(fig, width="stretch")

        with chart_tabs[1]:
            st.write("### Relative Return Comparison")
            if df_price.empty:
                st.info("No price history available to calculate relative performance.")
            else:
                # Get start date for relative calculation
                latest_date = df_price["date"].max()
                if tf == "1M":
                    start_date = latest_date - pd.Timedelta(days=30)
                elif tf == "3M":
                    start_date = latest_date - pd.Timedelta(days=90)
                elif tf == "6M":
                    start_date = latest_date - pd.Timedelta(days=180)
                elif tf == "1Y":
                    start_date = latest_date - pd.Timedelta(days=365)
                else:
                    start_date = df_price["date"].min()

                # Fetch QQQ and NVDAclose
                qqq_comp = get_company_by_symbol("QQQ")
                nvda_comp = get_company_by_symbol("NVDA")
                df_qqq = load_price_history(qqq_comp["id"]).copy() if qqq_comp else pd.DataFrame()
                df_nvda = (
                    load_price_history(nvda_comp["id"]).copy() if nvda_comp else pd.DataFrame()
                )

                if not df_qqq.empty:
                    df_qqq["date"] = pd.to_datetime(df_qqq["date"]).dt.date
                if not df_nvda.empty:
                    df_nvda["date"] = pd.to_datetime(df_nvda["date"]).dt.date

                rel_df = get_relative_perf_df(df_price, df_qqq, df_nvda, start_date)

                if rel_df.empty:
                    st.info("No overlapping data found for this timeframe.")
                else:
                    fig_rel = go.Figure()
                    fig_rel.add_trace(
                        go.Scatter(
                            x=rel_df["date"],
                            y=rel_df["comp_ret"],
                            name=company["symbol"],
                            line=dict(color="#1f77b4", width=2.5),
                        )
                    )
                    if "qqq_ret" in rel_df:
                        fig_rel.add_trace(
                            go.Scatter(
                                x=rel_df["date"],
                                y=rel_df["qqq_ret"],
                                name="QQQ (Benchmark)",
                                line=dict(color="#2ca02c", width=1.5, dash="dot"),
                            )
                        )
                    if "nvda_ret" in rel_df:
                        fig_rel.add_trace(
                            go.Scatter(
                                x=rel_df["date"],
                                y=rel_df["nvda_ret"],
                                name="NVDA (Benchmark)",
                                line=dict(color="#9467bd", width=1.5, dash="dot"),
                            )
                        )

                    # Real AI Infra Core Index
                    idx_rel = load_index_relative_returns(start_date)
                    if not idx_rel.empty and "index_ret" in idx_rel:
                        fig_rel.add_trace(
                            go.Scatter(
                                x=idx_rel["date"],
                                y=idx_rel["index_ret"],
                                name="AI Infra Core Index",
                                line=dict(color="#7f7f7f", width=2.0, dash="dash"),
                            )
                        )

                    fig_rel.update_layout(
                        title=f"Relative Cumulative Return vs Benchmarks (Start Date: {start_date})",
                        xaxis_title="Date",
                        yaxis_title="Return (%)",
                        template="plotly_white",
                        margin=dict(l=40, r=40, t=40, b=40),
                        height=450,
                        hovermode="x unified",
                    )
                    st.plotly_chart(fig_rel, width="stretch")

    with main_col2:
        # Watch Status
        st.write("### Watch Status")
        current_status = get_watch_status(company["id"])
        new_status = st.selectbox(
            "Status",
            sorted(list(WATCH_STATUSES)),
            index=sorted(list(WATCH_STATUSES)).index(current_status)
            if current_status in WATCH_STATUSES
            else 0,
            key="watch_status_selectbox",
        )
        if new_status != current_status:
            update_watch_status(company["id"], new_status)
            st.success(f"Status updated to '{new_status}'!")
            # Clear relevant Streamlit cache
            load_price_history.clear()
            load_index_relative_returns.clear()
            load_company_fundamentals.clear()
            load_company_news.clear()
            load_company_filings.clear()
            st.cache_data.clear()
            # Rerun the app
            st.rerun()

        # Watchlist Notes Reference
        wl_notes = get_watchlist_notes(company["id"])
        if wl_notes:
            st.write("---")
            st.write("**Watchlist Reference Notes:**")
            for wl_note in wl_notes:
                st.caption(f"_{wl_note['watchlist']}_:")
                st.info(wl_note["notes"])

        st.write("---")

        # User Notes
        st.write("### User Notes")
        existing_notes = get_company_notes(company["id"])

        # Form to add a note
        with st.form("add_note_form", clear_on_submit=True):
            new_note_text = st.text_area("Add research note...", height=100)
            submit_note = st.form_submit_button("Save Note")
            if submit_note and new_note_text.strip():
                add_company_note(company["id"], new_note_text)
                st.success("Note saved!")
                # Clear relevant Streamlit cache
                load_price_history.clear()
                load_index_relative_returns.clear()
                load_company_fundamentals.clear()
                load_company_news.clear()
                load_company_filings.clear()
                st.cache_data.clear()
                # Rerun the app
                st.rerun()

        # List notes chronologically
        if not existing_notes:
            st.info("No research notes for this ticker yet.")
        else:
            for note in existing_notes:
                dt_str = (
                    note["created_at"].strftime("%Y-%m-%d %H:%M") if note["created_at"] else "n/a"
                )
                st.markdown(f"**{note['created_by'] or 'User'}** ({dt_str}):")
                st.info(note["note_text"])

    # Bottom Layout: Fundamentals, news, filings
    st.write("---")
    bottom_tabs = st.tabs(["Fundamentals Snapshot", "Latest News", "Latest SEC Filings"])

    with bottom_tabs[0]:
        fundamentals = load_company_fundamentals(company["id"])
        if not fundamentals:
            st.info("No fundamentals snapshot available in database.")
        else:
            f_col1, f_col2 = st.columns(2)
            with f_col1:
                st.markdown("**Valuation Metrics**")
                st.markdown(
                    f"- **Market Cap:** {_fmt_large_num(fundamentals.get('market_cap'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **Enterprise Value:** {_fmt_large_num(fundamentals.get('enterprise_value'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **Trailing P/E:** {_fmt_multiple(fundamentals.get('trailing_pe'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **Forward P/E:** {_fmt_multiple(fundamentals.get('forward_pe'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **Price / Sales:** {_fmt_multiple(fundamentals.get('price_to_sales'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **EV / Sales:** {_fmt_multiple(fundamentals.get('ev_to_sales'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **EV / EBITDA:** {_fmt_multiple(fundamentals.get('ev_to_ebitda'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **52W Range:** {_fmt_price_range(metrics.get('low_52w') if metrics else None, metrics.get('high_52w') if metrics else None)}",
                    unsafe_allow_html=True,
                )
            with f_col2:
                st.markdown("**Operating Metrics**")
                st.markdown(
                    f"- **Revenue Growth:** {_fmt_pct_colored(fundamentals.get('revenue_growth'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **Gross Margin:** {_fmt_pct_colored(fundamentals.get('gross_margin'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **Operating Margin:** {_fmt_pct_colored(fundamentals.get('operating_margin'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **Free Cash Flow:** {_fmt_large_num(fundamentals.get('free_cash_flow'))}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"- **Data Provider:** {fundamentals.get('provider')}", unsafe_allow_html=True
                )
                st.markdown(
                    f"- **As of Date:** {fundamentals.get('as_of_date')}", unsafe_allow_html=True
                )

    with bottom_tabs[1]:
        news_items = load_company_news(company["id"])
        if not news_items:
            st.info("No recent news articles found in database.")
        else:
            for item in news_items:
                dt_str = (
                    item["published_at"].strftime("%Y-%m-%d %H:%M")
                    if item["published_at"]
                    else "n/a"
                )
                st.markdown(f"##### [{item['title']}]({item['url']})")
                st.caption(f"Source: {item['source_name'] or 'Unknown'} | {dt_str}")
                if item["summary"]:
                    st.write(item["summary"])
                st.write("---")

    with bottom_tabs[2]:
        filings = load_company_filings(company["id"])
        if not filings:
            st.info("No SEC filings found in database.")
        else:
            for f in filings:
                f_date = f["filing_date"].strftime("%Y-%m-%d") if f["filing_date"] else "n/a"
                url = f["primary_doc_url"] or f["filing_detail_url"] or "#"
                st.markdown(f"- **[{f['form']}]({url})** - filed on {f_date}")


if __name__ == "__main__":
    render_company_detail()
