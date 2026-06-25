from __future__ import annotations

from html import escape
import re

import pandas as pd
import streamlit as st
from argus.core.db import safe_execute_query

from datetime import UTC, datetime
from app.auth_links import company_detail_url
from app.components.database import get_configured_app_engine
from app.components.sidebar import render_sidebar_navigation

from argus.core.seed import WATCH_STATUSES
from argus.services.dashboard_service import build_stale_reasons
from argus.services.pullback_finder_service import (
    apply_pullback_filters,
    get_filter_options,
    load_pullback_candidates,
)
from app.components.tables import style_positive_green_negative_red, style_score_traffic_light


@st.cache_resource
def get_pullback_engine():
    return get_configured_app_engine()


@st.cache_data(ttl=300)
def load_pullback_data() -> pd.DataFrame:
    return load_pullback_candidates(get_pullback_engine())


@st.cache_data(ttl=300)
def load_backtest_summaries() -> pd.DataFrame:
    engine = get_pullback_engine()
    with engine.connect() as conn:
        query = """
            SELECT score_bucket, horizon, event_count, hit_rate, avg_return, avg_drawdown
            FROM score_backtest_summaries
        """
        data = safe_execute_query(conn, query)
        df = pd.DataFrame(data)
        if df.empty:
            return df

        def bucket_key(b):
            if b == "Below 0":
                return -100
            if b == "100+":
                return 1000
            try:
                parts = b.split("-")
                return int(parts[0])
            except Exception:
                return 0

        def horizon_key(h):
            h_map = {"5d": 1, "20d": 2, "60d": 3}
            return h_map.get(h.lower(), 4)

        df["bucket_sort"] = df["score_bucket"].apply(bucket_key)
        df["horizon_sort"] = df["horizon"].apply(horizon_key)
        df = df.sort_values(by=["bucket_sort", "horizon_sort"]).drop(
            columns=["bucket_sort", "horizon_sort"]
        )
        return df


@st.cache_data(ttl=300)
def load_summary_for_bucket(bucket: str) -> pd.DataFrame:
    engine = get_pullback_engine()
    with engine.connect() as conn:
        query = """
            SELECT horizon, event_count, hit_rate, avg_return, avg_drawdown
            FROM score_backtest_summaries
            WHERE score_bucket = :bucket
        """
        data = safe_execute_query(conn, query, {"bucket": bucket})
        return pd.DataFrame(data)


def _get_bucket_for_score(score_val: float) -> str:
    if score_val < 0:
        return "Below 0"
    if score_val >= 100:
        return "100+"
    lower = int(score_val // 10) * 10
    upper = lower + 10
    return f"{lower}-{upper}"


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:+.{digits}f}%"


def _fmt_score(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.1f}"


def _fmt_date(value) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()


def _fmt_price(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"${float(value):,.2f}"


def _fmt_metric_pct(value: float | None, *, signed: bool = True) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    sign = "+" if signed else ""
    return f"{float(value) * 100:{sign}.1f}%"


def _metric_color(value: float | None, *, inverse: bool = False) -> str:
    if value is None or pd.isna(value):
        return "#8b949e"
    numeric = float(value)
    if numeric == 0:
        return "#8b949e"
    is_positive = numeric > 0
    if inverse:
        is_positive = not is_positive
    return "#3fb950" if is_positive else "#f85149"


def _score_color(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "#8b949e"
    score = float(value)
    if score >= 70:
        return "#3fb950"
    if score >= 40:
        return "#f0b429"
    return "#f85149"


def _metric_badge(label: str, value: str, color: str = "#c9d1d9") -> str:
    return f"""
        <div style="background: rgba(13, 17, 23, 0.72); border: 1px solid rgba(139, 148, 158, 0.22); border-radius: 8px; padding: 10px 12px;">
            <div style="font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;">{escape(label)}</div>
            <div style="font-size: 15px; color: {color}; font-weight: 700;">{escape(value)}</div>
        </div>
    """


def _score_chip(label: str, value: float | None) -> str:
    text = _fmt_score(value)
    color = _metric_color(value)
    return f"""
        <span style="display: inline-flex; gap: 6px; align-items: baseline; border: 1px solid rgba(139, 148, 158, 0.22); border-radius: 999px; padding: 4px 9px; background: rgba(13, 17, 23, 0.62);">
            <span style="color: #8b949e;">{escape(label)}</span>
            <span style="color: {color}; font-weight: 700;">{escape(text)}</span>
        </span>
    """


def render_candidate_detail_card(ticker: str, company: str, row: pd.Series) -> str:
    """Render a compact selected-candidate detail card."""
    score = row.get("score")
    explanation = str(row.get("explanation") or "No explanation available.")
    valuation = str(row.get("valuation_flag") or "n/a")
    if valuation == "nan":
        valuation = "n/a"
    fwd_pe_pctile = row.get("forward_pe_percentile_rank")
    fwd_pe_text = "n/a" if pd.isna(fwd_pe_pctile) else f"{float(fwd_pe_pctile):.0f}"

    metrics = [
        _metric_badge("Latest Price", _fmt_price(row.get("price"))),
        _metric_badge("Price Date", _fmt_date(row.get("price_date"))),
        _metric_badge(
            "52W Drawdown",
            _fmt_metric_pct(row.get("drawdown_52w")),
            _metric_color(row.get("drawdown_52w")),
        ),
        _metric_badge(
            "RSI 14", "n/a" if pd.isna(row.get("rsi_14")) else f"{float(row.get('rsi_14')):.1f}"
        ),
        _metric_badge(
            "200DMA Distance",
            _fmt_metric_pct(row.get("distance_from_200dma")),
            _metric_color(row.get("distance_from_200dma")),
        ),
        _metric_badge(
            "3M vs QQQ",
            _fmt_metric_pct(row.get("relative_return_vs_qqq_3m")),
            _metric_color(row.get("relative_return_vs_qqq_3m")),
        ),
        _metric_badge("Valuation", valuation.title()),
        _metric_badge(
            "EV/Sales vs Sector",
            _fmt_metric_pct(row.get("ev_sales_premium_discount_pct")),
            _metric_color(row.get("ev_sales_premium_discount_pct"), inverse=True),
        ),
        _metric_badge("Fwd P/E Pctile", fwd_pe_text),
    ]

    chips = [
        _score_chip("Theme", row.get("score_theme_exposure")),
        _score_chip("Pullback", row.get("score_pullback")),
        _score_chip("Technical", row.get("score_technical_setup")),
        _score_chip("Rel Str", row.get("score_relative_strength")),
        _score_chip("Catalyst", row.get("score_catalyst")),
        _score_chip("Watchlist", row.get("score_watchlist_priority")),
        _score_chip("Risk", row.get("score_risk_penalty")),
        _score_chip("Macro", row.get("score_macro_penalty")),
        _score_chip("Valuation", row.get("score_valuation_adjustment")),
    ]

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
                Candidate Detail: <span style="color: #f0f6fc;">{escape(ticker)}</span> <span style="font-size: 14px; font-weight: normal; color: #8b949e;">({escape(company)})</span>
            </div>
            <div style="background: rgba(56, 139, 253, 0.15); color: {_score_color(score)}; font-weight: 700; font-size: 14px; padding: 4px 10px; border-radius: 20px; border: 1px solid rgba(56, 139, 253, 0.3);">
                Score: {_fmt_score(score)}
            </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 8px; margin: 14px 0 12px;">
            {"".join(metrics)}
        </div>
        <div style="display: flex; flex-wrap: wrap; gap: 7px; margin: 6px 0 14px; font-size: 13px;">
            {"".join(chips)}
        </div>
        <div style="color: #c9d1d9; font-size: 15px; line-height: 1.6; white-space: pre-wrap;">{escape(explanation)}</div>
    </div>
    """


def _filter_value(key: str) -> str:
    value = st.session_state.get(key, "All")
    return value if isinstance(value, str) else "All"


def _reset_invalid_filter(key: str, options: list[str]) -> None:
    if st.session_state.get(key) not in [None, "All", *options]:
        st.session_state[key] = "All"


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

    tabs = st.tabs(["Pullback Finder", "Signal History"])

    with tabs[0]:
        if st.button("Refresh candidates"):
            load_pullback_data.clear()
            st.rerun()

        candidates = load_pullback_data()
        if candidates.empty:
            st.warning(
                "No candidate data found. Run price ingestion and metrics computation first."
            )
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

        selected_sector_state = _filter_value("pullback_sector_filter")
        selected_family_state = _filter_value("pullback_theme_family_filter")
        selected_theme_state = _filter_value("pullback_theme_filter")

        sector_base = apply_pullback_filters(
            candidates,
            theme_family=None if selected_family_state == "All" else selected_family_state,
            theme=None if selected_theme_state == "All" else selected_theme_state,
        )
        sector_options = get_filter_options(sector_base)["sectors"]
        _reset_invalid_filter("pullback_sector_filter", sector_options)
        selected_sector_state = _filter_value("pullback_sector_filter")

        family_base = apply_pullback_filters(
            candidates,
            sector=None if selected_sector_state == "All" else selected_sector_state,
            theme=None if selected_theme_state == "All" else selected_theme_state,
        )
        family_options = get_filter_options(family_base)["theme_families"]
        _reset_invalid_filter("pullback_theme_family_filter", family_options)
        selected_family_state = _filter_value("pullback_theme_family_filter")

        theme_base = apply_pullback_filters(
            candidates,
            sector=None if selected_sector_state == "All" else selected_sector_state,
            theme_family=None if selected_family_state == "All" else selected_family_state,
        )
        theme_options = get_filter_options(theme_base)["themes"]
        _reset_invalid_filter("pullback_theme_filter", theme_options)

        filter1, filter2, filter3, filter4 = st.columns(4)
        with filter1:
            selected_sector = st.selectbox(
                "Sector",
                ["All"] + sector_options,
                key="pullback_sector_filter",
            )
        with filter2:
            selected_theme_family = st.selectbox(
                "Theme Family",
                ["All"] + family_options,
                key="pullback_theme_family_filter",
            )
        with filter3:
            selected_theme = st.selectbox(
                "Theme",
                ["All"] + theme_options,
                key="pullback_theme_filter",
            )
        with filter4:
            status_base = apply_pullback_filters(
                candidates,
                sector=None if selected_sector == "All" else selected_sector,
                theme_family=None if selected_theme_family == "All" else selected_theme_family,
                theme=None if selected_theme == "All" else selected_theme,
            )
            status_options = (
                sorted(status_base["watch_status"].dropna().unique().tolist())
                if "watch_status" in status_base
                else sorted(WATCH_STATUSES)
            )
            selected_statuses = st.multiselect(
                "Watch Status",
                status_options,
                default=status_options,
            )

        filter4_col, filter5, filter6 = st.columns(3)
        with filter4_col:
            min_drawdown_pct = st.slider("Minimum drawdown from 52W high (%)", 0, 40, 10)
        with filter5:
            rsi_min, rsi_max = st.slider("RSI 14 range", 0, 100, (0, 55))
        with filter6:
            dma_position = st.selectbox("200DMA position", ["Any", "Above", "Below"])

        filter7, filter8 = st.columns(2)
        with filter7:
            exclude_benchmarks = st.checkbox(
                "Exclude Benchmarks (NVDA, QQQ, MSFT, etc.)", value=True
            )
        with filter8:
            exclude_hyperscalers = st.checkbox(
                "Exclude Hyperscalers (AMZN, GOOGL, META, MSFT)", value=False
            )

        filtered = apply_pullback_filters(
            candidates,
            sector=None if selected_sector == "All" else selected_sector,
            theme_family=None if selected_theme_family == "All" else selected_theme_family,
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
        else:
            display_df = filtered.copy()
            display_df["rank"] = range(1, len(display_df) + 1)
            display_df["ticker"] = display_df["ticker"].apply(company_detail_url)
            display_df["score"] = display_df["opportunity_score"].round(1)
            display_df["drawdown"] = display_df["drawdown_52w"].apply(_fmt_pct)
            display_df["rsi"] = display_df["rsi_14"].apply(
                lambda value: "n/a" if pd.isna(value) else f"{value:.1f}"
            )
            display_df["vs QQQ 3M"] = display_df["relative_return_vs_qqq_3m"].apply(_fmt_pct)
            display_df["200DMA"] = display_df["distance_from_200dma"].apply(_fmt_pct)
            display_df["max theme score"] = display_df["theme_exposure_score"].apply(
                lambda value: "n/a" if pd.isna(value) else f"{value:.1f}/5"
            )
            display_df["valuation"] = (
                display_df["valuation_flag"].fillna("n/a")
                if "valuation_flag" in display_df
                else "n/a"
            )
            display_df["EV/Sales vs sector"] = (
                display_df["ev_sales_premium_discount_pct"].apply(_fmt_pct)
                if "ev_sales_premium_discount_pct" in display_df
                else "n/a"
            )
            display_df["Fwd P/E pctile"] = (
                display_df["forward_pe_percentile_rank"].apply(
                    lambda value: "n/a" if pd.isna(value) else f"{value:.0f}"
                )
                if "forward_pe_percentile_rank" in display_df
                else "n/a"
            )

            table_df = display_df[
                [
                    "rank",
                    "ticker",
                    "company",
                    "sector",
                    "theme_family",
                    "theme",
                    "watch_status",
                    "score",
                    "drawdown",
                    "rsi",
                    "200DMA",
                    "vs QQQ 3M",
                    "valuation",
                    "EV/Sales vs sector",
                    "Fwd P/E pctile",
                    "max theme score",
                ]
            ]

            st.subheader("Ranked pullback candidates")
            styled_table_df = table_df.style.map(
                style_positive_green_negative_red, subset=["drawdown", "200DMA", "vs QQQ 3M"]
            ).map(
                style_score_traffic_light,
                subset=["score"],
            )
            event = st.dataframe(
                styled_table_df,
                hide_index=True,
                width="stretch",
                column_config={
                    "rank": st.column_config.NumberColumn("rank", width="small"),
                    "score": st.column_config.NumberColumn("score", format="%.1f"),
                    "ticker": st.column_config.LinkColumn("ticker", display_text=r"ticker=([^&]+)"),
                },
                on_select="rerun",
                selection_mode="single-row",
            )

            st.caption(
                "💡 *Tip: Click on any row in the table above to view the full, wrapped reason/explanation below.*"
            )

            if event and event.selection and event.selection.rows:
                selected_row_idx = event.selection.rows[0]
                selected_row = display_df.iloc[selected_row_idx]

                # Extract symbol from link
                ticker_symbol = selected_row["ticker"]
                match = re.search(r"ticker=([^&]+)", ticker_symbol)
                if match:
                    ticker_symbol = match.group(1)

                company_name = selected_row["company"]
                score_val = selected_row["score"]

                st.html(render_candidate_detail_card(ticker_symbol, company_name, selected_row))

                # Historical Backtest Context
                bucket = _get_bucket_for_score(score_val)
                summary_df = load_summary_for_bucket(bucket)
                if not summary_df.empty:
                    st.markdown(f"#### 📊 Historical Backtest Context for Bucket: `{bucket}`")
                    st.caption(
                        "Shows historical returns and drawdowns for candidates with scores in this range."
                    )
                    disp_summary = summary_df.copy()

                    # Horizon ordering
                    horizon_map = {"5d": 1, "20d": 2, "60d": 3}
                    disp_summary["sort"] = disp_summary["horizon"].str.lower().map(horizon_map)
                    disp_summary = disp_summary.sort_values("sort").drop(columns=["sort"])

                    disp_summary["Horizon"] = disp_summary["horizon"].str.upper()
                    disp_summary["Event Count"] = disp_summary["event_count"]
                    disp_summary["Hit Rate"] = disp_summary["hit_rate"].apply(
                        lambda v: f"{v * 100:.1f}%"
                    )
                    disp_summary["Avg Return"] = disp_summary["avg_return"].apply(
                        lambda v: f"{v * 100:+.1f}%"
                    )
                    disp_summary["Avg Drawdown"] = disp_summary["avg_drawdown"].apply(
                        lambda v: f"{v * 100:+.1f}%"
                    )
                    summary_view = disp_summary[
                        ["Horizon", "Event Count", "Hit Rate", "Avg Return", "Avg Drawdown"]
                    ]
                    styled_summary = summary_view.style.map(
                        style_positive_green_negative_red,
                        subset=["Avg Return", "Avg Drawdown"],
                    )

                    st.dataframe(styled_summary, hide_index=True, use_container_width=True)

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
                        "score_macro_penalty",
                        "score_valuation_adjustment",
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
                        "score_macro_penalty": "macro penalty",
                        "score_valuation_adjustment": "valuation adj",
                    }
                )
                styled_breakdown_df = breakdown_df.style.map(
                    style_positive_green_negative_red,
                    subset=["risk penalty", "macro penalty", "valuation adj"],
                )
                st.dataframe(
                    styled_breakdown_df,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "ticker": st.column_config.LinkColumn(
                            "ticker", display_text=r"ticker=([^&]+)"
                        )
                    },
                )

    with tabs[1]:
        st.subheader("Signal History (Backtest Summaries)")
        st.markdown(
            "Performance of opportunity scores over historical 5-day, 20-day, and 60-day windows. "
            "Use this data to assess the historical reliability of candidates in different score buckets."
        )

        summaries_df = load_backtest_summaries()
        if summaries_df.empty:
            st.info(
                "No signal backtest history found in database. Run `python scripts/backtest_scores.py` to generate it."
            )
        else:
            disp_df = summaries_df.copy()
            disp_df["Score Bucket"] = disp_df["score_bucket"]
            disp_df["Horizon"] = disp_df["horizon"].str.upper()
            disp_df["Event Count"] = disp_df["event_count"]
            disp_df["Hit Rate"] = disp_df["hit_rate"].apply(lambda v: f"{v * 100:.1f}%")
            disp_df["Avg Return"] = disp_df["avg_return"].apply(lambda v: f"{v * 100:+.1f}%")
            disp_df["Avg Drawdown"] = disp_df["avg_drawdown"].apply(lambda v: f"{v * 100:+.1f}%")

            cols = [
                "Score Bucket",
                "Horizon",
                "Event Count",
                "Hit Rate",
                "Avg Return",
                "Avg Drawdown",
            ]
            styled_signal_history = disp_df[cols].style.map(
                style_positive_green_negative_red,
                subset=["Avg Return", "Avg Drawdown"],
            )
            st.dataframe(styled_signal_history, hide_index=True, use_container_width=True)


def selected_dma_position(label: str) -> str | None:
    mapping = {"Any": "any", "Above": "above", "Below": "below"}
    return mapping.get(label, "any")


render_pullback_finder()
