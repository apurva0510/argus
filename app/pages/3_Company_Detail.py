from __future__ import annotations

from datetime import datetime
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from app.components.sidebar import render_sidebar_navigation

from argus.analytics.market_hours import (
    MARKET_TZ,
    append_market_close_markers,
    filter_latest_market_sessions,
)
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
from html import escape
from textwrap import dedent
from app.auth_links import company_detail_url

get_relative_perf_df = build_relative_performance_frame


def _html(value: object) -> str:
    return escape("" if value is None or pd.isna(value) else str(value), quote=True)


def _html_block(markup: str) -> str:
    return "\n".join(line for line in dedent(markup).splitlines() if line.strip()).strip()


def _sentiment_badge(score: float | None) -> str:
    if score is None:
        return '<span style="background: rgba(139, 148, 158, 0.15); color: #8b949e; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Sentiment: N/A</span>'

    if score > 0.05:
        return f'<span style="background: rgba(63, 185, 80, 0.15); color: #3fb950; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Positive ({score:+.2f})</span>'
    elif score < -0.05:
        return f'<span style="background: rgba(248, 81, 73, 0.15); color: #f85149; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Negative ({score:.2f})</span>'
    else:
        return f'<span style="background: rgba(139, 148, 158, 0.15); color: #8b949e; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Neutral ({score:+.2f})</span>'


def _relevance_badge(score: float | None) -> str:
    if score is None:
        return '<span style="background: rgba(139, 148, 158, 0.15); color: #8b949e; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Relevance: N/A</span>'
    return f'<span style="background: rgba(56, 139, 253, 0.15); color: #58a6ff; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Relevance: {score * 100:.0f}%</span>'


def _ticker_badges(tickers_str: str | None) -> str:
    if not tickers_str:
        return ""
    badges = []
    for t in sorted(tickers_str.split(",")):
        t_clean = t.strip()
        if t_clean:
            ticker = escape(t_clean, quote=True)
            url = company_detail_url(t_clean)
            badges.append(
                f'<a href="{url}" target="_self" style="text-decoration: none; background: rgba(188, 140, 255, 0.15); color: #bc8cff; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-right: 4px;">{ticker}</a>'
            )
    return "".join(badges)


def _to_et(val) -> datetime | None:
    if val is None or pd.isna(val):
        return None
    try:
        dt = pd.to_datetime(val)
        if dt.tz is None:
            dt = dt.tz_localize("UTC")
        else:
            dt = dt.tz_convert("UTC")
        return dt.tz_convert("America/New_York")
    except Exception:
        return None


def _fmt_as_of_date(val) -> str:
    if val is None or pd.isna(val):
        return "n/a"
    try:
        dt = pd.to_datetime(val)
    except Exception:
        return str(val)
    if getattr(dt, "tzinfo", None) is not None:
        return dt.tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p ET")
    if isinstance(val, datetime) or (" " in str(val) or "T" in str(val)):
        return dt.tz_localize("UTC").tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p ET")
    return dt.strftime("%Y-%m-%d")


@st.cache_data(ttl=300)
def load_price_history(company_id: int, interval: str = "1d") -> pd.DataFrame:
    return get_company_price_history(company_id, interval=interval)


@st.cache_data(ttl=300)
def load_index_options() -> list[dict[str, object]]:
    from argus.core.app_engine import create_migrated_database_engine
    from argus.core.settings import settings
    from sqlalchemy.orm import sessionmaker
    from argus.analytics.index_builder import list_index_definitions

    engine = create_migrated_database_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        return [
            {"id": definition.id, "name": definition.name, "mode": definition.mode}
            for definition in list_index_definitions(session)
        ]


