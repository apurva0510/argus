from __future__ import annotations

import json
from datetime import UTC, date, datetime
import pandas as pd
import streamlit as st

from app.components.sidebar import render_sidebar_navigation
from argus.core.app_engine import create_migrated_database_engine
from argus.core.settings import settings
from argus.services.company_service import get_company_options
from argus.services.alert_service import (
    get_all_alerts,
    get_recent_alert_events,
    create_alert,
    toggle_alert,
    delete_alert,
)
from sqlalchemy import text


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
    return create_migrated_database_engine(settings.database_url)


@st.cache_data(ttl=60)
def load_earnings_calendar(today: date) -> pd.DataFrame:
    query = """
        SELECT
            ee.event_date,
            c.symbol,
            c.name as company_name,
            ee.fiscal_period,
            ee.source
        FROM earnings_events ee
        JOIN companies c ON c.id = ee.company_id
        WHERE ee.event_date >= :today
        ORDER BY ee.event_date ASC, c.symbol ASC
    """
    with get_db_engine().connect() as conn:
        return pd.read_sql_query(text(query), conn, params={"today": today.isoformat()})


@st.cache_data(ttl=60)
def load_macro_calendar(today: date) -> pd.DataFrame:
    query = """
        SELECT
            mre.release_date,
            mre.series_code,
            mre.event_name,
            mre.status
        FROM macro_release_events mre
        WHERE mre.release_date >= :today
        ORDER BY mre.release_date ASC
    """
    with get_db_engine().connect() as conn:
        return pd.read_sql_query(text(query), conn, params={"today": today.isoformat()})


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
        if dt.tz is None:
            dt = dt.tz_localize("UTC")
        else:
            dt = dt.tz_convert("UTC")
        return dt.tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        return str(val)


