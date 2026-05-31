from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
import pandas as pd
import streamlit as st

from app.components.sidebar import render_sidebar_navigation
from argus.core.db import create_database_engine
from argus.core.settings import settings
from argus.services.company_service import get_company_options
from argus.services.news_filings_service import (
    get_all_news_sources,
    get_filtered_filings,
    get_filtered_news,
    get_last_job_run,
)
from argus.services.alert_service import (
    get_all_alerts,
    get_recent_alert_events,
    create_alert,
    toggle_alert,
    delete_alert,
)

RULE_TYPES = [
    "price_below",
    "price_above",
    "daily_move_gt",
    "drawdown_52w_gt",
    "rsi_below",
    "crossed_50dma",
    "crossed_200dma",
    "new_sec_filing",
    "news_keyword_match",
    "earnings_within_days",
    "entered_pullback_zone",
]

RULE_DESCRIPTIONS = {
    "price_below": "Triggers when the stock price drops below a target price.",
    "price_above": "Triggers when the stock price rises above a target price.",
    "daily_move_gt": "Triggers when the absolute 1-day return exceeds a percentage.",
    "drawdown_52w_gt": "Triggers when the drawdown from 52-week high exceeds a percentage.",
    "rsi_below": "Triggers when RSI 14 falls below a threshold.",
    "crossed_50dma": "Triggers when price crosses the 50-day moving average.",
    "crossed_200dma": "Triggers when price crosses the 200-day moving average.",
    "new_sec_filing": "Triggers when a new SEC filing is detected.",
    "news_keyword_match": "Triggers when a news item matches specified keywords.",
    "earnings_within_days": "Triggers when earnings are within a specified number of days.",
    "entered_pullback_zone": "Triggers when a stock enters the pullback zone criteria.",
}


@st.cache_resource
def get_db_engine():
    return create_database_engine(settings.database_url)


@st.cache_data(ttl=60)
def load_news(ticker, source, keyword, start_date, end_date) -> pd.DataFrame:
    return get_filtered_news(
        get_db_engine(),
        ticker=ticker,
        source=source,
        keyword=keyword,
        start_date=start_date,
        end_date=end_date,
    )


@st.cache_data(ttl=60)
def load_filings(ticker, form, start_date, end_date) -> pd.DataFrame:
    return get_filtered_filings(
        get_db_engine(),
        ticker=ticker,
        form=form,
        start_date=start_date,
        end_date=end_date,
    )


@st.cache_data(ttl=300)
def load_sources() -> list[str]:
    return get_all_news_sources(get_db_engine())


@st.cache_data(ttl=30)
def load_alerts() -> pd.DataFrame:
    return get_all_alerts(get_db_engine())


@st.cache_data(ttl=30)
def load_alert_history(limit: int = 50) -> pd.DataFrame:
    return get_recent_alert_events(get_db_engine(), limit=limit)


def _parse_job_time(val) -> str:
    if val is None or pd.isna(val):
        return "never"
    try:
        dt = pd.to_datetime(val)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(val)


