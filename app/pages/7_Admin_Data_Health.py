from __future__ import annotations

from datetime import UTC, date, datetime
import pandas as pd
import streamlit as st

from app.components.data_health import build_freshness_summary, render_freshness_card_html
from app.components.sidebar import render_sidebar_navigation
from argus.core.app_engine import create_migrated_database_engine
from argus.core.settings import settings
from argus.core.timezones import format_et_datetime


@st.cache_resource
def get_db_engine():
    return create_migrated_database_engine(settings.database_url)


def _load_health_data(today: date) -> dict[str, pd.DataFrame]:
    from argus.services.data_health_service import load_data_health_info
    engine = get_db_engine()
    return load_data_health_info(engine, today)


def _format_dt(val) -> str:
    if val is None or pd.isna(val):
        return "N/A"
    formatted = format_et_datetime(val)
    return formatted if formatted != "Never" else str(val)


def render_page() -> None:
    render_sidebar_navigation()
    st.title("🛡️ Admin & Data Health Dashboard")
    st.markdown(
        "Monitor pipeline executions, rate-limits, provider configurations, and database freshness warnings."
    )

    # Fetch stats
    today = datetime.now(UTC).date()
    health_data = _load_health_data(today)

    tab_overview, tab_pipelines, tab_providers, tab_integrity = st.tabs(
        [
            "🔍 System Overview & Freshness",
            "⚙️ Pipeline Executions",
            "🌐 Provider Health & Usage",
            "⚠️ Data Integrity & Audits",
        ]
    )

    # 1. Overview Tab
    with tab_overview:
        st.subheader("Data Freshness Audits")
        freshness_summary = build_freshness_summary(health_data, today)

        if freshness_summary.stale_items:
            st.error("🚨 Stale Datasets Detected!")
            for item in freshness_summary.stale_items:
                st.markdown(f"**{item.name}**: {item.reason}")
                st.code(item.command, language="bash")
        else:
            st.success("✅ All core datasets are fresh (updated within the last 3 days).")

        st.divider()
        st.subheader("Freshness Summary")

        # Inject custom CSS for freshness cards grid
        st.markdown(
            """
            <style>
            .freshness-grid {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 16px;
                margin-top: 12px;
                margin-bottom: 20px;
            }
            .freshness-card {
                background: linear-gradient(135deg, rgba(22, 27, 34, 0.4) 0%, rgba(17, 22, 29, 0.5) 100%);
                border: 1px solid rgba(240, 246, 252, 0.1);
                border-radius: 10px;
                padding: 14px 16px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }
            .freshness-card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .freshness-title {
                font-size: 11px;
                color: #8b949e;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.8px;
            }
            .status-indicator {
                display: inline-flex;
                align-items: center;
                font-size: 10px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                padding: 2px 8px;
                border-radius: 12px;
            }
            .status-indicator.fresh {
                color: #3fb950;
                background: rgba(46, 160, 67, 0.12);
                border: 1px solid rgba(46, 160, 67, 0.2);
            }
            .status-indicator.stale {
                color: #f85149;
                background: rgba(248, 81, 73, 0.12);
                border: 1px solid rgba(248, 81, 73, 0.2);
            }
            .status-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                margin-right: 5px;
                display: inline-block;
            }
            .status-indicator.fresh .status-dot {
                background-color: #3fb950;
                box-shadow: 0 0 6px rgba(46, 160, 67, 0.8);
            }
            .status-indicator.stale .status-dot {
                background-color: #f85149;
                box-shadow: 0 0 6px rgba(248, 81, 73, 0.8);
            }
            .freshness-value {
                display: flex;
                align-items: baseline;
                flex-wrap: wrap;
                margin-top: 4px;
            }
            .freshness-val-date {
                font-size: 14px;
                font-weight: 600;
                color: #f0f6fc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            }
            .freshness-val-time {
                font-size: 12px;
                color: #8b949e;
                margin-left: 6px;
                font-weight: 400;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            }
            .freshness-val-na {
                font-size: 14px;
                font-weight: 600;
                color: #484f58;
            }
            @media (max-width: 768px) {
                .freshness-grid {
                    grid-template-columns: 1fr;
                }
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="freshness-grid">
                {"".join(render_freshness_card_html(card) for card in freshness_summary.cards)}
            </div>
            """,
            unsafe_allow_html=True,
        )

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
                p_display[
                    ["job_name", "status", "started_at", "finished_at", "rows_read", "rows_written"]
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "job_name": "Pipeline Job",
                    "status": "Latest Status",
                    "started_at": "Started At",
                    "finished_at": "Finished At",
                    "rows_read": "Rows Read",
                    "rows_written": "Rows Written",
                },
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
                },
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
                h_display[
                    [
                        "provider",
                        "status",
                        "failure_count",
                        "disabled_until",
                        "last_success_at",
                        "last_error",
                    ]
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "provider": "Provider Name",
                    "status": "Health Status",
                    "failure_count": "Failure Count",
                    "disabled_until": "Cooldown Active Until",
                    "last_success_at": "Last Success Time",
                    "last_error": "Last Provider Error",
                },
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
                u_display[
                    [
                        "provider",
                        "request_count",
                        "success_count",
                        "failure_count",
                        "rate_limit_count",
                        "last_request_time",
                    ]
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "provider": "Provider",
                    "request_count": "Total Requests",
                    "success_count": "Successes",
                    "failure_count": "Failures",
                    "rate_limit_count": "429 Rate Limits",
                    "last_request_time": "Last Request Time",
                },
            )

    # 4. Integrity Tab
    with tab_integrity:
        st.subheader("CIK Configurations Validation Audit")
        st.markdown(
            "Active companies must be configured with a 10-digit CIK code for filings and capex ingestion pipelines."
        )
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
                },
            )


if __name__ == "__main__":
    render_page()
