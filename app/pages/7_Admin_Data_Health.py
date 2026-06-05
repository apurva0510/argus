from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import pandas as pd
import streamlit as st

from app.components.sidebar import render_sidebar_navigation
from argus.core.app_engine import create_migrated_database_engine
from argus.core.settings import settings
from sqlalchemy import text


@st.cache_resource
def get_db_engine():
    return create_migrated_database_engine(settings.database_url)


def _load_health_data(today: date) -> dict[str, pd.DataFrame]:
    engine = get_db_engine()
    data = {}

    with engine.connect() as conn:
        # 1. Pipeline status
        data["pipeline_status"] = pd.read_sql_query(
            text(
                """
                SELECT jr.job_name, jr.started_at, jr.finished_at, jr.status, jr.rows_read, jr.rows_written, jr.error_text
                FROM job_runs jr
                JOIN (
                    SELECT job_name, MAX(id) as max_id
                    FROM job_runs
                    GROUP BY job_name
                ) latest ON jr.id = latest.max_id
                ORDER BY jr.job_name ASC
                """
            ),
            conn,
        )

        # 2. Provider Health
        data["provider_health"] = pd.read_sql_query(
            text(
                """
                SELECT provider, status, failure_count, disabled_until, last_success_at, last_failure_at, last_error
                FROM provider_health
                ORDER BY provider ASC
                """
            ),
            conn,
        )

        # 3. Provider Daily Usage
        data["provider_usage"] = pd.read_sql_query(
            text(
                """
                SELECT provider, request_count, success_count, failure_count, rate_limit_count, last_request_time
                FROM provider_daily_usage
                WHERE date = :today
                ORDER BY provider ASC
                """
            ),
            conn,
            params={"today": today.isoformat()},
        )

        # 4. CIK Integrity
        data["cik_integrity"] = pd.read_sql_query(
            text(
                """
                SELECT symbol, name, CIK as cik
                FROM companies
                WHERE is_active = TRUE AND (CIK IS NULL OR CIK = '' OR LENGTH(CIK) != 10)
                ORDER BY symbol ASC
                """
            ),
            conn,
        )

        # 5. Recent Errors
        data["recent_errors"] = pd.read_sql_query(
            text(
                """
                SELECT id, job_name, started_at, finished_at, status, error_text
                FROM job_runs
                WHERE status = 'failed'
                ORDER BY id DESC
                LIMIT 10
                """
            ),
            conn,
        )

        # 6. Latest Dates for Stale Checks
        data["latest_prices"] = pd.read_sql_query(text("SELECT MAX(date) as val FROM price_bars"), conn)
        data["latest_metrics"] = pd.read_sql_query(text("SELECT MAX(date) as val FROM daily_metrics"), conn)
        data["latest_macro"] = pd.read_sql_query(text("SELECT MAX(observation_date) as val FROM macro_observations"), conn)
        data["latest_news"] = pd.read_sql_query(text("SELECT MAX(published_at) as val FROM news_items"), conn)
        data["latest_filings"] = pd.read_sql_query(text("SELECT MAX(filing_date) as val FROM sec_filings"), conn)
        data["latest_signals"] = pd.read_sql_query(text("SELECT MAX(date) as val FROM signal_daily"), conn)

    return data


def _parse_date(val) -> date | None:
    if val is None or pd.isna(val):
        return None
    return pd.to_datetime(val).date()


def _format_dt(val) -> str:
    if val is None or pd.isna(val):
        return "N/A"
    return pd.to_datetime(val).strftime("%Y-%m-%d %H:%M:%S")


