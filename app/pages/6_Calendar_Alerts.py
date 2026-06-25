from __future__ import annotations

import json
from datetime import UTC, date, datetime
from html import escape
import pandas as pd
import streamlit as st

from app.components.database import get_configured_app_engine
from app.components.sidebar import render_sidebar_navigation
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
    return get_configured_app_engine()


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
def load_historical_post_earnings_moves() -> dict[str, float]:
    """Return a dictionary mapping company symbol to its average absolute post-earnings move."""
    query = """
        SELECT
            c.symbol,
            AVG(ABS(cis.return_event_to_p1)) AS avg_move
        FROM catalyst_events ce
        JOIN companies c ON c.id = ce.company_id
        JOIN catalyst_impact_snapshots cis ON cis.catalyst_event_id = ce.id
        WHERE ce.event_type = 'earnings'
          AND cis.return_event_to_p1 IS NOT NULL
        GROUP BY c.symbol
    """
    with get_db_engine().connect() as conn:
        df = pd.read_sql_query(text(query), conn)
        return dict(zip(df["symbol"].str.upper(), df["avg_move"]))


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
        return dt.tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p ET")
    except Exception:
        return str(val)


def _format_alert_config(config_val) -> str:
    if config_val is None or pd.isna(config_val):
        return "No extra parameters"
    try:
        cfg = config_val if isinstance(config_val, dict) else json.loads(config_val)
    except Exception:
        return str(config_val)
    if not cfg:
        return "No extra parameters"
    return " · ".join(f"{key}: {value}" for key, value in cfg.items())


def _render_alert_rule_card(
    row: pd.Series, target_html: str, config_text: str, last_trigger: str
) -> str:
    enabled = bool(row["is_enabled"])
    status_class = "enabled" if enabled else "disabled"
    status_label = "Enabled" if enabled else "Disabled"
    return f"""
    <div style="
        background: linear-gradient(135deg, rgba(22, 27, 34, 0.4) 0%, rgba(17, 22, 29, 0.5) 100%);
        border: 1px solid rgba(240, 246, 252, 0.1);
        border-radius: 10px;
        padding: 14px 16px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        margin-bottom: 8px;
    ">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px;">
            <div style="font-size:16px; font-weight:700; color:#f0f6fc;">{escape(str(row["name"]), quote=True)}</div>
            <span class="alert-rule-status {status_class}">{status_label}</span>
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; color:#c9d1d9; font-size:13px;">
            <span style="color:#8b949e; font-weight:600; text-transform:uppercase; letter-spacing:0.6px;">{escape(str(row["rule_type"]), quote=True)}</span>
            <span style="color:#484f58;">-></span>
            <span>{target_html}</span>
        </div>
        <div style="margin-top:8px; color:#8b949e; font-size:12px;">{escape(config_text, quote=True)}</div>
        <div style="margin-top:6px; color:#8b949e; font-size:12px;">Last triggered: {escape(last_trigger, quote=True)}</div>
    </div>
    """


