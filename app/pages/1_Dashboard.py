from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from app.components.sidebar import render_sidebar_navigation
from app.auth_links import company_detail_url
import os
from argus.core.app_engine import create_migrated_database_engine

from argus.core.settings import settings
from argus.core.timezones import format_et_datetime, to_et_naive_series
from argus.services.dashboard_service import (
    build_stale_reasons,
    calculate_intraday_core_return_from_engine,
    filter_low_rsi,
    load_dashboard_data_from_engine,
    parse_optional_date,
    parse_optional_datetime,
    rank_biggest_drawdowns,
    rank_top_gainers,
    rank_top_losers,
    summarize_core_returns,
)
from app.components.metrics import render_metric_card, render_plain_metric_card
from app.components.tables import style_positive_green_negative_red


@st.cache_resource
def get_dashboard_engine():
    return create_migrated_database_engine(settings.database_url)


@st.cache_data(ttl=300)
def load_dashboard_data() -> dict[str, object]:
    return load_dashboard_data_from_engine(get_dashboard_engine())


@st.cache_data(ttl=60)
def load_intraday_core_return() -> float | None:
    return calculate_intraday_core_return_from_engine(get_dashboard_engine())


@st.cache_data(ttl=300)
def load_index_data(tf: str) -> dict:
    from sqlalchemy.orm import sessionmaker
    from argus.analytics.index_builder import (
        calculate_equal_weight_index,
        calculate_relative_performance,
        calculate_top_contributors,
        get_default_index_symbols,
    )
    from argus.analytics.market_hours import filter_latest_market_sessions

    engine = get_dashboard_engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        short_range = tf in {"1D", "5D"}
        interval = "15m" if short_range else "1d"
        index_df = calculate_equal_weight_index(
            session,
            interval=interval,
            use_precomputed=not short_range,
        )
        if index_df.empty:
            return {}

        if short_range:
            index_df = filter_latest_market_sessions(index_df, 1 if tf == "1D" else 5)
            if index_df.empty:
                return {}

        latest_point = pd.to_datetime(index_df["date"]).max()
        if tf == "1D":
            start_date = pd.to_datetime(index_df["date"]).min()
        elif tf == "5D":
            start_date = pd.to_datetime(index_df["date"]).min()
        elif tf == "1M":
            start_date = latest_point - pd.Timedelta(days=30)
        elif tf == "3M":
            start_date = latest_point - pd.Timedelta(days=90)
        elif tf == "6M":
            start_date = latest_point - pd.Timedelta(days=180)
        elif tf == "1Y":
            start_date = latest_point - pd.Timedelta(days=365)
        else:
            start_date = pd.to_datetime(index_df["date"]).min()

        if not short_range:
            start_date = pd.to_datetime(start_date).date()
        latest_date_date = latest_point.date()

        rel_df = calculate_relative_performance(
            session,
            index_df,
            start_date,
            interval=interval,
        )
        if not rel_df.empty:
            rel_df["index_level"] = 100.0 + rel_df["index_ret"]
            if "qqq_ret" in rel_df and not rel_df["qqq_ret"].isna().all():
                rel_df["qqq_level"] = 100.0 + rel_df["qqq_ret"]
            if "nvda_ret" in rel_df and not rel_df["nvda_ret"].isna().all():
                rel_df["nvda_level"] = 100.0 + rel_df["nvda_ret"]

        symbols = get_default_index_symbols(session)

        date_1m = latest_date_date - pd.Timedelta(days=30)
        date_3m = latest_date_date - pd.Timedelta(days=90)
        date_ytd = datetime(latest_date_date.year - 1, 12, 31).date()

        contrib_1m = calculate_top_contributors(session, symbols, date_1m, latest_date_date)
        contrib_3m = calculate_top_contributors(session, symbols, date_3m, latest_date_date)
        contrib_ytd = calculate_top_contributors(session, symbols, date_ytd, latest_date_date)

        return {
            "rel_df": rel_df,
            "contrib_1m": contrib_1m,
            "contrib_3m": contrib_3m,
            "contrib_ytd": contrib_ytd,
            "constituent_count": len(symbols),
            "interval": interval,
        }