@st.cache_data(ttl=300)
def load_index_relative_returns(
    start_date,
    interval: str = "1d",
    index_definition_id: int | None = None,
) -> pd.DataFrame:
    from argus.core.app_engine import create_migrated_database_engine
    from argus.core.settings import settings
    from sqlalchemy.orm import sessionmaker
    from argus.analytics.index_builder import (
        calculate_relative_performance,
        calculate_weighted_index,
    )

    engine = create_migrated_database_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        interval = interval.strip().lower()
        index_df = calculate_weighted_index(
            session,
            definition_id=index_definition_id,
            interval=interval,
            use_precomputed=interval == "1d",
        )
        if index_df.empty:
            return pd.DataFrame()

        # Convert start_date from America/New_York naive datetime to UTC naive datetime for comparison in SQL/Pandas
        if interval == "15m" and start_date is not None:
            start_date_utc = (
                pd.to_datetime(start_date)
                .tz_localize("America/New_York")
                .tz_convert("UTC")
                .tz_localize(None)
                .to_pydatetime()
            )
        else:
            start_date_utc = start_date

        rel_df = calculate_relative_performance(
            session, index_df, start_date_utc, interval=interval
        )
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
    # Two literal dollar signs are parsed as inline LaTeX by st.markdown.
    return f"&#36;{low:.2f} - &#36;{high:.2f}"


def _interval_for_timeframe(tf: str) -> str:
    return "15m" if tf in {"1D", "5D"} else "1d"


def _start_for_timeframe(latest_point, earliest_point, tf: str):
    latest_ts = pd.to_datetime(latest_point)
    if tf == "1D":
        return latest_ts - pd.Timedelta(days=1)
    if tf == "5D":
        return latest_ts - pd.Timedelta(days=5)
    if tf == "1M":
        return (latest_ts - pd.Timedelta(days=30)).date()
    if tf == "3M":
        return (latest_ts - pd.Timedelta(days=90)).date()
    if tf == "6M":
        return (latest_ts - pd.Timedelta(days=180)).date()
    if tf == "1Y":
        return (latest_ts - pd.Timedelta(days=365)).date()
    return earliest_point


def _filter_price_timeframe(
    df: pd.DataFrame, tf: str, interval: str
) -> tuple[pd.DataFrame, object]:
    if df.empty:
        return df, None

    df_sorted = df.sort_values("date").copy()
    if interval == "15m" and tf in {"1D", "5D"}:
        filtered = filter_latest_market_sessions(
            df_sorted, 1 if tf == "1D" else 5, naive_tz=MARKET_TZ
        )
        if filtered.empty:
            return filtered, None
        return filtered, filtered["date"].min()

    latest_date = df_sorted["date"].max()
    start_date = _start_for_timeframe(latest_date, df_sorted["date"].min(), tf)
    return df_sorted[df_sorted["date"] >= start_date], start_date


def _maybe_append_close_bar(
    df_intraday: pd.DataFrame,
    df_daily: pd.DataFrame,
    tf: str,
) -> pd.DataFrame:
    """Append a synthetic 4:00 PM ET closing bar for the 1D view.

    yfinance 15-minute data ends at 3:45 PM ET.  When the session is
    complete (i.e. not today), we splice in the official daily adj_close
    at 16:00 so the chart extends to market close.
    """
    if tf != "1D" or df_intraday.empty or df_daily.empty:
        return df_intraday

    from datetime import time as dt_time
    from zoneinfo import ZoneInfo

    _et = ZoneInfo("America/New_York")

    last_bar = pd.to_datetime(df_intraday["date"].max())
    # Only inject when the final 15m bar is at 3:45 PM (session complete)
    if last_bar.time() != dt_time(15, 45):
        return df_intraday

    session_date = last_bar.date()

    # Do not inject for a live/in-progress session (today in ET)
    today_et = pd.Timestamp.now(tz=_et).date()
    if session_date >= today_et:
        return df_intraday

    # Look up the daily close for that session date
    df_daily_copy = df_daily.copy()
    df_daily_copy["_date"] = pd.to_datetime(df_daily_copy["date"]).dt.date
    match = df_daily_copy[df_daily_copy["_date"] == session_date]
    if match.empty:
        return df_intraday

    close_price = float(match.iloc[-1]["adj_close"])
    close_ts = pd.Timestamp(session_date.year, session_date.month, session_date.day, 16, 0)

    close_row = {col: None for col in df_intraday.columns}
    close_row["date"] = close_ts
    close_row["adj_close"] = close_price

    return pd.concat([df_intraday, pd.DataFrame([close_row])], ignore_index=True)