def _render_create_alert_form() -> None:
    st.markdown("### Create New Alert")
    col_a, col_b = st.columns(2)
    with col_a:
        alert_name = st.text_input("Alert Name", placeholder="e.g., NVDA price drop alert")
    with col_b:
        rule_type = st.selectbox("Rule Type", options=RULE_TYPES, key="alert_rule_type")

    st.caption(RULE_DESCRIPTIONS.get(rule_type, ""))

    tickers = ["— Select target company —"] + get_company_options()
    selected_ticker = st.selectbox("Target Company", options=tickers, key="alert_ticker")

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
        config["direction"] = st.selectbox("Cross Direction", options=["any", "above", "below"])
    elif rule_type == "new_sec_filing":
        forms_input = st.text_input(
            "Form Types (comma-separated, or leave blank for all)",
            placeholder="e.g., 10-K, 8-K",
        )
        if forms_input.strip():
            config["forms"] = [form.strip() for form in forms_input.split(",") if form.strip()]
    elif rule_type == "news_keyword_match":
        keywords_input = st.text_input(
            "Keywords (comma-separated)", placeholder="e.g., AI infrastructure, data center"
        )
        if keywords_input.strip():
            config["keywords"] = keywords_input
    elif rule_type == "earnings_within_days":
        config["days"] = st.number_input("Days Before Earnings", min_value=1, value=7, step=1)
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

    if st.button("Create Alert", type="primary"):
        if not alert_name.strip():
            st.error("Alert name is required.")
            return
        if selected_ticker == "— Select target company —":
            st.error("Select a target company before creating an alert.")
            return
        from argus.services.company_service import get_company_by_symbol

        company_info = get_company_by_symbol(selected_ticker)
        if not company_info:
            st.error("Selected company was not found.")
            return
        try:
            create_alert(
                name=alert_name.strip(),
                rule_type=rule_type,
                company_id=company_info["id"],
                config_json=config if config else None,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(f"Alert '{alert_name}' created successfully.")
            load_alerts.clear()
            st.cache_data.clear()
            st.rerun()
    return


def _render_active_alerts() -> None:
    st.markdown("### Active Alert Rules")
    alerts_df = load_alerts()
    if alerts_df.empty:
        st.info("No alert rules defined yet. Use the form below to create one.")
        return

    st.markdown(
        """
        <style>
        .alert-rule-status {
            display: inline-flex;
            align-items: center;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 3px 8px;
            border-radius: 12px;
        }
        .alert-rule-status.enabled {
            color: #3fb950;
            background: rgba(46, 160, 67, 0.12);
            border: 1px solid rgba(46, 160, 67, 0.2);
        }
        .alert-rule-status.disabled {
            color: #8b949e;
            background: rgba(139, 148, 158, 0.12);
            border: 1px solid rgba(139, 148, 158, 0.2);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for _, row in alerts_df.iterrows():
        alert_id = int(row["id"])
        enabled = bool(row["is_enabled"])
        last_trigger = _parse_job_time(row.get("last_triggered_at"))
        from app.auth_links import company_detail_url

        ticker = row.get("ticker")
        if ticker:
            safe_ticker = escape(str(ticker), quote=True)
            target_html = f'<a href="{company_detail_url(str(ticker))}" target="_self" style="color:#58a6ff; text-decoration:none; font-weight:700;">{safe_ticker}</a>'
        else:
            target_html = f'<span style="font-weight:700;">{escape(str(row.get("watchlist") or "All"), quote=True)}</span>'
        config_str = _format_alert_config(row.get("config_json"))

        with st.container():
            c1, c2, c3 = st.columns([7, 1, 1])
            with c1:
                st.markdown(
                    _render_alert_rule_card(row, target_html, config_str, last_trigger),
                    unsafe_allow_html=True,
                )
            with c2:
                new_state = not enabled
                btn_label = "Disable" if enabled else "Enable"
                if st.button(btn_label, key=f"toggle_{alert_id}"):
                    toggle_alert(alert_id, new_state)
                    load_alerts.clear()
                    st.cache_data.clear()
                    st.rerun()
            with c3:
                if st.button("🗑️", key=f"delete_{alert_id}"):
                    delete_alert(alert_id)
                    load_alerts.clear()
                    load_alert_history.clear()
                    st.cache_data.clear()
                    st.rerun()

        st.divider()


def _render_alert_history() -> None:
    st.markdown("### Alert Trigger History")
    history_df = load_alert_history(limit=50)
    if history_df.empty:
        st.info(
            "No alert events recorded yet. Run the alert pipeline via CLI: `python scripts/run_alerts.py`"
        )
        return

    display = history_df.copy()
    triggered_dt = pd.to_datetime(display["triggered_at"])
    if triggered_dt.dt.tz is None:
        triggered_dt = triggered_dt.dt.tz_localize("UTC")
    display["triggered_at"] = triggered_dt.dt.tz_convert("America/New_York").dt.strftime(
        "%Y-%m-%d %I:%M %p ET"
    )

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
    st.title("Calendar & Alerts")
    st.markdown("View upcoming events and manage custom automated alert triggers.")

    today = datetime.now(UTC).date()
    earnings_df = load_earnings_calendar(today)
    macro_df = load_macro_calendar(today)

    tab_earnings, tab_macro, tab_alert_rules, tab_alert_logs = st.tabs(
        [
            "Earnings Calendar",
            "Macro Release Calendar",
            "Alerts Manager",
            "Delivery Logs",
        ]
    )

    # 1. Earnings Tab
    with tab_earnings:
        st.subheader("Upcoming Corporate Earnings Calls")
        if earnings_df.empty:
            st.info("No upcoming corporate earnings calls found in the database.")
        else:
            moves_map = load_historical_post_earnings_moves()
            df_view = earnings_df.copy()
            df_view["Hist. Move Avg"] = df_view["symbol"].apply(
                lambda sym: f"{moves_map[sym.upper()] * 100:.1f}%" if sym.upper() in moves_map else "n/a"
            )
            df_view["event_date"] = pd.to_datetime(df_view["event_date"]).dt.strftime("%Y-%m-%d")
            df_view["fiscal_period"] = df_view["fiscal_period"].fillna("n/a")
            from app.auth_links import company_detail_url

            df_view["symbol"] = df_view["symbol"].apply(company_detail_url)

            st.dataframe(
                df_view[["event_date", "symbol", "company_name", "Hist. Move Avg", "fiscal_period", "source"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "event_date": "Earnings Date",
                    "symbol": st.column_config.LinkColumn("Symbol", display_text=r"ticker=([^&]+)"),
                    "company_name": "Company Name",
                    "Hist. Move Avg": "Hist. Post-Earnings Move (Avg)",
                    "fiscal_period": "Fiscal Period",
                    "source": "Source",
                },
            )

    # 2. Macro Release Tab
    with tab_macro:
        st.subheader("Scheduled Macroeconomic Release Events")
        if macro_df.empty:
            st.info(
                "No scheduled macroeconomic release schedules found. Register a FRED API key to populate."
            )
        else:
            df_view = macro_df.copy()
            df_view["release_date"] = pd.to_datetime(df_view["release_date"]).dt.strftime(
                "%Y-%m-%d"
            )
            st.dataframe(
                df_view[["release_date", "event_name", "series_code", "status"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "release_date": "Release Date",
                    "event_name": "Release Event",
                    "series_code": "FRED Series Code",
                    "status": "Status",
                },
            )

    # 3. Alerts Manager Tab
    with tab_alert_rules:
        _render_active_alerts()
        _render_create_alert_form()

    # 4. Delivery Logs Tab
    with tab_alert_logs:
        _render_alert_history()


if __name__ == "__main__":
    render_page()
