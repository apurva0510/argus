from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pandas as pd
import streamlit as st

from app.components.sidebar import render_sidebar_navigation
from argus.core.app_engine import create_migrated_database_engine
from argus.core.settings import settings
from argus.services.company_service import get_company_options
from argus.services.news_filings_service import (
    get_all_news_sources,
    get_filtered_filings,
    get_filtered_news,
)


@st.cache_resource
def get_db_engine():
    return create_migrated_database_engine(settings.database_url)


@st.cache_data(ttl=60)
def load_news(ticker, source, keyword, start_date, end_date, min_relevance, sentiment_band) -> pd.DataFrame:
    return get_filtered_news(
        get_db_engine(),
        ticker=ticker,
        source=source,
        keyword=keyword,
        start_date=start_date,
        end_date=end_date,
        min_relevance=min_relevance,
        sentiment_band=sentiment_band,
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
            badges.append(
                f'<a href="/Company_Detail?ticker={t_clean}" target="_self" style="text-decoration: none; background: rgba(188, 140, 255, 0.15); color: #bc8cff; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-right: 4px;">{t_clean}</a>'
            )
    return "".join(badges)


def render_page() -> None:
    render_sidebar_navigation()
    st.title("📰 News & SEC Filings")
    st.markdown("Stay informed with a combined real-time feed of company announcements, headlines, and official SEC filings.")

    # Custom styling for unified card feed
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

    with st.expander("🔍 Filter Options", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            tickers = ["All"] + get_company_options()
            selected_ticker = st.selectbox("Company / Ticker Filter", options=tickers)
            item_type = st.selectbox("Item Type", options=["All", "News Only", "Filing Only"])
        
        with col2:
            default_start = (datetime.now(UTC) - timedelta(days=30)).date()
            default_end = datetime.now(UTC).date()
            selected_start = st.date_input("Start Date", value=default_start)
            selected_end = st.date_input("End Date", value=default_end)

        with col3:
            if item_type == "News Only":
                forms = ["All"]
                selected_form = "All"
            else:
                forms = ["All", "10-K", "10-Q", "8-K", "6-K", "20-F", "40-F"]
                selected_form = st.selectbox("Form Type Filter", options=forms)

            if item_type == "Filing Only":
                selected_source = "All"
                min_relevance = 0.0
                sentiment_band = "All"
            else:
                sources = ["All"] + load_sources()
                selected_source = st.selectbox("Filter by Source", options=sources)

        if item_type != "Filing Only":
            col4, col5 = st.columns(2)
            with col4:
                min_relevance = st.slider("Minimum Relevance", min_value=0.0, max_value=1.0, value=0.0, step=0.1)
            with col5:
                sentiment_band = st.selectbox("Sentiment Band", options=["All", "Positive", "Neutral", "Negative"])
        else:
            min_relevance = 0.0
            sentiment_band = "All"

    search_keyword = st.text_input("📝 Search headlines, summary or keywords")

    news_df = pd.DataFrame()
    filings_df = pd.DataFrame()

    # News does not have form types. If a specific form type filter is active, do not load news.
    if item_type in ("All", "News Only") and selected_form == "All":
        news_df = load_news(
            selected_ticker,
            selected_source,
            search_keyword if search_keyword.strip() else None,
            selected_start,
            selected_end,
            min_relevance if min_relevance > 0 else None,
            sentiment_band,
        )
    # SEC filings do not have news sources. If a specific news source filter is active, do not load filings.
    if item_type in ("All", "Filing Only") and selected_source == "All":
        filings_df = load_filings(
            selected_ticker,
            selected_form,
            selected_start,
            selected_end,
        )

    # Combine news and filings
    combined_items = []

    if not news_df.empty:
        for _, row in news_df.iterrows():
            combined_items.append({
                "type": "news",
                "timestamp": pd.to_datetime(row["published_at"]),
                "title": row["title"],
                "summary": row["summary"],
                "url": row["url"],
                "source_name": row["source_name"],
                "provider": row["provider"],
                "tickers": row["tickers"],
                "keywords": row["keywords"],
                "sentiment_score": row["sentiment_score"],
                "relevance_score": row["relevance_score"],
            })

    if not filings_df.empty:
        for _, row in filings_df.iterrows():
            # Apply keyword filter manually if present
            if search_keyword.strip():
                kw = search_keyword.strip().lower()
                symbol_match = kw in str(row["symbol"]).lower()
                company_match = kw in str(row["company_name"]).lower()
                form_match = kw in str(row["form"]).lower()
                if not (symbol_match or company_match or form_match):
                    continue

            ts = pd.to_datetime(row["acceptance_datetime"]) if pd.notna(row["acceptance_datetime"]) else pd.to_datetime(row["filing_date"])
            combined_items.append({
                "type": "filing",
                "timestamp": ts,
                "ticker": row["symbol"],
                "company_name": row["company_name"],
                "form": row["form"],
                "filing_detail_url": row["filing_detail_url"],
                "primary_doc_url": row["primary_doc_url"],
                "is_new": bool(row["is_new"]),
            })

    # Sort descending
    combined_items.sort(key=lambda x: x["timestamp"], reverse=True)

    if not combined_items:
        st.info("No items found matching the current filters.")
        return

    # Render unified list
    for item in combined_items:
        time_str = item["timestamp"].strftime("%b %d, %Y %I:%M %p")
        
        if item["type"] == "news":
            sentiment_html = _sentiment_badge(item["sentiment_score"])
            relevance_html = _relevance_badge(item["relevance_score"])
            tickers_html = _ticker_badges(item["tickers"])
            
            st.markdown(
                f"""
                <div class="feed-card">
                    <div class="feed-header">
                        <div>
                            <span class="type-badge-news">News</span>
                            <span style="margin-left: 8px; font-weight: bold; color: #58a6ff;">{item['source_name']}</span>
                        </div>
                        <span style="font-size: 13px; color: #8b949e;">{time_str}</span>
                    </div>
                    <div class="feed-title"><a href="{item['url']}" target="_blank" style="color: #c9d1d9; text-decoration: none;">{item['title']}</a></div>
                    <div class="feed-summary">{item['summary'] or ''}</div>
                    <div class="feed-badges">
                        {tickers_html}
                        {sentiment_html}
                        {relevance_html}
                        <span style="font-size: 12px; color: #8b949e; margin-left: auto;">Provider: {item['provider'].upper()}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            
        else:
            new_star = "⭐ <span style='color: #f2c94c; font-weight: bold; font-size: 12px; margin-right: 8px;'>NEW</span>" if item["is_new"] else ""
            ticker_badge = f'<a href="/Company_Detail?ticker={item["ticker"]}" target="_self" style="text-decoration: none; background: rgba(188, 140, 255, 0.15); color: #bc8cff; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-right: 8px;">{item["ticker"]}</a>'
            
            st.markdown(
                f"""
                <div class="feed-card">
                    <div class="feed-header">
                        <div>
                            <span class="type-badge-filing">SEC Filing</span>
                            <span style="margin-left: 8px; font-weight: bold; color: #f78166;">{item['form']}</span>
                        </div>
                        <span style="font-size: 13px; color: #8b949e;">{time_str}</span>
                    </div>
                    <div class="feed-title" style="color: #c9d1d9;">
                        {new_star}
                        {ticker_badge}
                        <strong>{item['company_name']}</strong>
                    </div>
                    <div class="feed-summary">Official {item['form']} filing submitted to the SEC.</div>
                    <div class="feed-badges">
                        <a href="{item['filing_detail_url']}" target="_blank" style="background: rgba(139, 148, 158, 0.15); color: #c9d1d9; padding: 4px 12px; border-radius: 4px; font-size: 13px; text-decoration: none; font-weight: 600;">Filing Index</a>
                        <a href="{item['primary_doc_url']}" target="_blank" style="background: rgba(56, 139, 253, 0.15); color: #58a6ff; padding: 4px 12px; border-radius: 4px; font-size: 13px; text-decoration: none; font-weight: 600;">View Document</a>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


if __name__ == "__main__":
    render_page()