def apply_intraday_xaxis(fig: go.Figure, df_or_interval, tf: str | None = None) -> None:
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
        _1d_ticks = {"09:30", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"}
        for i, dt in enumerate(dates_ny):
            if dt.strftime("%H:%M") in _1d_ticks:
                tickvals.append(df.iloc[i][tick_value_column])
                ticktext.append(dt.strftime("%I:%M %p").lstrip("0"))
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


def _latest_price_from_history(daily_prices: pd.DataFrame, intraday_prices: pd.DataFrame):
    if not intraday_prices.empty:
        intraday_dates = pd.to_datetime(intraday_prices["date"])
        latest_intraday_idx = intraday_dates.idxmax()
        latest_intraday_date = intraday_dates.loc[latest_intraday_idx].date()
        if daily_prices.empty:
            return intraday_prices.loc[latest_intraday_idx, "adj_close"]
        latest_daily_date = pd.to_datetime(daily_prices["date"]).max().date()
        if latest_intraday_date >= latest_daily_date:
            return intraday_prices.loc[latest_intraday_idx, "adj_close"]

    if not daily_prices.empty:
        daily_dates = pd.to_datetime(daily_prices["date"])
        latest_daily_idx = daily_dates.idxmax()
        return daily_prices.loc[latest_daily_idx, "adj_close"]
    return None


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

    # Custom styling for unified card feed (matching news and filings page)
    st.markdown(
        """
        <style>
        .feed-card {
            background: rgba(22, 27, 34, 0.4);
            border: 1px solid rgba(240, 246, 252, 0.1);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            transition: transform 0.2s, border-color 0.2s;
        }
        .feed-card:hover {
            border-color: rgba(56, 139, 253, 0.4);
        }
        .feed-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            border-bottom: 1px solid rgba(240, 246, 252, 0.05);
            padding-bottom: 8px;
        }
        .feed-title {
            font-size: 18px;
            font-weight: 600;
            margin: 0 0 8px 0;
        }
        .feed-meta {
            font-size: 13px;
            color: #8b949e;
            margin-bottom: 10px;
        }
        .feed-summary {
            font-size: 14px;
            color: #c9d1d9;
            margin-bottom: 12px;
            line-height: 1.5;
        }
        .feed-badges {
            display: flex;
            gap: 6px;
            align-items: center;
            flex-wrap: wrap;
        }
        .type-badge-news {
            background: rgba(56, 139, 253, 0.2);
            color: #58a6ff;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
            padding: 2px 6px;
            border-radius: 4px;
        }
        .type-badge-filing {
            background: rgba(219, 109, 40, 0.2);
            color: #f78166;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
            padding: 2px 6px;
            border-radius: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

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
    df_daily_price = load_price_history(company["id"], "1d").copy()
    df_intraday_price = load_price_history(company["id"], "15m").copy()
    if not df_intraday_price.empty:
        dates = pd.to_datetime(df_intraday_price["date"])
        if dates.dt.tz is None:
            dates = dates.dt.tz_localize("UTC")
        else:
            dates = dates.dt.tz_convert("UTC")
        df_intraday_price["date"] = dates.dt.tz_convert("America/New_York").dt.tz_localize(None)
    latest_price = _latest_price_from_history(df_daily_price, df_intraday_price)
    if not df_intraday_price.empty:
        df_intraday_price["date"] = pd.to_datetime(df_intraday_price["date"])
    if not df_daily_price.empty:
        df_daily_price["date"] = pd.to_datetime(df_daily_price["date"]).dt.date

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
        # Timeframe selector
        tf = st.radio(
            "Timeframe",
            ["1D", "5D", "1M", "3M", "6M", "1Y", "All"],
            index=5,
            horizontal=True,
            key="timeframe_radio",
        )

        chart_tabs = st.tabs(["Price Chart", "Relative Performance"])

        with chart_tabs[0]:
            interval = _interval_for_timeframe(tf)
            df_price = (df_intraday_price if interval == "15m" else df_daily_price).copy()

            if df_price.empty:
                st.info("No price history available for this company.")
            else:
                # Calculate rolling MAs on entire history first, so they are accurate at the beginning of the plot
                df_chart = df_price.sort_values("date").copy()
                if interval == "1d":
                    df_chart["50DMA"] = df_chart["adj_close"].rolling(50).mean()
                    df_chart["200DMA"] = df_chart["adj_close"].rolling(200).mean()

                df_filtered, _start_date = _filter_price_timeframe(df_chart, tf, interval)

                if df_filtered.empty:
                    st.info("No regular-market price history available for this timeframe.")
                else:
                    if interval == "15m":
                        df_filtered = append_market_close_markers(
                            df_filtered,
                            df_daily_price,
                            value_columns=["adj_close"],
                            timeframe=tf,
                        )

                    x_column = "date"
                    if interval == "15m":
                        df_filtered = df_filtered.copy()
                        df_filtered["date_label"] = pd.to_datetime(df_filtered["date"]).dt.strftime(
                            "%b %d, %Y %I:%M %p ET"
                        )
                        x_column = "date_label"

                    # Plotly Chart
                    fig = go.Figure()
                    fig.add_trace(
                        go.Scatter(
                            x=df_filtered[x_column],
                            y=df_filtered["adj_close"],
                            name="Adj Close",
                            line=dict(color="#1f77b4", width=2.5),
                        )
                    )

                    # Overlay moving averages for daily ranges only.
                    if interval == "1d" and not df_filtered["50DMA"].isna().all():
                        fig.add_trace(
                            go.Scatter(
                                x=df_filtered["date"],
                                y=df_filtered["50DMA"],
                                name="50 DMA",
                                line=dict(color="#ff7f0e", width=1.5, dash="dash"),
                            )
                        )
                    if interval == "1d" and not df_filtered["200DMA"].isna().all():
                        fig.add_trace(
                            go.Scatter(
                                x=df_filtered["date"],
                                y=df_filtered["200DMA"],
                                name="200 DMA",
                                line=dict(color="#d62728", width=1.5, dash="dash"),
                            )
                        )

                    fig.update_layout(
                        title=f"{company['symbol']} {'Intraday' if interval == '15m' else 'Historical'} Price",
                        xaxis_title="Market Time (ET)" if interval == "15m" else "Date",
                        yaxis_title="Price ($)",
                        template="plotly_white",
                        margin=dict(l=40, r=40, t=40, b=40),
                        height=450,
                        hovermode="x unified",
                    )
                    apply_intraday_xaxis(fig, df_filtered, tf)
                    st.plotly_chart(fig, width="stretch")

        with chart_tabs[1]:
            st.write("### Relative Return Comparison")
            interval = _interval_for_timeframe(tf)
            df_price = (df_intraday_price if interval == "15m" else df_daily_price).copy()
            if df_price.empty:
                st.info("No price history available to calculate relative performance.")
            else:
                df_price, start_date = _filter_price_timeframe(df_price, tf, interval)
                if df_price.empty or start_date is None:
                    st.info("No price history available to calculate relative performance.")
                    rel_df = pd.DataFrame()
                else:
                    # Fetch QQQ and NVDAclose
                    qqq_comp = get_company_by_symbol("QQQ")
                    nvda_comp = get_company_by_symbol("NVDA")
                    df_qqq = (
                        load_price_history(qqq_comp["id"], interval).copy()
                        if qqq_comp
                        else pd.DataFrame()
                    )
                    df_nvda = (
                        load_price_history(nvda_comp["id"], interval).copy()
                        if nvda_comp
                        else pd.DataFrame()
                    )

                    if not df_qqq.empty:
                        df_qqq["date"] = pd.to_datetime(df_qqq["date"])
                        if interval == "15m":
                            dates = pd.to_datetime(df_qqq["date"])
                            if dates.dt.tz is None:
                                dates = dates.dt.tz_localize("UTC")
                            else:
                                dates = dates.dt.tz_convert("UTC")
                            df_qqq["date"] = dates.dt.tz_convert("America/New_York").dt.tz_localize(
                                None
                            )
                        elif interval == "1d":
                            df_qqq["date"] = df_qqq["date"].dt.date
                    if not df_nvda.empty:
                        df_nvda["date"] = pd.to_datetime(df_nvda["date"])
                        if interval == "15m":
                            dates = pd.to_datetime(df_nvda["date"])
                            if dates.dt.tz is None:
                                dates = dates.dt.tz_localize("UTC")
                            else:
                                dates = dates.dt.tz_convert("UTC")
                            df_nvda["date"] = dates.dt.tz_convert(
                                "America/New_York"
                            ).dt.tz_localize(None)
                        elif interval == "1d":
                            df_nvda["date"] = df_nvda["date"].dt.date

                    rel_df = get_relative_perf_df(df_price, df_qqq, df_nvda, start_date)

                if rel_df.empty:
                    st.info("No overlapping data found for this timeframe.")
                else:
                    x_column = "date"
                    if interval == "15m":
                        rel_df = rel_df.copy()
                        rel_df["date_label"] = pd.to_datetime(rel_df["date"]).dt.strftime(
                            "%b %d, %Y %I:%M %p ET"
                        )
                        x_column = "date_label"

                    index_options = load_index_options()
                    selected_index_id = None
                    selected_index_name = "AI Infra Core Index"
                    if index_options:
                        selected_index_name = st.selectbox(
                            "Index Comparison",
                            [str(option["name"]) for option in index_options],
                            index=0,
                            key="detail_index_selectbox",
                        )
                        selected_index = next(
                            option
                            for option in index_options
                            if option["name"] == selected_index_name
                        )
                        selected_index_id = int(selected_index["id"])

                    fig_rel = go.Figure()
                    fig_rel.add_trace(
                        go.Scatter(
                            x=rel_df[x_column],
                            y=rel_df["comp_ret"],
                            name=company["symbol"],
                            line=dict(color="#1f77b4", width=2.5),
                        )
                    )
                    if "qqq_ret" in rel_df:
                        fig_rel.add_trace(
                            go.Scatter(
                                x=rel_df[x_column],
                                y=rel_df["qqq_ret"],
                                name="QQQ (Benchmark)",
                                line=dict(color="#2ca02c", width=1.5, dash="dot"),
                            )
                        )
                    if "nvda_ret" in rel_df:
                        fig_rel.add_trace(
                            go.Scatter(
                                x=rel_df[x_column],
                                y=rel_df["nvda_ret"],
                                name="NVDA (Benchmark)",
                                line=dict(color="#9467bd", width=1.5, dash="dot"),
                            )
                        )

                    # Real AI Infra Core Index
                    idx_rel = load_index_relative_returns(
                        start_date,
                        interval,
                        selected_index_id,
                    ).copy()
                    if not idx_rel.empty and "index_ret" in idx_rel:
                        if interval == "15m":
                            dates = pd.to_datetime(idx_rel["date"])
                            if dates.dt.tz is None:
                                dates = dates.dt.tz_localize("UTC")
                            else:
                                dates = dates.dt.tz_convert("UTC")
                            idx_rel["date"] = dates.dt.tz_convert(
                                "America/New_York"
                            ).dt.tz_localize(None)

                        # Merge onto rel_df to align timestamps perfectly
                        aligned_idx = pd.merge(
                            rel_df[["date"]],
                            idx_rel[["date", "index_ret"]],
                            on="date",
                            how="left",
                        )
                        aligned_idx["index_ret"] = aligned_idx["index_ret"].ffill()

                        if not aligned_idx["index_ret"].isna().all():
                            fig_rel.add_trace(
                                go.Scatter(
                                    x=rel_df[x_column],
                                    y=aligned_idx["index_ret"],
                                    name=selected_index_name,
                                    line=dict(color="#7f7f7f", width=2.0, dash="dash"),
                                )
                            )

                    fig_rel.update_layout(
                        title=f"Relative Cumulative Return vs Benchmarks (Start Date: {start_date})",
                        xaxis_title="Market Time (ET)" if interval == "15m" else "Date",
                        yaxis_title="Return (%)",
                        template="plotly_white",
                        margin=dict(l=40, r=40, t=40, b=40),
                        height=450,
                        hovermode="x unified",
                    )
                    apply_intraday_xaxis(fig_rel, rel_df, tf)
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
            load_index_options.clear()
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
                load_index_options.clear()
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
                created_at_et = _to_et(note["created_at"])
                dt_str = created_at_et.strftime("%Y-%m-%d %I:%M %p ET") if created_at_et else "n/a"
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
                    f"- **As of Date:** {_fmt_as_of_date(fundamentals.get('as_of_date'))}",
                    unsafe_allow_html=True,
                )

    with bottom_tabs[1]:
        news_items = load_company_news(company["id"])
        if not news_items:
            st.info("No recent news articles found in database.")
        else:
            for item in news_items:
                published_at_et = _to_et(item["published_at"])
                time_str = (
                    published_at_et.strftime("%b %d, %Y %I:%M %p ET")
                    if published_at_et
                    else "Unknown time"
                )
                sentiment_html = _sentiment_badge(item.get("sentiment_score"))
                relevance_html = _relevance_badge(item.get("relevance_score"))
                tickers_html = _ticker_badges(item.get("tickers"))
                title = _html(item["title"])
                summary = _html(item["summary"])
                source_name = _html(item["source_name"] or "Unknown")
                provider = _html(item.get("provider") or "yfinance").upper()
                url = _html(item["url"])

                st.markdown(
                    _html_block(
                        f"""
                    <div class="feed-card">
                        <div class="feed-header">
                            <div>
                                <span class="type-badge-news">News</span>
                                <span style="margin-left: 8px; font-weight: bold; color: #58a6ff;">{source_name}</span>
                            </div>
                            <span style="font-size: 13px; color: #8b949e;">{time_str}</span>
                        </div>
                        <div class="feed-title"><a href="{url}" target="_blank" style="color: #c9d1d9; text-decoration: none;">{title}</a></div>
                        <div class="feed-summary">{summary}</div>
                        <div class="feed-badges">
                            {tickers_html}
                            {sentiment_html}
                            {relevance_html}
                            <span style="font-size: 12px; color: #8b949e; margin-left: auto;">Provider: {provider}</span>
                        </div>
                    </div>
                    """
                    ),
                    unsafe_allow_html=True,
                )

    with bottom_tabs[2]:
        filings = load_company_filings(company["id"])
        if not filings:
            st.info("No SEC filings found in database.")
        else:
            for f in filings:
                if f.get("acceptance_datetime") is not None:
                    ts = _to_et(f["acceptance_datetime"])
                else:
                    ts = (
                        _to_et(datetime.combine(f["filing_date"], datetime.min.time()))
                        if f["filing_date"]
                        else None
                    )

                time_str = (
                    ts.strftime("%b %d, %Y %I:%M %p ET")
                    if ts
                    else (
                        f["filing_date"].strftime("%b %d, %Y")
                        if f["filing_date"]
                        else "Unknown date"
                    )
                )

                now_ny = pd.Timestamp.now(tz="America/New_York").to_pydatetime()
                is_new = (now_ny - ts) <= pd.Timedelta(hours=24) if ts is not None else False
                new_star = (
                    "⭐ <span style='color: #f2c94c; font-weight: bold; font-size: 12px; margin-right: 8px;'>NEW</span>"
                    if is_new
                    else ""
                )

                ticker = _html(company["symbol"])
                company_name = _html(company["name"])
                form = _html(f["form"])
                filing_detail_url = _html(f["filing_detail_url"] or "#")
                primary_doc_url = _html(f["primary_doc_url"] or "#")
                url = company_detail_url(company["symbol"])
                ticker_badge = f'<a href="{url}" target="_self" style="text-decoration: none; background: rgba(188, 140, 255, 0.15); color: #bc8cff; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-right: 8px;">{ticker}</a>'
                raw_document_link = (
                    f'<a href="{primary_doc_url}" target="_blank" style="background: rgba(139, 148, 158, 0.15); color: #c9d1d9; padding: 4px 12px; border-radius: 4px; font-size: 13px; text-decoration: none; font-weight: 600;">Raw SEC Document</a>'
                    if f["primary_doc_url"]
                    else ""
                )

                st.markdown(
                    _html_block(
                        f"""
                    <div class="feed-card">
                        <div class="feed-header">
                            <div>
                                <span class="type-badge-filing">SEC Filing</span>
                                <span style="margin-left: 8px; font-weight: bold; color: #f78166;">{form}</span>
                            </div>
                            <span style="font-size: 13px; color: #8b949e;">{time_str}</span>
                        </div>
                        <div class="feed-title" style="color: #c9d1d9;">
                            {new_star}
                            {ticker_badge}
                            <strong>{company_name}</strong>
                        </div>
                        <div class="feed-summary">Official {form} filing submitted to the SEC.</div>
                        <div class="feed-badges">
                            <a href="{filing_detail_url}" target="_blank" style="background: rgba(56, 139, 253, 0.15); color: #58a6ff; padding: 4px 12px; border-radius: 4px; font-size: 13px; text-decoration: none; font-weight: 600;">SEC Filing Page</a>
                            {raw_document_link}
                        </div>
                    </div>
                    """
                    ),
                    unsafe_allow_html=True,
                )


if __name__ == "__main__":
    render_company_detail()