def apply_intraday_xaxis(fig, df_or_interval, tf: str | None = None) -> None:
    # Support old signature: apply_intraday_xaxis(fig, interval)
    if tf is None:
        if df_or_interval == "15m":
            fig.update_xaxes(type="category")
        return

    # Only apply category axis formatting to intraday 1D/5D timeframes
    if tf not in ("1D", "5D"):
        return

    df = df_or_interval
    if df.empty:
        return

    # dates are already in US Eastern Time (New York) naive format
    dates_ny = pd.to_datetime(df["date"])
    tick_value_column = "date_label" if "date_label" in df.columns else "date"

    tickvals = []
    ticktext = []
    
    if tf == "1D":
        for i, dt in enumerate(dates_ny):
            time_str = dt.strftime("%I:%M %p")
            # Show tick at start, 11:00 AM, 01:00 PM, 03:00 PM, and end of session
            if i == 0 or dt.strftime("%H:%M") in ("11:00", "13:00", "15:00") or i == len(dates_ny) - 1:
                tickvals.append(df.iloc[i][tick_value_column])
                ticktext.append(time_str)
    elif tf == "5D":
        last_date = None
        for i, dt in enumerate(dates_ny):
            day_str = dt.strftime("%b %d")
            if last_date != day_str:
                tickvals.append(df.iloc[i][tick_value_column])
                ticktext.append(day_str)
                last_date = day_str
                
    if tickvals:
        fig.update_xaxes(
            type="category",
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            tickangle=0,
        )


def _format_dt_et(val) -> str:
    if val is None or pd.isna(val):
        return "Never"
    formatted = format_et_datetime(val)
    return formatted if formatted != "Never" else str(val)


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:+.{digits}f}%"


def _fmt_plain_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:.{digits}f}%"


def _fmt_bps(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.0f} bps"


def _fmt_pct_colored(value: float | None, *, positive_is_bad: bool = False) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    pct_val = value * 100
    formatted = f"{pct_val:+.2f}%"
    if pct_val == 0:
        return f"<span style='color: #8b949e; font-weight: 600;'>{formatted}</span>"
    is_bad = pct_val > 0 if positive_is_bad else pct_val < 0
    color = "#f85149" if is_bad else "#3fb950"
    return f"<span style='color: {color}; font-weight: 600;'>{formatted}</span>"


def _fmt_bps_colored(value: float | None, *, positive_is_bad: bool = False) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    formatted = f"{value:+.0f} bps"
    if value == 0:
        return f"<span style='color: #8b949e; font-weight: 600;'>{formatted}</span>"
    is_bad = value > 0 if positive_is_bad else value < 0
    color = "#f85149" if is_bad else "#3fb950"
    return f"<span style='color: {color}; font-weight: 600;'>{formatted}</span>"


def _fmt_yield_obs(observation: object) -> str:
    if not isinstance(observation, dict) or observation.get("value") is None:
        return "n/a"
    return f"{float(observation['value']):.2f}%"


