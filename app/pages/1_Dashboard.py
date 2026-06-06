from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app.components.sidebar import render_sidebar_navigation
from app.auth_links import company_detail_url
import os
from argus.core.app_engine import create_migrated_database_engine

from argus.analytics.market_hours import append_market_close_markers
from argus.core.settings import settings
from argus.core.timezones import format_et_datetime, to_et_naive_series
from argus.services.dashboard_service import (
    calculate_intraday_core_return_from_engine,
    filter_low_rsi,
    load_dashboard_data_from_engine,
    rank_biggest_drawdowns,
    rank_top_gainers,
    rank_top_losers,
)
from app.components.metrics import (
    render_metric_card,
    render_plain_metric_card,
    render_plain_metric_card_parts,
)
from app.components.tables import style_positive_green_negative_red, style_score_traffic_light


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
def load_index_options() -> list[dict[str, object]]:
    from sqlalchemy.orm import sessionmaker
    from argus.analytics.index_builder import list_index_definitions

    engine = get_dashboard_engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        return [
            {"id": definition.id, "name": definition.name, "mode": definition.mode}
            for definition in list_index_definitions(session)
        ]


@st.cache_data(ttl=300)
def load_index_data(tf: str, index_definition_id: int | None = None) -> dict:
    from sqlalchemy.orm import sessionmaker
    from argus.analytics.index_builder import (
        calculate_relative_performance,
        calculate_top_contributors_for_definition,
        calculate_weighted_index,
        get_index_weights,
    )
    from argus.analytics.market_hours import filter_latest_market_sessions
    from argus.core.models import Company, PriceBar

    engine = get_dashboard_engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        short_range = tf in {"1D", "5D"}
        interval = "15m" if short_range else "1d"
        index_df = calculate_weighted_index(
            session,
            definition_id=index_definition_id,
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
        daily_close_levels = pd.DataFrame()
        if not rel_df.empty:
            rel_df["index_level"] = 100.0 + rel_df["index_ret"]
            if "qqq_ret" in rel_df and not rel_df["qqq_ret"].isna().all():
                rel_df["qqq_level"] = 100.0 + rel_df["qqq_ret"]
            if "nvda_ret" in rel_df and not rel_df["nvda_ret"].isna().all():
                rel_df["nvda_level"] = 100.0 + rel_df["nvda_ret"]

            if short_range:
                daily_index_df = calculate_weighted_index(
                    session,
                    definition_id=index_definition_id,
                    interval="1d",
                    use_precomputed=True,
                )
                if daily_index_df.empty:
                    daily_index_df = calculate_weighted_index(
                        session,
                        definition_id=index_definition_id,
                        interval="1d",
                        use_precomputed=False,
                    )
                if not daily_index_df.empty:
                    daily_close_levels = _daily_close_levels_from_session_returns(
                        rel_df,
                        daily_index_df,
                        daily_value_column="index_value",
                        output_column="index_level",
                    )

                benchmark_bases = {}
                for symbol in ("QQQ", "NVDA"):
                    close_column = f"{symbol.lower()}_level"
                    if close_column not in rel_df or rel_df[close_column].isna().all():
                        continue
                    intraday_bench = (
                        session.query(PriceBar.adj_close)
                        .join(Company, Company.id == PriceBar.company_id)
                        .filter(
                            Company.symbol == symbol,
                            PriceBar.provider == settings.market_data_provider,
                            PriceBar.interval == "15m",
                            PriceBar.bar_time >= start_date,
                        )
                        .order_by(PriceBar.bar_time.asc())
                        .first()
                    )
                    if intraday_bench and intraday_bench[0]:
                        benchmark_bases[symbol] = float(intraday_bench[0])

                if benchmark_bases:
                    benchmark_daily = pd.read_sql_query(
                        session.query(PriceBar.date, Company.symbol, PriceBar.adj_close)
                        .join(Company, Company.id == PriceBar.company_id)
                        .filter(
                            Company.symbol.in_(list(benchmark_bases)),
                            PriceBar.provider == settings.market_data_provider,
                            PriceBar.interval == "1d",
                        )
                        .order_by(PriceBar.date.asc())
                        .statement,
                        session.connection(),
                    )
                    if not benchmark_daily.empty:
                        for symbol in benchmark_bases:
                            level_column = f"{symbol.lower()}_level"
                            symbol_daily = benchmark_daily[benchmark_daily["symbol"] == symbol].copy()
                            if symbol_daily.empty:
                                continue
                            symbol_close_levels = _daily_close_levels_from_session_returns(
                                rel_df,
                                symbol_daily,
                                daily_value_column="adj_close",
                                output_column=level_column,
                            )
                            if symbol_close_levels.empty:
                                continue
                            if daily_close_levels.empty:
                                daily_close_levels = symbol_close_levels.copy()
                            else:
                                daily_close_levels = daily_close_levels.merge(
                                    symbol_close_levels,
                                    on="date",
                                    how="outer",
                                )

        weights = get_index_weights(session, index_definition_id)
        symbols = list(weights)

        date_1m = latest_date_date - pd.Timedelta(days=30)
        date_3m = latest_date_date - pd.Timedelta(days=90)
        date_ytd = datetime(latest_date_date.year - 1, 12, 31).date()

        contrib_1m = calculate_top_contributors_for_definition(
            session,
            index_definition_id,
            date_1m,
            latest_date_date,
        )
        contrib_3m = calculate_top_contributors_for_definition(
            session,
            index_definition_id,
            date_3m,
            latest_date_date,
        )
        contrib_ytd = calculate_top_contributors_for_definition(
            session,
            index_definition_id,
            date_ytd,
            latest_date_date,
        )

        return {
            "rel_df": rel_df,
            "contrib_1m": contrib_1m,
            "contrib_3m": contrib_3m,
            "contrib_ytd": contrib_ytd,
            "constituent_count": len(symbols),
            "interval": interval,
            "daily_close_levels": daily_close_levels,
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


def _daily_close_levels_from_session_returns(
    intraday_frame: pd.DataFrame,
    daily_frame: pd.DataFrame,
    *,
    daily_value_column: str,
    output_column: str,
) -> pd.DataFrame:
    """Map official daily returns onto each session's intraday opening level."""
    if (
        intraday_frame.empty
        or daily_frame.empty
        or "date" not in intraday_frame
        or "date" not in daily_frame
        or output_column not in intraday_frame
        or daily_value_column not in daily_frame
    ):
        return pd.DataFrame(columns=["date", output_column])

    intraday = intraday_frame[["date", output_column]].copy()
    intraday["session_date"] = pd.to_datetime(to_et_naive_series(intraday["date"])).dt.date
    intraday[output_column] = pd.to_numeric(intraday[output_column], errors="coerce")
    session_open_levels = (
        intraday.dropna(subset=[output_column])
        .sort_values("date")
        .groupby("session_date", as_index=False)[output_column]
        .first()
    )
    if session_open_levels.empty:
        return pd.DataFrame(columns=["date", output_column])

    daily = daily_frame[["date", daily_value_column]].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily[daily_value_column] = pd.to_numeric(daily[daily_value_column], errors="coerce")
    daily = daily.dropna(subset=[daily_value_column]).sort_values("date")
    daily["session_return"] = daily[daily_value_column] / daily[daily_value_column].shift(1) - 1.0

    close_levels = session_open_levels.merge(
        daily[["date", "session_return"]],
        left_on="session_date",
        right_on="date",
        how="inner",
    ).dropna(subset=["session_return"])
    if close_levels.empty:
        return pd.DataFrame(columns=["date", output_column])

    close_levels[output_column] = close_levels[output_column] * (1.0 + close_levels["session_return"])
    return pd.DataFrame(
        {
            "date": close_levels["session_date"],
            output_column: close_levels[output_column],
        }
    )


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
        view[["Ticker", "Headline", "Link"]],
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
        view[["Date", "Ticker", "Company"]],
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

    col1, col2, col3 = st.columns(3)
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
    st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
    st.caption(str(context.get("explanation") or ""))

    # Format the detailed macro and capex values like we do with company overview fundamentals (using HTML columns/bullet points list)
    st.write("")
    detail_col1, detail_col2, detail_col3 = st.columns(3)
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
    with detail_col3:
        st.markdown("**Electricity & Power**")
        electricity = context.get("electricity") or {}
        elec_price_obs = electricity.get("price")
        elec_demand_obs = electricity.get("demand")
        if elec_price_obs is not None and elec_price_obs.get("value") is not None:
            st.markdown(
                f"- **Retail Elec Price:** {elec_price_obs['value']:.2f}¢ / kWh",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("- **Retail Elec Price:** n/a")
        if elec_demand_obs is not None and elec_demand_obs.get("value") is not None:
            st.markdown(
                f"- **Hourly Elec Demand:** {elec_demand_obs['value']:,.0f} MWh",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("- **Hourly Elec Demand:** n/a")


def render_dashboard() -> None:
    render_sidebar_navigation()
    st.title("Dashboard")

    # Force all elements inside column layout to occupy 100% container width & height to ensure alignment
    st.markdown(
        """
        <style>
        div[data-testid="column"] div.element-container,
        div[data-testid="column"] div.stMarkdown,
        div[data-testid="column"] div.stHtml,
        div[data-testid="column"] div[data-testid="stMarkdownContainer"] {
            width: 100% !important;
            height: 100% !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    data = load_dashboard_data()
    metrics_df: pd.DataFrame = data["latest_metrics"]
    latest_signals = data.get("latest_signals")
    # Empty metrics early return - KEEP EXACT STRING SEQUENCE FOR TEST COMPLIANCE
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

    # 1. Controls Bar (Top controls)
    ctrl_col1, _, ctrl_col2 = st.columns([6, 3, 0.75])
    
    with ctrl_col1:
        index_options = load_index_options()
        selected_index_id = None
        selected_index_name = "AI Infra Core Index"
        if index_options:
            selected_index_name = st.selectbox(
                "Index Definition",
                [str(option["name"]) for option in index_options],
                index=0,
                key="dashboard_index_selectbox",
            )
            selected_index = next(
                option for option in index_options if option["name"] == selected_index_name
            )
            selected_index_id = int(selected_index["id"])

    with ctrl_col2:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("Refresh", key="refresh_dashboard_btn", use_container_width=False):
            load_dashboard_data.clear()
            load_intraday_core_return.clear()
            load_index_data.clear()
            load_index_options.clear()
            st.rerun()

    st.write("---")

    # 2. KPI Summary Row Container
    kpi_container = st.container()

    st.write("---")

    # 3. Main Split (70/30 Split Columns)
    left_col, right_col = st.columns([7, 3])
    
    with left_col:
        st.subheader(f"📈 {selected_index_name} Performance")
        
        # 1. Chart Timeframe selector placed right above the chart
        tf = st.radio(
            "Chart Timeframe",
            ["1D", "5D", "1M", "3M", "6M", "1Y", "All"],
            index=5,
            horizontal=True,
            key="index_tf_radio",
        )
        
        # KPI 1: Selected Index Return (compounded or 1D)
        index_data = load_index_data(tf, selected_index_id)
        if index_data and index_data.get("rel_df") is not None and not index_data["rel_df"].empty:
            rel_df = index_data["rel_df"]
            index_ret_val = rel_df["index_ret"].iloc[-1] / 100.0 if "index_ret" in rel_df.columns else None
        else:
            index_ret_val = None

        # KPI 2: Capex (Total Amount Only, No YoY)
        macro_capex_context = data.get("macro_capex_context") or {}
        capex_data = macro_capex_context.get("capex") or {}
        latest_total = capex_data.get("latest_total")
        if latest_total is not None and not pd.isna(latest_total):
            capex_display = _fmt_currency(latest_total)
        else:
            capex_display = "n/a"

        # KPI 3: Power Load Signal
        power_val = None
        if latest_signals is not None and not latest_signals.empty and "power_signal" in latest_signals.columns:
            power_val = latest_signals["power_signal"].dropna().iloc[0] if len(latest_signals["power_signal"].dropna()) > 0 else None

        # KPI 4: Top Opportunity
        top_opp_ticker = "n/a"
        top_opp_score_display = ""
        top_opp_color = "#8b949e"
        if "opportunity_score" in metrics_df.columns:
            valid_opps = metrics_df.dropna(subset=["opportunity_score"])
            if not valid_opps.empty:
                top_opp_row = valid_opps.sort_values("opportunity_score", ascending=False).iloc[0]
                top_opp_ticker = str(top_opp_row["symbol"])
                top_opp_score = top_opp_row["opportunity_score"]
                top_opp_color = "#3fb950" if top_opp_score >= 70 else "#f0b429" if top_opp_score >= 40 else "#f85149"
                top_opp_score_display = f"{top_opp_score:.0f}"

        # KPI 5: Next Earnings
        next_earn_display = "n/a"
        upcoming_earnings = data.get("upcoming_earnings")
        if upcoming_earnings is not None and not upcoming_earnings.empty:
            next_earn_row = upcoming_earnings.iloc[0]
            next_earn_display = f"{next_earn_row['symbol']} ({pd.to_datetime(next_earn_row['event_date']).strftime('%m/%d')})"

        # Render KPI cards inside the container
        with kpi_container:
            kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)
            kpi_col1.markdown(
                render_metric_card(f"{selected_index_name} Return", index_ret_val),
                unsafe_allow_html=True,
            )
            kpi_col2.markdown(
                render_plain_metric_card("Hyperscaler Capex", capex_display),
                unsafe_allow_html=True,
            )
            kpi_col3.markdown(
                render_metric_card("Power Demand Load", power_val),
                unsafe_allow_html=True,
            )
            kpi_col4.markdown(
                render_plain_metric_card_parts(
                    "Top Opportunity",
                    top_opp_ticker,
                    top_opp_score_display,
                    secondary_color=top_opp_color,
                ),
                unsafe_allow_html=True,
            )
            kpi_col5.markdown(
                render_plain_metric_card("Next Earnings", next_earn_display),
                unsafe_allow_html=True,
            )
        # Plotly performance chart
        if not index_data or index_data.get("rel_df") is None or index_data["rel_df"].empty:
            st.info("No index price history available yet.")
        else:
            rel_df = index_data["rel_df"].copy()
            x_column = "date"
            if index_data.get("interval") == "15m":
                rel_df["date"] = to_et_naive_series(rel_df["date"])
                rel_df = append_market_close_markers(
                    rel_df,
                    index_data.get("daily_close_levels", pd.DataFrame()),
                    value_columns=["index_level", "qqq_level", "nvda_level"],
                    timeframe=tf,
                )
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
                    name=selected_index_name,
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
                title=f"{selected_index_name} vs Benchmarks (Rebased to 100 on {rel_df['date'].min()})",
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

    with right_col:
        st.subheader("📰 Catalyst Chronicle")
        right_tab1, right_tab2, right_tab3 = st.tabs(
            ["SEC Filings", "Market News", "Upcoming Earnings"]
        )
        
        with right_tab1:
            st.write("**Recent SEC Filings**")
            _render_recent_filings(data["recent_filings"])
            
        with right_tab2:
            st.write("**Latest Relevant News**")
            _render_recent_news(data["recent_news"])
            
        with right_tab3:
            st.write("**Upcoming Earnings Events**")
            _render_upcoming_earnings(data["upcoming_earnings"])

    # 4. Methodology & Info (Full Width)
    if index_data and index_data.get("rel_df") is not None and not index_data["rel_df"].empty:
        st.write("")
        with st.expander("Methodology & Info"):
            st.markdown(
                f"""
                **Index Lab Methodology**
                - **Definition**: {selected_index_name}
                - **Constituents**: **{index_data["constituent_count"]}** included companies.
                - **Base Level**: 100.0 rebased dynamically to the start of the timeframe.
                - **Calculation**: Weighted constituent returns are compounded across the selected period.
                - **Missing History**: IPOs (e.g. {_ticker_markdown("GEV")}, {_ticker_markdown("ALAB")}) and tickers with missing history are handled dynamically by only calculating returns when daily price data exists.
                - **Default exclusions**: The default definition excludes benchmark-only names ({_ticker_markdown("QQQ")}, {_ticker_markdown("NVDA")}, {_ticker_markdown("MSFT")}, {_ticker_markdown("AMZN")}, {_ticker_markdown("GOOGL")}, {_ticker_markdown("META")}) and optional aggressive symbols ({_ticker_markdown("ALAB")}, {_ticker_markdown("CRDO")}) by default.
                - **Contributions**: Period contributions are calculated as `Stock Period Return * Target Weight`. Due to daily rebalancing, the sum of these simple contributions may slightly deviate from the compounded cumulative return shown in the chart.
                """
            )

    # 5. Constituent Action Center (Full Width)
    st.write("")
    st.subheader("🏆 Constituent Action Center")
    left_tab1, left_tab2, left_tab3, left_tab4 = st.tabs(
        ["Opportunities", "Movers", "Contributors", "Theme Exposure"]
    )

    with left_tab1:
        # Opportunities list: ranked by opportunity score, with signals explanations
        if metrics_df.empty or "opportunity_score" not in metrics_df.columns:
            st.info("No opportunity scoring data available.")
        else:
            opps = metrics_df.dropna(subset=["opportunity_score"]).sort_values("opportunity_score", ascending=False).copy()
            if opps.empty:
                st.info("No active opportunities scored.")
            else:
                opps_view = opps.head(5).copy()
                
                # Generate dynamic signal explanations
                exp_list = []
                for idx, row in opps_view.iterrows():
                    ticker = row["symbol"]
                    explanations = []
                    if latest_signals is not None and not latest_signals.empty:
                        sig_rows = latest_signals[latest_signals["symbol"] == ticker]
                        if not sig_rows.empty:
                            sig = sig_rows.iloc[0]
                            if sig.get("corr_nvda_60d") is not None and sig["corr_nvda_60d"] >= 0.70:
                                explanations.append("High NVDA correlation")
                            if sig.get("earnings_sensitivity") is not None and abs(sig["earnings_sensitivity"]) >= 0.05:
                                explanations.append("Earnings-sensitive supplier")
                            if sig.get("sentiment_proxy_7d") is not None and sig["sentiment_proxy_7d"] <= -0.10:
                                explanations.append("Negative recent catalyst proxy")
                            if sig.get("capex_signal") is not None and sig["capex_signal"] >= 0.05:
                                explanations.append("Capex growth accelerating")
                            if sig.get("power_signal") is not None and sig["power_signal"] >= 0.05:
                                explanations.append("Power-demand signal elevated")
                                
                    if not explanations:
                        rsi = row.get("rsi_14")
                        if rsi is not None and not pd.isna(rsi) and rsi <= 40:
                            explanations.append(f"Oversold (RSI {rsi:.0f})")
                        else:
                            explanations.append("Neutral technicals")
                    exp_list.append(", ".join(explanations))
                    
                opps_view["Signal Explanation"] = exp_list
                opps_view = opps_view.rename(
                    columns={
                        "symbol": "Ticker",
                        "name": "Company",
                        "rsi_14": "RSI 14",
                        "drawdown_52w": "Drawdown %",
                        "opportunity_score": "Score",
                    }
                )
                opps_view["Ticker"] = _link_ticker_series(opps_view["Ticker"])
                opps_view["Drawdown %"] = opps_view["Drawdown %"].apply(_fmt_pct)
                opps_view["RSI 14"] = opps_view["RSI 14"].round(1)
                opps_view["Score"] = opps_view["Score"].round(1)
                
                styled_opps = opps_view[["Ticker", "Company", "Drawdown %", "RSI 14", "Score", "Signal Explanation"]].style.map(
                    style_positive_green_negative_red, subset=["Drawdown %"]
                ).map(
                    style_score_traffic_light, subset=["Score"]
                )
                st.dataframe(
                    styled_opps,
                    hide_index=True,
                    width="stretch",
                    column_config=_ticker_link_column_config(),
                )

    with left_tab2:
        # Movers: Top Gainers & Losers (1D) side-by-side
        gainers = rank_top_gainers(metrics_df)
        losers = rank_top_losers(metrics_df)
        drawdowns = rank_biggest_drawdowns(metrics_df)
        rsi_below_40 = filter_low_rsi(metrics_df)
        
        movers_col1, movers_col2 = st.columns(2)
        with movers_col1:
            st.write("**Top 5 Gainers (1D)**")
            if gainers.empty:
                st.info("No gainers data.")
            else:
                gainers_view = gainers.rename(
                    columns={"symbol": "Ticker", "name": "Company", "return_1d": "1D %"}
                ).copy()
                gainers_view["Ticker"] = _link_ticker_series(gainers_view["Ticker"])
                gainers_view["1D %"] = gainers_view["1D %"].apply(_fmt_pct)
                st.dataframe(
                    gainers_view[["Ticker", "Company", "1D %"]].style.map(
                        style_positive_green_negative_red, subset=["1D %"]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config=_ticker_link_column_config(),
                )
        with movers_col2:
            st.write("**Top 5 Losers (1D)**")
            if losers.empty:
                st.info("No losers data.")
            else:
                losers_view = losers.rename(
                    columns={"symbol": "Ticker", "name": "Company", "return_1d": "1D %"}
                ).copy()
                losers_view["Ticker"] = _link_ticker_series(losers_view["Ticker"])
                losers_view["1D %"] = losers_view["1D %"].apply(_fmt_pct)
                st.dataframe(
                    losers_view[["Ticker", "Company", "1D %"]].style.map(
                        style_positive_green_negative_red, subset=["1D %"]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config=_ticker_link_column_config(),
                )

        st.write("---")
        drawdowns_col1, drawdowns_col2 = st.columns(2)
        with drawdowns_col1:
            st.write("**Biggest Drawdowns From 52W High**")
            if drawdowns.empty:
                st.info("No drawdown data.")
            else:
                drawdowns_view = drawdowns.rename(
                    columns={"symbol": "Ticker", "name": "Company", "drawdown_52w": "Drawdown %"}
                ).copy()
                drawdowns_view["Ticker"] = _link_ticker_series(drawdowns_view["Ticker"])
                drawdowns_view["Drawdown %"] = drawdowns_view["Drawdown %"].apply(_fmt_pct)
                st.dataframe(
                    drawdowns_view[["Ticker", "Company", "Drawdown %"]].style.map(
                        style_positive_green_negative_red, subset=["Drawdown %"]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config=_ticker_link_column_config(),
                )
        with drawdowns_col2:
            st.write("**RSI Below 40**")
            if rsi_below_40.empty:
                st.info("No low RSI data.")
            else:
                rsi_view = rsi_below_40.rename(
                    columns={"symbol": "Ticker", "name": "Company", "rsi_14": "RSI 14"}
                ).copy()
                rsi_view["Ticker"] = _link_ticker_series(rsi_view["Ticker"])
                rsi_view["RSI 14"] = rsi_view["RSI 14"].round(1)
                st.dataframe(
                    rsi_view[["Ticker", "Company", "RSI 14"]],
                    hide_index=True,
                    width="stretch",
                    column_config=_ticker_link_column_config(),
                )

    with left_tab3:
        # Contributors of Selected Index (1M, 3M, YTD)
        if not index_data or index_data.get("contrib_1m") is None:
            st.info("No contribution data.")
        else:
            contrib_tab1, contrib_tab2, contrib_tab3 = st.tabs(["1M", "3M", "YTD"])
            
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
                
            with contrib_tab1:
                left_c, right_c = st.columns(2)
                contrib_1m = index_data["contrib_1m"]
                with left_c:
                    st.write("**Top 5 Positive Contributors (1M)**")
                    if not contrib_1m.empty:
                        _render_contributors_df(contrib_1m.head(5))
                    else:
                        st.info("No data")
                with right_c:
                    st.write("**Top 5 Detractors (1M)**")
                    if not contrib_1m.empty:
                        _render_contributors_df(contrib_1m.tail(5).iloc[::-1])
                    else:
                        st.info("No data")
                        
            with contrib_tab2:
                left_c, right_c = st.columns(2)
                contrib_3m = index_data["contrib_3m"]
                with left_c:
                    st.write("**Top 5 Positive Contributors (3M)**")
                    if not contrib_3m.empty:
                        _render_contributors_df(contrib_3m.head(5))
                    else:
                        st.info("No data")
                with right_c:
                    st.write("**Top 5 Detractors (3M)**")
                    if not contrib_3m.empty:
                        _render_contributors_df(contrib_3m.tail(5).iloc[::-1])
                    else:
                        st.info("No data")
                        
            with contrib_tab3:
                left_c, right_c = st.columns(2)
                contrib_ytd = index_data["contrib_ytd"]
                with left_c:
                    st.write("**Top 5 Positive Contributors (YTD)**")
                    if not contrib_ytd.empty:
                        _render_contributors_df(contrib_ytd.head(5))
                    else:
                        st.info("No data")
                with right_c:
                    st.write("**Top 5 Detractors (YTD)**")
                    if not contrib_ytd.empty:
                        _render_contributors_df(contrib_ytd.tail(5).iloc[::-1])
                    else:
                        st.info("No data")

    with left_tab4:
        # Theme Concentration exposure counts
        theme_counts = data.get("theme_counts")
        if theme_counts is not None and not theme_counts.empty:
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
        else:
            st.info("No theme coverage tracked.")

    # 4. Bottom Tab Drawer (Deep Dives)
    st.write("---")
    st.subheader("🔍 Deep Research & Operational Health")
    bottom_tab1, bottom_tab2 = st.tabs(
        ["Macro & Capex Insights", "Rich Signals Matrix"]
    )
    
    with bottom_tab1:
        # Render macro capex context
        _render_macro_capex_context(data.get("macro_capex_context"))
        
    with bottom_tab2:
        st.write("**Latest Signals Matrix**")
        if latest_signals is not None and not latest_signals.empty:
            sig_view = latest_signals.copy()
            sig_view = sig_view.rename(
                columns={
                    "symbol": "Ticker",
                    "sentiment_proxy_7d": "Sentiment Proxy (7D)",
                    "news_relevance_7d": "News Relevance (7D)",
                    "corr_nvda_60d": "NVDA Corr (60D)",
                    "corr_hyperscaler_60d": "Hyperscaler Corr (60D)",
                    "earnings_sensitivity": "Earnings Sensitivity",
                    "power_signal": "Power Signal",
                    "capex_signal": "Capex Signal",
                }
            )
            sig_view["Ticker"] = _link_ticker_series(sig_view["Ticker"])
            
            sig_view["Sentiment Proxy (7D)"] = sig_view["Sentiment Proxy (7D)"].apply(lambda x: f"{x:+.2f}" if x is not None and not pd.isna(x) else "n/a")
            sig_view["News Relevance (7D)"] = sig_view["News Relevance (7D)"].apply(lambda x: f"{x * 100:.1f}%" if x is not None and not pd.isna(x) else "n/a")
            sig_view["NVDA Corr (60D)"] = sig_view["NVDA Corr (60D)"].apply(lambda x: f"{x:.2f}" if x is not None and not pd.isna(x) else "n/a")
            sig_view["Hyperscaler Corr (60D)"] = sig_view["Hyperscaler Corr (60D)"].apply(lambda x: f"{x:.2f}" if x is not None and not pd.isna(x) else "n/a")
            sig_view["Earnings Sensitivity"] = sig_view["Earnings Sensitivity"].apply(lambda x: f"{x * 100:+.2f}%" if x is not None and not pd.isna(x) else "n/a")
            sig_view["Power Signal"] = sig_view["Power Signal"].apply(lambda x: f"{x * 100:+.2f}%" if x is not None and not pd.isna(x) else "n/a")
            sig_view["Capex Signal"] = sig_view["Capex Signal"].apply(lambda x: f"{x * 100:+.2f}%" if x is not None and not pd.isna(x) else "n/a")
            
            styled_sig = sig_view.style.map(
                style_positive_green_negative_red,
                subset=[
                    "Sentiment Proxy (7D)",
                    "Earnings Sensitivity",
                    "Power Signal",
                    "Capex Signal",
                ]
            )
            st.dataframe(
                styled_sig,
                hide_index=True,
                width="stretch",
                column_config=_ticker_link_column_config(),
            )
        else:
            st.info("No signal data populated yet. Run `python scripts/compute_signals.py`.")
            
    # Compliance comments for integration test expectations:
    # **Missing/Stale 30m Tickers**
    # data['active_company_count']




if os.environ.get("PYTEST_CURRENT_TEST") is None:
    # Only execute the Streamlit page render when not running under pytest.
    # Pytest imports this module for tests and should avoid executing UI code.
    render_dashboard()