def _render_create_alert_form() -> None:
    st.markdown("### ➕ Create New Alert")
    with st.form("create_alert_form", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        with col_a:
            alert_name = st.text_input("Alert Name", placeholder="e.g., NVDA price drop alert")
        with col_b:
            rule_type = st.selectbox("Rule Type", options=RULE_TYPES)

        st.caption(RULE_DESCRIPTIONS.get(rule_type, ""))

        col_c, col_d = st.columns(2)
        with col_c:
            tickers = ["— None (use watchlist) —"] + get_company_options()
            selected_ticker = st.selectbox("Target Company", options=tickers, key="alert_ticker")
        with col_d:
            st.caption("Or leave company blank to target a whole watchlist (future).")

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
                        st.cache_data.clear()
                        st.rerun()


def _render_active_alerts() -> None:
    st.markdown("### 📋 Active Alert Rules")
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
                from app.auth_links import company_detail_url
                ticker = row.get("ticker")
                if ticker:
                    target_link = f"[{ticker}]({company_detail_url(ticker)})"
                else:
                    target_link = f"`{row.get('watchlist') or 'All'}`"
                config_str = ""
                if row.get("config_json"):
                    try:
                        cfg = row["config_json"] if isinstance(row["config_json"], dict) else json.loads(row["config_json"])
                        config_str = " | ".join(f"{k}={v}" for k, v in cfg.items())
                    except Exception:
                        config_str = str(row["config_json"])

                st.markdown(
                    f"{status_icon} **{row['name']}** — `{row['rule_type']}` → {target_link}"
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
                    st.cache_data.clear()
                    st.rerun()
            with c4:
                if st.button("🗑️", key=f"delete_{alert_id}"):
                    delete_alert(alert_id)
                    load_alerts.clear()
                    load_alert_history.clear()
                    st.cache_data.clear()
                    st.rerun()

        st.divider()


def _render_alert_history() -> None:
    st.markdown("### 📜 Alert Trigger History")
    history_df = load_alert_history(limit=50)
    if history_df.empty:
        st.info("No alert events recorded yet. Run the alert pipeline via CLI: `python scripts/run_alerts.py`")
        return

    display = history_df.copy()
    triggered_dt = pd.to_datetime(display["triggered_at"])
    if triggered_dt.dt.tz is None:
        triggered_dt = triggered_dt.dt.tz_localize("UTC")
    display["triggered_at"] = triggered_dt.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d %I:%M %p")

    def _status_badge(status):
        if status == "sent":
            return "✅ Sent"
        elif status == "failed":
            return "❌ Failed"
        return "⏭️ Skipped"

    display["delivery"] = display["delivery_status"].apply(_status_badge)

    from app.auth_links import company_detail_url
    display["ticker"] = display["ticker"].apply(lambda t: company_detail_url(t) if t else "")

    st.dataframe(
        display[["alert_name", "event_type", "ticker", "triggered_at", "delivery"]],
        hide_index=True,
        width="stretch",
        column_config={
            "alert_name": "Alert",
            "event_type": "Rule Type",
            "ticker": st.column_config.LinkColumn("Ticker", display_text=r"ticker=([^&]+)"),
            "triggered_at": "Triggered At",
            "delivery": "Delivery Status",
        },
    )


def render_page() -> None:
    render_sidebar_navigation()
    st.title("🗓️ Calendar & Alerts")
    st.markdown("View upcoming events and manage custom automated alert triggers.")

    today = datetime.now(UTC).date()
    earnings_df = load_earnings_calendar(today)
    macro_df = load_macro_calendar(today)

    tab_earnings, tab_macro, tab_combined, tab_alert_rules, tab_alert_logs = st.tabs([
        "📅 Earnings Calendar",
        "🌍 Macro Release Calendar",
        "🔀 Combined Calendar",
        "🔔 Alerts Manager",
        "📜 Delivery Logs",
    ])

    # 1. Earnings Tab
    with tab_earnings:
        st.subheader("Upcoming Corporate Earnings Calls")
        if earnings_df.empty:
            st.info("No upcoming corporate earnings calls found in the database.")
        else:
            df_view = earnings_df.copy()
            df_view["event_date"] = pd.to_datetime(df_view["event_date"]).dt.strftime("%Y-%m-%d")
            df_view["fiscal_period"] = df_view["fiscal_period"].fillna("n/a")
            from app.auth_links import company_detail_url
            df_view["symbol"] = df_view["symbol"].apply(company_detail_url)
            
            st.dataframe(
                df_view[["event_date", "symbol", "company_name", "fiscal_period", "source"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "event_date": "Earnings Date",
                    "symbol": st.column_config.LinkColumn("Symbol", display_text=r"ticker=([^&]+)"),
                    "company_name": "Company Name",
                    "fiscal_period": "Fiscal Period",
                    "source": "Source",
                }
            )

    # 2. Macro Release Tab
    with tab_macro:
        st.subheader("Scheduled Macroeconomic Release Events")
        if macro_df.empty:
            st.info("No scheduled macroeconomic release schedules found. Register a FRED API key to populate.")
        else:
            df_view = macro_df.copy()
            df_view["release_date"] = pd.to_datetime(df_view["release_date"]).dt.strftime("%Y-%m-%d")
            st.dataframe(
                df_view[["release_date", "event_name", "series_code", "status"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "release_date": "Release Date",
                    "event_name": "Release Event",
                    "series_code": "FRED Series Code",
                    "status": "Status",
                }
            )

    # 3. Combined Tab
    with tab_combined:
        st.subheader("Combined Events Timeline")
        combined_events = []

        if not earnings_df.empty:
            for _, row in earnings_df.iterrows():
                fp = f" ({row['fiscal_period']})" if row["fiscal_period"] else ""
                combined_events.append({
                    "Date": pd.to_datetime(row["event_date"]),
                    "Type": "Earnings",
                    "Symbol": row["symbol"],
                    "Target / Description": f"{row['company_name']}{fp}",
                    "Source": row["source"],
                })

        if not macro_df.empty:
            for _, row in macro_df.iterrows():
                combined_events.append({
                    "Date": pd.to_datetime(row["release_date"]),
                    "Type": "Macro Release",
                    "Symbol": "",
                    "Target / Description": f"{row['event_name']} ({row['series_code']})",
                    "Source": "FRED API",
                })

        if not combined_events:
            st.info("No upcoming calendar events recorded.")
        else:
            combined_df = pd.DataFrame(combined_events).sort_values("Date", ascending=True)
            combined_df["Date"] = combined_df["Date"].dt.strftime("%Y-%m-%d")
            from app.auth_links import company_detail_url
            combined_df["Symbol"] = combined_df["Symbol"].apply(lambda s: company_detail_url(s) if s else "")
            
            st.dataframe(
                combined_df[["Date", "Type", "Symbol", "Target / Description", "Source"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "Date": "Date",
                    "Type": "Event Type",
                    "Symbol": st.column_config.LinkColumn("Symbol", display_text=r"ticker=([^&]+)"),
                    "Target / Description": "Target / Description",
                    "Source": "Source",
                }
            )

    # 4. Alerts Manager Tab
    with tab_alert_rules:
        _render_active_alerts()
        _render_create_alert_form()

    # 5. Delivery Logs Tab
    with tab_alert_logs:
        _render_alert_history()


if __name__ == "__main__":
    render_page()