def _fmt_currency(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    abs_value = abs(float(value))
    sign = "-" if float(value) < 0 else ""
    if abs_value >= 1_000_000_000_000:
        return f"{sign}${abs_value / 1_000_000_000_000:.2f}T"
    if abs_value >= 1_000_000_000:
        return f"{sign}${abs_value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{sign}${abs_value / 1_000_000:.2f}M"
    return f"{sign}${abs_value:,.0f}"


def _ticker_link_column_config() -> dict[str, object]:
    return {"Ticker": st.column_config.LinkColumn("Ticker", display_text=r"ticker=([^&]+)")}


def _link_ticker_series(series: pd.Series) -> pd.Series:
    return series.apply(lambda ticker: company_detail_url(ticker) if ticker else "")


def _ticker_markdown(ticker: str) -> str:
    return f"[{ticker}]({company_detail_url(ticker)})"


def _split_tickers(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return [""]
    tickers = [ticker.strip() for ticker in str(value).split(",") if ticker.strip()]
    return tickers or [""]


def _render_recent_news(news_df: pd.DataFrame) -> None:
    if news_df.empty:
        st.info(
            "No recent news found. Run `python scripts/refresh_news.py` to ingest catalyst headlines."
        )
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
    view["Published"] = to_et_naive_series(view["Published"]).dt.strftime("%Y-%m-%d %I:%M %p ET")
    view["Ticker"] = view["Tickers"].apply(_split_tickers)
    view = view.explode("Ticker")
    view["Ticker"] = _link_ticker_series(view["Ticker"])
    st.dataframe(
        view[["Published", "Headline", "Source", "Ticker", "Link"]],
        hide_index=True,
        width="stretch",
        column_config={
            **_ticker_link_column_config(),
            "Link": st.column_config.LinkColumn("Link", display_text="Open"),
        },
    )


def _render_recent_filings(filings_df: pd.DataFrame) -> None:
    if filings_df.empty:
        st.info(
            "No recent SEC filings found. Run `python scripts/refresh_filings.py` after setting SEC_USER_AGENT."
        )
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
    view["Ticker"] = _link_ticker_series(view["Ticker"])
    st.dataframe(
        view[["Filed", "Ticker", "Company", "Form", "Filing"]],
        hide_index=True,
        width="stretch",
        column_config={
            **_ticker_link_column_config(),
            "Filing": st.column_config.LinkColumn("Filing", display_text="Open"),
        },
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

    # Clean up empty or missing Fiscal Period values to display 'n/a'
    if "Fiscal Period" in view.columns:
        view["Fiscal Period"] = view["Fiscal Period"].fillna("n/a").replace("", "n/a")

    view["Ticker"] = _link_ticker_series(view["Ticker"])
    st.dataframe(
        view[["Date", "Ticker", "Company", "Fiscal Period", "Source"]],
        hide_index=True,
        width="stretch",
        column_config=_ticker_link_column_config(),
    )


def _render_theme_counts(theme_counts: object) -> None:
    if not isinstance(theme_counts, pd.DataFrame) or theme_counts.empty:
        return

    st.subheader("Theme Coverage")
    theme_counts_view = theme_counts.rename(
        columns={
            "theme_family": "Theme Family",
            "theme": "Theme",
            "company_count": "Companies",
        }
    )
    st.dataframe(
        theme_counts_view[["Theme Family", "Theme", "Companies"]],
        hide_index=True,
        width="stretch",
    )


def _render_macro_capex_context(context: object) -> None:
    if not isinstance(context, dict):
        return

    latest_yields = context.get("latest_yields") or {}
    inflation = context.get("inflation") or {}
    capex = context.get("capex") or {}
    has_data = any(
        [
            latest_yields.get("dgs10"),
            latest_yields.get("dgs30"),
            inflation.get("core_cpi_yoy") is not None,
            capex.get("latest_total") is not None,
        ]
    )

    st.subheader("Macro & Capex Pressure")
    if not has_data:
        st.info(
            "Macro context will appear after running `python scripts/refresh_macro.py` "
            "and adding quarterly hyperscaler capex observations."
        )
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(
        render_plain_metric_card("Pressure", context.get("pressure_label", "n/a")),
        unsafe_allow_html=True,
    )
    col2.markdown(
        render_plain_metric_card("10Y Treasury", _fmt_yield_obs(latest_yields.get("dgs10"))),
        unsafe_allow_html=True,
    )
    col3.markdown(
        render_plain_metric_card("Core CPI YoY", _fmt_plain_pct(inflation.get("core_cpi_yoy"))),
        unsafe_allow_html=True,
    )

    # Format the capex metric in the card using a YoY growth indicator
    capex_yoy = capex.get("capex_yoy")
    if capex_yoy is not None and not pd.isna(capex_yoy):
        yoy_str = f"{capex_yoy * 100:+.2f}%"
        color = "#3fb950" if capex_yoy > 0 else ("#f85149" if capex_yoy < 0 else "#8b949e")
        capex_val_display = f"{_fmt_currency(capex.get('latest_total'))} <span style='font-size: 14px; color: {color}; font-weight: 600;'>({yoy_str} YoY)</span>"
    else:
        capex_val_display = _fmt_currency(capex.get("latest_total"))

    col4.markdown(
        render_plain_metric_card("Hyperscaler Capex", capex_val_display),
        unsafe_allow_html=True,
    )
    st.caption(str(context.get("explanation") or ""))

    # Format the detailed macro and capex values like we do with company overview fundamentals (using HTML columns/bullet points list)
    st.write("")
    detail_col1, detail_col2 = st.columns(2)
    with detail_col1:
        st.markdown("**Treasury & Yields**")
        st.markdown(
            f"- **30Y Treasury:** {_fmt_yield_obs(latest_yields.get('dgs30'))}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"- **2Y Treasury:** {_fmt_yield_obs(latest_yields.get('dgs2'))}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"- **Fed Funds Rate:** {_fmt_yield_obs(latest_yields.get('fed_funds'))}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"- **10Y 1M Change:** {_fmt_bps_colored(latest_yields.get('dgs10_1m_bps'), positive_is_bad=True)}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"- **10Y 3M Change:** {_fmt_bps_colored(latest_yields.get('dgs10_3m_bps'), positive_is_bad=True)}",
            unsafe_allow_html=True,
        )
    with detail_col2:
        st.markdown("**Inflation & Capex**")
        st.markdown(
            f"- **CPI YoY:** {_fmt_pct_colored(inflation.get('cpi_yoy'), positive_is_bad=True)}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"- **PPI YoY:** {_fmt_pct_colored(inflation.get('ppi_yoy'), positive_is_bad=True)}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"- **Hyperscaler Capex:** {_fmt_currency(capex.get('latest_total'))}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"- **Capex YoY Growth:** {_fmt_pct_colored(capex.get('capex_yoy'))}",
            unsafe_allow_html=True,
        )


def render_dashboard() -> None:
    render_sidebar_navigation()
    st.title("Dashboard")

    if st.button("Refresh dashboard"):
        load_dashboard_data.clear()
        load_intraday_core_return.clear()
        load_index_data.clear()
        st.rerun()

    data = load_dashboard_data()
    latest_dates = data["latest_dates"]
    metrics_df: pd.DataFrame = data["latest_metrics"]

    last_price_refresh = parse_optional_datetime(latest_dates.get("last_price_refresh_at"))
    last_metrics_refresh = parse_optional_datetime(latest_dates.get("last_metrics_refresh_at"))
    last_news_refresh = parse_optional_datetime(latest_dates.get("last_news_refresh_at"))
    last_filings_refresh = parse_optional_datetime(latest_dates.get("last_filings_refresh_at"))
    last_macro_refresh = parse_optional_datetime(latest_dates.get("last_macro_refresh_at"))
    last_price_attempt = parse_optional_datetime(latest_dates.get("last_price_attempt_at"))
    last_metrics_attempt = parse_optional_datetime(latest_dates.get("last_metrics_attempt_at"))
    last_news_attempt = parse_optional_datetime(latest_dates.get("last_news_attempt_at"))
    last_filings_attempt = parse_optional_datetime(latest_dates.get("last_filings_attempt_at"))
    last_macro_attempt = parse_optional_datetime(latest_dates.get("last_macro_attempt_at"))
    latest_price_date = parse_optional_date(latest_dates.get("latest_price_date"))
    latest_intraday_price_time = parse_optional_datetime(
        latest_dates.get("latest_intraday_price_time")
    )
    latest_metrics_date = parse_optional_date(latest_dates.get("latest_metrics_date"))

    stale_reasons = build_stale_reasons(
        latest_price_date,
        latest_metrics_date,
        today=datetime.now(UTC).date(),
    )

    with st.expander("🩺 Data Health & API Status", expanded=bool(stale_reasons)):
        if stale_reasons:
            st.warning(
                "Data staleness warnings detected:\n" + "\n".join([f"- {r}" for r in stale_reasons])
            )
        else:
            st.success("All core data sets look fresh.")

        p_status = data["provider_status"]
        st.markdown(f"**Active Market Data Provider**: `{p_status['active_provider']}`")

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown("📈 **yfinance**:\n`Available (Default)`")
        c2.markdown(
            f"🦈 **Finnhub**:\n`{'Configured' if p_status['finnhub_available'] else 'Missing Key'}`"
        )
        c3.markdown(
            f"🕛 **Twelve Data**:\n`{'Configured' if p_status['twelvedata_available'] else 'Missing Key'}`"
        )
        c4.markdown(
            f"🏔️ **Alpha Vantage**:\n`{'Configured' if p_status['alphavantage_available'] else 'Missing Key'}`"
        )

        st.write("---")

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown(
                f"**Last Successful Price Refresh**: `{_format_dt_et(last_price_refresh)}`"
            )
            st.markdown(
                f"**Last Successful Metrics Computation**: `{_format_dt_et(last_metrics_refresh)}`"
            )
            st.markdown(
                f"**Last Successful News Refresh**: `{_format_dt_et(last_news_refresh)}`"
            )
            st.markdown(
                f"**Last Successful Filings Refresh**: `{_format_dt_et(last_filings_refresh)}`"
            )
            st.markdown(
                f"**Last Successful Macro Refresh**: `{_format_dt_et(last_macro_refresh)}`"
            )
        with col_t2:
            st.markdown(
                f"**Last Price Attempt**: `{_format_dt_et(last_price_attempt)}`"
            )
            st.markdown(
                f"**Last Metrics Attempt**: `{_format_dt_et(last_metrics_attempt)}`"
            )
            st.markdown(
                f"**Last News Attempt**: `{_format_dt_et(last_news_attempt)}`"
            )
            st.markdown(
                f"**Last Filings Attempt**: `{_format_dt_et(last_filings_attempt)}`"
            )
            st.markdown(
                f"**Last Macro Attempt**: `{_format_dt_et(last_macro_attempt)}`"
            )
            st.markdown(f"**Active Companies**: `{data['active_company_count']}`")
            st.markdown(f"**Stale Tickers (No recent prices)**: `{data['stale_tickers_count']}`")
            st.markdown(
                "**Latest 15m Price Bar**: "
                f"`{_format_dt_et(latest_intraday_price_time)}`"
            )
            st.markdown(f"**Missing/Stale 30m Tickers**: `{data['intraday_stale_tickers_count']}`")

        st.write("---")

        failed_job = data.get("failed_job")
        if failed_job:
            st.error(
                f"**Latest Failed Job**: `{failed_job['job_name']}`\n\n"
                f"**Finished At**: `{_format_dt_et(failed_job['finished_at'])}`\n\n"
                f"**Error**: `{failed_job['error_text']}`"
            )
        else:
            st.success("No failed background jobs found.")

    # Render Overview cards at the top
    st.subheader("📊 AI Infrastructure Core Overview")
    if metrics_df.empty:
        col1, col2, col3, col4 = st.columns(4)
        col1.markdown(
            render_plain_metric_card("Tracked Symbols", data.get("index_constituent_count")),
            unsafe_allow_html=True,
        )
        col2.markdown(render_metric_card("AI Infra Core 1D", None), unsafe_allow_html=True)
        col3.markdown(render_metric_card("AI Infra Core 1W", None), unsafe_allow_html=True)
        col4.markdown(render_metric_card("AI Infra Core 1M", None), unsafe_allow_html=True)
        st.write("---")

        # Render Macro & Capex context for empty metrics case
        _render_macro_capex_context(data.get("macro_capex_context"))
        st.write("---")

        st.subheader("Recent News")
        st.info("News feed will appear here after news ingestion is implemented.")
        st.subheader("Recent Filings")
        st.info("SEC filings will appear here after filings ingestion is implemented.")
        st.subheader("Upcoming Earnings")
        st.info("Earnings events will appear here after earnings ingestion is implemented.")
        _render_theme_counts(data.get("theme_counts"))
        return

    core_returns = summarize_core_returns(metrics_df)
    intraday_core_1d = load_intraday_core_return()
    core_1d = intraday_core_1d if intraday_core_1d is not None else core_returns["return_1d"]
    core_1w = core_returns["return_1w"]
    core_1m = core_returns["return_1m"]

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(
        render_plain_metric_card("Tracked Symbols", data.get("index_constituent_count")),
        unsafe_allow_html=True,
    )
    col2.markdown(render_metric_card("AI Infra Core 1D", core_1d), unsafe_allow_html=True)
    col3.markdown(render_metric_card("AI Infra Core 1W", core_1w), unsafe_allow_html=True)
    col4.markdown(render_metric_card("AI Infra Core 1M", core_1m), unsafe_allow_html=True)

    st.write("---")

    st.caption(
        "AI Infra Core is a simple equal-weight average excluding benchmarks, optional aggressive names, and Quantum Computing names."
    )

    # Render Index section
    st.subheader("📈 AI Infra Core Index Performance")

    tf = st.radio(
        "Chart Timeframe",
        ["1D", "5D", "1M", "3M", "6M", "1Y", "All"],
        index=5,
        horizontal=True,
        key="index_tf_radio",
    )
    index_data = load_index_data(tf)

    if not index_data or index_data.get("rel_df") is None or index_data["rel_df"].empty:
        st.info("No index price history available yet.")
    else:
        rel_df = index_data["rel_df"].copy()
        x_column = "date"
        if index_data.get("interval") == "15m":
            rel_df["date"] = to_et_naive_series(rel_df["date"])
            rel_df["date_label"] = pd.to_datetime(rel_df["date"]).dt.strftime(
                "%b %d, %Y %I:%M %p ET"
            )
            x_column = "date_label"
        import plotly.graph_objects as go

        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=rel_df[x_column],
                y=rel_df["index_level"],
                name="AI Infra Core Index",
                line=dict(color="#1f77b4", width=3),
            )
        )

        if "qqq_level" in rel_df:
            fig.add_trace(
                go.Scatter(
                    x=rel_df[x_column],
                    y=rel_df["qqq_level"],
                    name="QQQ (Benchmark)",
                    line=dict(color="#2ca02c", width=1.5, dash="dot"),
                )
            )

        if "nvda_level" in rel_df:
            fig.add_trace(
                go.Scatter(
                    x=rel_df[x_column],
                    y=rel_df["nvda_level"],
                    name="NVDA (Benchmark)",
                    line=dict(color="#9467bd", width=1.5, dash="dot"),
                )
            )

        fig.update_layout(
            title=f"AI Infra Core Index vs Benchmarks (Rebased to 100 on {rel_df['date'].min()})",
            xaxis_title="Market Time (ET)" if index_data.get("interval") == "15m" else "Date",
            yaxis_title="Normalized Level",
            template="plotly_white",
            margin=dict(l=40, r=40, t=40, b=40),
            height=400,
            hovermode="x unified",
        )
        if index_data.get("interval") == "15m":
            fig.update_traces(
                hovertemplate="%{y:.2f}<extra>%{fullData.name}</extra>"
            )
            apply_intraday_xaxis(fig, rel_df, tf)
        st.plotly_chart(fig, width="stretch")

        with st.expander("Methodology & Info"):
            st.markdown(
                f"""
                **AI Infra Core Index Methodology**
                - **Type**: Equal-weighted index of **{index_data["constituent_count"]}** AI infrastructure suppliers.
                - **Base Level**: 100.0 rebased dynamically to the start of the timeframe.
                - **Calculation**: Average daily return is calculated across all active constituents for each day, and cumulative returns are compounded daily.
                - **Missing History**: IPOs (e.g. {_ticker_markdown("GEV")}, {_ticker_markdown("ALAB")}) and tickers with missing history are handled dynamically by only calculating returns when daily price data exists.
                - **Exclusions**: Excludes benchmark-only names ({_ticker_markdown("QQQ")}, {_ticker_markdown("NVDA")}, {_ticker_markdown("MSFT")}, {_ticker_markdown("AMZN")}, {_ticker_markdown("GOOGL")}, {_ticker_markdown("META")}) and optional aggressive symbols ({_ticker_markdown("ALAB")}, {_ticker_markdown("CRDO")}) by default.
                - **Contributions**: Constituent return contributions are calculated as `Stock Period Return / N`. Due to daily rebalancing, the sum of these simple contributions may slightly deviate from the compounded cumulative return shown in the chart.
                """
            )

        st.subheader("🏆 Index Contributors & Detractors")
        c_tab1, c_tab2, c_tab3 = st.tabs(["1M Contributors", "3M Contributors", "YTD Contributors"])

        def _render_contributors_df(df: pd.DataFrame) -> None:
            if df.empty:
                st.info("No contribution data available for this period.")
                return
            df_view = df.copy()
            df_view["Return"] = df_view["return"].apply(lambda r: f"{r * 100:+.2f}%")
            df_view["Index Contribution"] = df_view["contribution"].apply(
                lambda c: f"{c * 100:+.2f}%"
            )
            df_view = df_view.rename(columns={"symbol": "Ticker", "name": "Company"})
            df_view["Ticker"] = _link_ticker_series(df_view["Ticker"])
            styled_df = df_view[["Ticker", "Company", "Return", "Index Contribution"]].style.map(
                style_positive_green_negative_red, subset=["Return", "Index Contribution"]
            )
            st.dataframe(
                styled_df,
                hide_index=True,
                width="stretch",
                column_config=_ticker_link_column_config(),
            )

        with c_tab1:
            left_col, right_col = st.columns(2)
            contrib_1m = index_data["contrib_1m"]
            with left_col:
                st.write("**Top 5 Positive Contributors (1M)**")
                if not contrib_1m.empty:
                    _render_contributors_df(contrib_1m.head(5))
                else:
                    st.info("No data")
            with right_col:
                st.write("**Top 5 Detractors (1M)**")
                if not contrib_1m.empty:
                    _render_contributors_df(contrib_1m.tail(5).iloc[::-1])
                else:
                    st.info("No data")

        with c_tab2:
            left_col, right_col = st.columns(2)
            contrib_3m = index_data["contrib_3m"]
            with left_col:
                st.write("**Top 5 Positive Contributors (3M)**")
                if not contrib_3m.empty:
                    _render_contributors_df(contrib_3m.head(5))
                else:
                    st.info("No data")
            with right_col:
                st.write("**Top 5 Detractors (3M)**")
                if not contrib_3m.empty:
                    _render_contributors_df(contrib_3m.tail(5).iloc[::-1])
                else:
                    st.info("No data")

        with c_tab3:
            left_col, right_col = st.columns(2)
            contrib_ytd = index_data["contrib_ytd"]
            with left_col:
                st.write("**Top 5 Positive Contributors (YTD)**")
                if not contrib_ytd.empty:
                    _render_contributors_df(contrib_ytd.head(5))
                else:
                    st.info("No data")
            with right_col:
                st.write("**Top 5 Detractors (YTD)**")
                if not contrib_ytd.empty:
                    _render_contributors_df(contrib_ytd.tail(5).iloc[::-1])
                else:
                    st.info("No data")

    st.write("---")

    # Render Macro & Capex section below Index contributors
    _render_macro_capex_context(data.get("macro_capex_context"))
    st.write("---")

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
            gainers_view = gainers.rename(
                columns={"symbol": "Ticker", "name": "Company", "return_1d": "1D %"}
            ).copy()
            gainers_view["Ticker"] = _link_ticker_series(gainers_view["Ticker"])
            gainers_view["1D %"] = gainers_view["1D %"].apply(_fmt_pct)
            styled_gainers = gainers_view[["Ticker", "Company", "1D %"]].style.map(
                style_positive_green_negative_red, subset=["1D %"]
            )
            st.dataframe(
                styled_gainers,
                hide_index=True,
                width="stretch",
                column_config=_ticker_link_column_config(),
            )
        st.subheader("Biggest Drawdowns From 52W High")
        if drawdowns.empty:
            st.info("No 52-week drawdown data available for the latest metrics date.")
        else:
            drawdowns_view = drawdowns.rename(
                columns={"symbol": "Ticker", "name": "Company", "drawdown_52w": "Drawdown %"}
            ).copy()
            drawdowns_view["Ticker"] = _link_ticker_series(drawdowns_view["Ticker"])
            drawdowns_view["Drawdown %"] = drawdowns_view["Drawdown %"].apply(_fmt_pct)
            styled_drawdowns = drawdowns_view[["Ticker", "Company", "Drawdown %"]].style.map(
                style_positive_green_negative_red, subset=["Drawdown %"]
            )
            st.dataframe(
                styled_drawdowns,
                hide_index=True,
                width="stretch",
                column_config=_ticker_link_column_config(),
            )
    with right:
        st.subheader("Top 5 Losers (1D)")
        if losers.empty:
            st.info("No 1D return data available for the latest metrics date.")
        else:
            losers_view = losers.rename(
                columns={"symbol": "Ticker", "name": "Company", "return_1d": "1D %"}
            ).copy()
            losers_view["Ticker"] = _link_ticker_series(losers_view["Ticker"])
            losers_view["1D %"] = losers_view["1D %"].apply(_fmt_pct)
            styled_losers = losers_view[["Ticker", "Company", "1D %"]].style.map(
                style_positive_green_negative_red, subset=["1D %"]
            )
            st.dataframe(
                styled_losers,
                hide_index=True,
                width="stretch",
                column_config=_ticker_link_column_config(),
            )
        st.subheader("RSI Below 40")
        if rsi_below_40.empty:
            st.info("No symbols with RSI below 40 on the latest metrics date.")
        else:
            rsi_view = rsi_below_40.rename(
                columns={"symbol": "Ticker", "name": "Company", "rsi_14": "RSI 14"}
            ).copy()
            rsi_view["Ticker"] = _link_ticker_series(rsi_view["Ticker"])
            rsi_view["RSI 14"] = rsi_view["RSI 14"].round(1)
            st.dataframe(
                rsi_view,
                hide_index=True,
                width="stretch",
                column_config=_ticker_link_column_config(),
            )

    st.subheader("Recent News")
    _render_recent_news(data["recent_news"])

    st.subheader("Recent Filings")
    _render_recent_filings(data["recent_filings"])

    st.subheader("Upcoming Earnings")
    _render_upcoming_earnings(data["upcoming_earnings"])

    _render_theme_counts(data.get("theme_counts"))


if os.environ.get("PYTEST_CURRENT_TEST") is None:
    # Only execute the Streamlit page render when not running under pytest.
    # Pytest imports this module for tests and should avoid executing UI code.
    render_dashboard()
