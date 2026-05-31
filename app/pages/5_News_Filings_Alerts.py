from __future__ import annotations

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


def _parse_job_time(val) -> str:
    if val is None or pd.isna(val):
        return "never"
    try:
        dt = pd.to_datetime(val)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(val)


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
        if st.button("Refresh / Clear Cache", use_container_width=True):
            load_news.clear()
            load_filings.clear()
            load_sources.clear()
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
                use_container_width=True,
            )

    # 3. Alerts Manager Placeholder Tab
    with tab_alerts:
        st.subheader("Alert Setup & Rules")
        st.info("Email notifications and rule configuration UI will be implemented in Phase 10.")
        st.markdown(
            """
            Planned Phase 10 alerting features:
            - **Rule-based Alerts:** Price threshold alerts (below/above target), crossed 50/200 DMA, low RSI crossover, and catalyst mentions.
            - **Email Notifications:** Configurable delivery to user emails via SMTP integration.
            - **Deduplication Engine:** Prevents duplicate notification delivery within 24 hours.
            """
        )


render_page()