def _render_create_alert_form() -> None:
    """Render the form to create a new alert rule."""
    st.markdown("#### ➕ Create New Alert")

    with st.form("create_alert_form", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        with col_a:
            alert_name = st.text_input("Alert Name", placeholder="e.g., NVDA price drop alert")
        with col_b:
            rule_type = st.selectbox("Rule Type", options=RULE_TYPES)

        # Show rule description
        st.caption(RULE_DESCRIPTIONS.get(rule_type, ""))

        col_c, col_d = st.columns(2)
        with col_c:
            tickers = ["— None (use watchlist) —"] + get_company_options()
            selected_ticker = st.selectbox("Target Company", options=tickers, key="alert_ticker")
        with col_d:
            # Watchlist-based targeting placeholder
            st.caption("Or leave company blank to target a whole watchlist (future).")

        # Dynamic config inputs based on rule type
        config = {}
        if rule_type in ("price_below", "price_above"):
            config["threshold"] = st.number_input(
                "Price Threshold ($)", min_value=0.01, value=100.0, step=1.0
            )
        elif rule_type == "daily_move_gt":
            config["threshold_pct"] = st.number_input(
                "Move Threshold (%)", min_value=0.1, value=5.0, step=0.5
            )
        elif rule_type == "drawdown_52w_gt":
            config["threshold_pct"] = st.number_input(
                "Drawdown Threshold (%)", min_value=1.0, value=15.0, step=1.0
            )
        elif rule_type == "rsi_below":
            config["threshold"] = st.number_input(
                "RSI Threshold", min_value=1.0, max_value=100.0, value=30.0, step=1.0
            )
        elif rule_type in ("crossed_50dma", "crossed_200dma"):
            config["direction"] = st.selectbox(
                "Cross Direction", options=["any", "above", "below"]
            )
        elif rule_type == "new_sec_filing":
            forms_input = st.text_input(
                "Form Types (comma-separated, or leave blank for all)",
                placeholder="e.g., 10-K, 8-K",
            )
            if forms_input.strip():
                config["forms"] = [f.strip() for f in forms_input.split(",")]
        elif rule_type == "news_keyword_match":
            keywords_input = st.text_input(
                "Keywords (comma-separated)", placeholder="e.g., AI infrastructure, data center"
            )
            if keywords_input.strip():
                config["keywords"] = keywords_input
        elif rule_type == "earnings_within_days":
            config["days"] = st.number_input(
                "Days Before Earnings", min_value=1, value=7, step=1
            )
        elif rule_type == "entered_pullback_zone":
            p_col1, p_col2, p_col3 = st.columns(3)
            with p_col1:
                config["min_drawdown_pct"] = st.number_input(
                    "Min Drawdown (%)", min_value=1.0, value=10.0, step=1.0
                )
            with p_col2:
                config["max_rsi"] = st.number_input(
                    "Max RSI", min_value=1.0, max_value=100.0, value=55.0, step=1.0
                )
            with p_col3:
                config["min_distance_from_200dma"] = st.number_input(
                    "Min Dist from 200DMA (%)", value=-5.0, step=1.0
                )

        submitted = st.form_submit_button("Create Alert", type="primary")
        if submitted:
            if not alert_name.strip():
                st.error("Alert name is required.")
            else:
                company_id = None
                if selected_ticker != "— None (use watchlist) —":
                    # Resolve ticker to company_id
                    from argus.services.company_service import get_company_by_symbol

                    company_info = get_company_by_symbol(selected_ticker)
                    if company_info:
                        company_id = company_info["id"]

                if company_id is None:
                    st.error("Select a target company before creating an alert.")
                else:
                    try:
                        create_alert(
                            name=alert_name.strip(),
                            rule_type=rule_type,
                            company_id=company_id,
                            config_json=config if config else None,
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.success(f"Alert '{alert_name}' created successfully!")
                        load_alerts.clear()
                        load_alert_history.clear()
                        st.rerun()


def _render_active_alerts() -> None:
    """Render active alerts table with toggle/delete actions."""
    st.markdown("#### 📋 Active Alert Rules")

    alerts_df = load_alerts()
    if alerts_df.empty:
        st.info("No alert rules defined yet. Use the form below to create one.")
        return

    for _, row in alerts_df.iterrows():
        alert_id = int(row["id"])
        enabled = bool(row["is_enabled"])
        status_icon = "🟢" if enabled else "🔴"
        last_trigger = _parse_job_time(row.get("last_triggered_at"))

        with st.container():
            c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
            with c1:
                target_str = row.get("ticker") or row.get("watchlist") or "All"
                config_str = ""
                if row.get("config_json"):
                    try:
                        cfg = row["config_json"] if isinstance(row["config_json"], dict) else json.loads(row["config_json"])
                        config_str = " | ".join(f"{k}={v}" for k, v in cfg.items())
                    except Exception:
                        config_str = str(row["config_json"])

                st.markdown(
                    f"{status_icon} **{row['name']}** — `{row['rule_type']}` → {target_str}"
                )
                if config_str:
                    st.caption(f"Config: {config_str}")
            with c2:
                st.caption(f"Last triggered: {last_trigger}")
            with c3:
                new_state = not enabled
                btn_label = "Disable" if enabled else "Enable"
                if st.button(btn_label, key=f"toggle_{alert_id}"):
                    toggle_alert(alert_id, new_state)
                    load_alerts.clear()
                    st.rerun()
            with c4:
                if st.button("🗑️", key=f"delete_{alert_id}"):
                    delete_alert(alert_id)
                    load_alerts.clear()
                    load_alert_history.clear()
                    st.rerun()

        st.divider()


def _render_alert_history() -> None:
    """Render recent alert trigger history."""
    st.markdown("#### 📜 Alert Trigger History")

    history_df = load_alert_history(limit=50)
    if history_df.empty:
        st.info("No alert events recorded yet. Run the alert pipeline via CLI: `python scripts/run_alerts.py`")
        return

    display = history_df.copy()
    display["triggered_at"] = pd.to_datetime(display["triggered_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    # Color-code delivery status
    def _status_badge(status):
        if status == "sent":
            return "✅ Sent"
        elif status == "failed":
            return "❌ Failed"
        return "⏭️ Skipped"

    display["delivery"] = display["delivery_status"].apply(_status_badge)

    st.dataframe(
        display[["alert_name", "event_type", "ticker", "triggered_at", "delivery"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "alert_name": "Alert",
            "event_type": "Rule Type",
            "ticker": "Ticker",
            "triggered_at": "Triggered At",
            "delivery": "Delivery Status",
        },
    )


def render_page() -> None:
    render_sidebar_navigation()
    st.title("Catalysts: News, Filings & Alerts")

    # Ingestion Status Banner
    engine = get_db_engine()
    last_news_job = get_last_job_run(engine, "refresh_news")
    last_filings_job = get_last_job_run(engine, "refresh_filings")

    col_status1, col_status2, col_status3 = st.columns([2, 2, 1])

    with col_status1:
        if last_news_job:
            status_emoji = "✅" if last_news_job["status"] == "success" else "⚠️"
            st.caption(
                f"**News Job:** {status_emoji} {last_news_job['status'].upper()} | "
                f"Ran: {_parse_job_time(last_news_job['finished_at'])} | "
                f"Read: {last_news_job['rows_read']}, Written: {last_news_job['rows_written']}"
            )
        else:
            st.caption("**News Job:** No runs recorded.")

    with col_status2:
        if last_filings_job:
            status_emoji = "✅" if last_filings_job["status"] == "success" else "⚠️"
            st.caption(
                f"**SEC Job:** {status_emoji} {last_filings_job['status'].upper()} | "
                f"Ran: {_parse_job_time(last_filings_job['finished_at'])} | "
                f"Read: {last_filings_job['rows_read']}, Written: {last_filings_job['rows_written']}"
            )
        else:
            st.caption("**SEC Job:** No runs recorded.")

    with col_status3:
        if st.button("Refresh / Clear Cache", width="stretch"):
            load_news.clear()
            load_filings.clear()
            load_sources.clear()
            load_alerts.clear()
            load_alert_history.clear()
            st.rerun()

    # Tabs
    tab_news, tab_filings, tab_alerts = st.tabs(["Catalyst News", "SEC Filings", "Alerts Manager"])

    # Shared Filters Expandable Section
    with st.expander("Filter Options", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            tickers = ["All"] + get_company_options()
            selected_ticker = st.selectbox("Company / Ticker Filter", options=tickers)

        with col2:
            # Let's support date ranges up to past 90 days by default
            default_start = (datetime.now(UTC) - timedelta(days=30)).date()
            default_end = datetime.now(UTC).date()
            selected_start = st.date_input("Start Date", value=default_start)

        with col3:
            selected_end = st.date_input("End Date", value=default_end)

    # 1. Catalyst News Tab
    with tab_news:
        st.subheader("Latest News Headlines")

        # News specific filters
        n_col1, n_col2 = st.columns([1, 2])
        with n_col1:
            sources = ["All"] + load_sources()
            selected_source = st.selectbox("Filter by Source", options=sources)
        with n_col2:
            search_keyword = st.text_input("Search headlines, summary or keywords")

        news_df = load_news(
            selected_ticker,
            selected_source,
            search_keyword,
            selected_start,
            selected_end,
        )

        if news_df.empty:
            st.info("No news items found matching the current filters.")
        else:
            for _, item in news_df.iterrows():
                # Card-like layout for news headlines
                published_str = ""
                if item["published_at"]:
                    published_str = pd.to_datetime(item["published_at"]).strftime("%b %d, %Y %I:%M %p")

                st.markdown(f"### [{item['title']}]({item['url']})")
                st.markdown(
                    f"**Source:** `{item['source_name']}` | **Provider:** `{item['provider']}` | **Date:** {published_str}"
                )

                if item["summary"]:
                    st.write(item["summary"])

                # Tickers and Keywords badges
                badges = []
                if item["tickers"]:
                    badges.append(f"🏷️ **Tickers:** {item['tickers']}")
                if item["keywords"]:
                    badges.append(f"🔑 **Keywords:** {item['keywords']}")

                if badges:
                    st.caption("  •  ".join(badges))

                st.markdown("---")

    # 2. SEC Filings Tab
    with tab_filings:
        st.subheader("SEC EDGAR Filings")

        # Filings specific filters
        f_col1 = st.columns(1)[0]
        with f_col1:
            forms = ["All", "10-K", "10-Q", "8-K", "6-K", "20-F", "40-F"]
            selected_form = st.selectbox("Form Type Filter", options=forms)

        filings_df = load_filings(
            selected_ticker,
            selected_form,
            selected_start,
            selected_end,
        )

        if filings_df.empty:
            st.info("No filings found matching the current filters.")
        else:
            # Table formatting
            df_view = filings_df.copy()
            df_view["Filing Date"] = pd.to_datetime(df_view["filing_date"]).dt.strftime("%Y-%m-%d")
            df_view["Acceptance Time"] = pd.to_datetime(df_view["acceptance_datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")
            df_view["New?"] = df_view["is_new"].apply(lambda x: "⭐ New" if x else "")

            df_view = df_view.rename(
                columns={
                    "symbol": "Ticker",
                    "company_name": "Company Name",
                    "form": "Form",
                    "filing_detail_url": "Detail Link",
                    "primary_doc_url": "Document Link",
                }
            )

            st.dataframe(
                df_view[
                    [
                        "New?",
                        "Ticker",
                        "Company Name",
                        "Form",
                        "Filing Date",
                        "Acceptance Time",
                        "Detail Link",
                        "Document Link",
                    ]
                ],
                column_config={
                    "Detail Link": st.column_config.LinkColumn("Detail Link", display_text="Index Page"),
                    "Document Link": st.column_config.LinkColumn("Document Link", display_text="PDF/HTML Filing"),
                },
                hide_index=True,
                width="stretch",
            )

    # 3. Alerts Manager Tab
    with tab_alerts:
        st.subheader("Alert Setup & Rules")
        st.caption(
            "Define alert rules below. To evaluate alerts and send notifications, "
            "run the alert pipeline from the CLI: `python scripts/run_alerts.py`"
        )

        _render_active_alerts()
        _render_create_alert_form()

        st.markdown("---")
        _render_alert_history()


render_page()