def render_page() -> None:
    render_sidebar_navigation()
    st.title("🛡️ Admin & Data Health Dashboard")
    st.markdown("Monitor pipeline executions, rate-limits, provider configurations, and database freshness warnings.")

    # Fetch stats
    today = datetime.now(UTC).date()
    health_data = _load_health_data(today)

    tab_overview, tab_pipelines, tab_providers, tab_integrity = st.tabs([
        "🔍 System Overview & Freshness",
        "⚙️ Pipeline Executions",
        "🌐 Provider Health & Usage",
        "⚠️ Data Integrity & Audits",
    ])

    # 1. Overview Tab
    with tab_overview:
        st.subheader("Data Freshness Audits")

        price_date = _parse_date(health_data["latest_prices"].at[0, "val"])
        metrics_date = _parse_date(health_data["latest_metrics"].at[0, "val"])
        macro_date = _parse_date(health_data["latest_macro"].at[0, "val"])
        news_date = _parse_date(health_data["latest_news"].at[0, "val"])
        filings_date = _parse_date(health_data["latest_filings"].at[0, "val"])
        signals_date = _parse_date(health_data["latest_signals"].at[0, "val"])

        stale_threshold = today - timedelta(days=3)

        stale_items = []
        fresh_items = []

        datasets = [
            ("Price Bars", price_date, "python scripts/run_daily_refresh.py"),
            ("Daily Metrics", metrics_date, "python scripts/compute_metrics.py"),
            ("Macro Observations", macro_date, "python scripts/refresh_macro.py"),
            ("News Items", news_date, "python scripts/refresh_news.py"),
            ("SEC Filings", filings_date, "python scripts/refresh_filings.py"),
            ("Daily Signals", signals_date, "python scripts/compute_signals.py"),
        ]

        for name, l_date, cmd in datasets:
            if l_date is None:
                stale_items.append((name, "No data present", cmd))
            elif l_date < stale_threshold:
                stale_items.append((name, f"Stale since {l_date.isoformat()} (Older than 3 days)", cmd))
            else:
                fresh_items.append((name, f"Fresh (latest: {l_date.isoformat()})"))

        if stale_items:
            st.error("🚨 Stale Datasets Detected!")
            for name, reason, cmd in stale_items:
                st.markdown(f"**{name}**: {reason}")
                st.code(cmd, language="bash")
        else:
            st.success("✅ All core datasets are fresh (updated within the last 3 days).")

        st.divider()
        st.subheader("Freshness Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Latest Prices", price_date.isoformat() if price_date else "N/A")
            st.metric("Latest News", news_date.isoformat() if news_date else "N/A")
        with col2:
            st.metric("Latest Metrics", metrics_date.isoformat() if metrics_date else "N/A")
            st.metric("Latest Filings", filings_date.isoformat() if filings_date else "N/A")
        with col3:
            st.metric("Latest Signals", signals_date.isoformat() if signals_date else "N/A")
            st.metric("Latest Macro", macro_date.isoformat() if macro_date else "N/A")

    # 2. Pipelines Tab
    with tab_pipelines:
        st.subheader("Pipeline Run Statuses")
        p_df = health_data["pipeline_status"]
        if p_df.empty:
            st.info("No pipeline run records found.")
        else:
            p_display = p_df.copy()
            p_display["started_at"] = p_display["started_at"].apply(_format_dt)
            p_display["finished_at"] = p_display["finished_at"].apply(_format_dt)
            st.dataframe(
                p_display[["job_name", "status", "started_at", "finished_at", "rows_read", "rows_written"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "job_name": "Pipeline Job",
                    "status": "Latest Status",
                    "started_at": "Started At",
                    "finished_at": "Finished At",
                    "rows_read": "Rows Read",
                    "rows_written": "Rows Written",
                }
            )

        st.divider()
        st.subheader("Recent Run Failures")
        err_df = health_data["recent_errors"]
        if err_df.empty:
            st.success("No pipeline failures recorded in the database.")
        else:
            err_display = err_df.copy()
            err_display["started_at"] = err_display["started_at"].apply(_format_dt)
            st.dataframe(
                err_display[["job_name", "started_at", "error_text"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "job_name": "Job Name",
                    "started_at": "Failed At",
                    "error_text": "Error Description",
                }
            )

    # 3. Providers Tab
    with tab_providers:
        st.subheader("Provider Health Status & Cooldowns")
        h_df = health_data["provider_health"]
        if h_df.empty:
            st.info("No provider health tracking records found.")
        else:
            h_display = h_df.copy()
            h_display["disabled_until"] = h_display["disabled_until"].apply(
                lambda x: _format_dt(x) if pd.notna(x) else "No Active Cooldown"
            )
            h_display["last_success_at"] = h_display["last_success_at"].apply(_format_dt)
            st.dataframe(
                h_display[["provider", "status", "failure_count", "disabled_until", "last_success_at", "last_error"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "provider": "Provider Name",
                    "status": "Health Status",
                    "failure_count": "Failure Count",
                    "disabled_until": "Cooldown Active Until",
                    "last_success_at": "Last Success Time",
                    "last_error": "Last Provider Error",
                }
            )

        st.divider()
        st.subheader("Provider Daily Usage Statistics (Today)")
        u_df = health_data["provider_usage"]
        if u_df.empty:
            st.info("No request logs recorded for today yet.")
        else:
            u_display = u_df.copy()
            u_display["last_request_time"] = u_display["last_request_time"].apply(_format_dt)
            st.dataframe(
                u_display[["provider", "request_count", "success_count", "failure_count", "rate_limit_count", "last_request_time"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "provider": "Provider",
                    "request_count": "Total Requests",
                    "success_count": "Successes",
                    "failure_count": "Failures",
                    "rate_limit_count": "429 Rate Limits",
                    "last_request_time": "Last Request Time",
                }
            )

    # 4. Integrity Tab
    with tab_integrity:
        st.subheader("CIK Configurations Validation Audit")
        st.markdown("Active companies must be configured with a 10-digit CIK code for filings and capex ingestion pipelines.")
        cik_df = health_data["cik_integrity"]
        if cik_df.empty:
            st.success("All active symbols are configured with valid 10-digit CIK identifiers.")
        else:
            st.warning("Issues detected with CIK settings!")
            st.dataframe(
                cik_df,
                hide_index=True,
                width="stretch",
                column_config={
                    "symbol": "Company Symbol",
                    "name": "Company Name",
                    "cik": "Configured CIK (Invalid or Missing)",
                }
            )


if __name__ == "__main__":
    render_page()
