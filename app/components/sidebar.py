import streamlit as st
import pandas as pd
from datetime import UTC, datetime
from argus.services.company_service import get_company_options
from argus.core.app_engine import create_migrated_database_engine
from argus.core.settings import settings

@st.cache_data(ttl=60)
def get_system_health_status() -> tuple[str, str]:
    from sqlalchemy import text
    engine = create_migrated_database_engine(settings.database_url)
    with engine.connect() as conn:
        latest_dates = pd.read_sql_query(
            text(
                """
                SELECT
                    (SELECT MAX(date) FROM price_bars WHERE provider = :provider AND interval = '1d') AS latest_price_date,
                    (SELECT MAX(date) FROM daily_metrics) AS latest_metrics_date
                """
            ),
            conn,
            params={"provider": settings.market_data_provider},
        )
        
        failed_job_df = pd.read_sql_query(
            text(
                """
                SELECT jr.job_name, jr.finished_at, jr.error_text
                FROM job_runs jr
                JOIN (
                    SELECT job_name, MAX(id) AS max_id
                    FROM job_runs
                    GROUP BY job_name
                ) latest ON jr.id = latest.max_id
                WHERE jr.status = 'failed'
                LIMIT 1
                """
            ),
            conn,
        )
        
    def _parse_date(val):
        if val is None or pd.isna(val):
            return None
        return pd.to_datetime(val).date()
        
    latest_price_date = _parse_date(latest_dates.at[0, "latest_price_date"])
    latest_metrics_date = _parse_date(latest_dates.at[0, "latest_metrics_date"])
    failed_job = not failed_job_df.empty
    
    today = datetime.now(UTC).date()
    stale_days_threshold = 3
    
    stale_reasons = []
    if latest_price_date is None:
        stale_reasons.append("No price data found.")
    elif (today - latest_price_date).days > stale_days_threshold:
        stale_reasons.append("Prices are stale.")
        
    if latest_metrics_date is None:
        stale_reasons.append("No metrics data found.")
    elif (today - latest_metrics_date).days > stale_days_threshold:
        stale_reasons.append("Metrics are stale.")
        
    if failed_job:
        return "🔴 Pipeline Failed", "#f85149"
    elif stale_reasons:
        return "🟡 Data Warnings", "#f0883e"
    else:
        return "🟢 Systems Fresh", "#3fb950"

def render_sidebar_navigation() -> None:
    symbols = get_company_options()
    if not symbols:
        return
    
    with st.sidebar:
        st.write("---")
        st.subheader("🔍 Quick Ticker Detail")
        options = ["Select..."] + symbols
        selected_ticker = st.selectbox(
            "Go to Company Detail:",
            options,
            index=0,
            key="sidebar_ticker_selectbox"
        )
        if selected_ticker != "Select...":
            st.session_state.selected_ticker = selected_ticker
            st.switch_page("pages/3_Company_Detail.py")

        st.write("---")
        health_status, health_color = get_system_health_status()
        st.markdown(
            f"""
            <div style='text-align: center; margin-top: 30px; padding: 10px 0;'>
                <span style='background-color: rgba(22, 27, 34, 0.6); color: {health_color}; border: 1px solid {health_color}33; border-radius: 20px; padding: 6px 12px; font-size: 14px; font-weight: 600; white-space: nowrap;'>
                    {health_status}
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )
