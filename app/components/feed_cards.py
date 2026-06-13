from __future__ import annotations

from html import escape
from textwrap import dedent

import pandas as pd

from app.auth_links import company_detail_url

FEED_CARD_STYLES = """
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
"""


def html_escape(value: object) -> str:
    return escape("" if value is None or pd.isna(value) else str(value), quote=True)


def html_block(markup: str) -> str:
    return "\n".join(line for line in dedent(markup).splitlines() if line.strip()).strip()


def sentiment_badge(score: float | None) -> str:
    if score is None:
        return '<span style="background: rgba(139, 148, 158, 0.15); color: #8b949e; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Sentiment: N/A</span>'

    if score > 0.05:
        return f'<span style="background: rgba(63, 185, 80, 0.15); color: #3fb950; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Positive ({score:+.2f})</span>'
    if score < -0.05:
        return f'<span style="background: rgba(248, 81, 73, 0.15); color: #f85149; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Negative ({score:.2f})</span>'
    return f'<span style="background: rgba(139, 148, 158, 0.15); color: #8b949e; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Neutral ({score:+.2f})</span>'


def relevance_badge(score: float | None) -> str:
    if score is None:
        return '<span style="background: rgba(139, 148, 158, 0.15); color: #8b949e; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Relevance: N/A</span>'
    return f'<span style="background: rgba(56, 139, 253, 0.15); color: #58a6ff; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;">Relevance: {score * 100:.0f}%</span>'


def ticker_badges(tickers_str: str | None) -> str:
    if not tickers_str:
        return ""
    badges = []
    for ticker_value in sorted(tickers_str.split(",")):
        ticker_clean = ticker_value.strip()
        if ticker_clean:
            ticker = escape(ticker_clean, quote=True)
            url = html_escape(company_detail_url(ticker_clean))
            badges.append(
                f'<a href="{url}" target="_self" style="text-decoration: none; background: rgba(188, 140, 255, 0.15); color: #bc8cff; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-right: 4px;">{ticker}</a>'
            )
    return "".join(badges)


def render_news_feed_card(
    *,
    time_str: str,
    title: object,
    summary: object,
    url: object,
    source_name: object,
    provider: object,
    tickers: str | None,
    sentiment_score: float | None,
    relevance_score: float | None,
) -> str:
    return html_block(
        f"""
        <div class="feed-card">
            <div class="feed-header">
                <div>
                    <span class="type-badge-news">News</span>
                    <span style="margin-left: 8px; font-weight: bold; color: #58a6ff;">{html_escape(source_name)}</span>
                </div>
                <span style="font-size: 13px; color: #8b949e;">{html_escape(time_str)}</span>
            </div>
            <div class="feed-title"><a href="{html_escape(url)}" target="_blank" style="color: #c9d1d9; text-decoration: none;">{html_escape(title)}</a></div>
            <div class="feed-summary">{html_escape(summary)}</div>
            <div class="feed-badges">
                {ticker_badges(tickers)}
                {sentiment_badge(sentiment_score)}
                {relevance_badge(relevance_score)}
                <span style="font-size: 12px; color: #8b949e; margin-left: auto;">Provider: {html_escape(provider).upper()}</span>
            </div>
        </div>
        """
    )


def render_filing_feed_card(
    *,
    time_str: str,
    ticker: str,
    company_name: object,
    form: object,
    filing_detail_url: object,
    primary_doc_url: object | None,
    is_new: bool,
) -> str:
    ticker_text = html_escape(ticker)
    ticker_url = html_escape(company_detail_url(ticker))
    ticker_badge = (
        f'<a href="{ticker_url}" target="_self" style="text-decoration: none; background: rgba(188, 140, 255, 0.15); color: #bc8cff; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-right: 8px;">{ticker_text}</a>'
    )
    raw_document_link = (
        f'<a href="{html_escape(primary_doc_url)}" target="_blank" style="background: rgba(139, 148, 158, 0.15); color: #c9d1d9; padding: 4px 12px; border-radius: 4px; font-size: 13px; text-decoration: none; font-weight: 600;">Raw SEC Document</a>'
        if primary_doc_url
        else ""
    )
    new_marker = (
        "&#11088; <span style='color: #f2c94c; font-weight: bold; font-size: 12px; margin-right: 8px;'>NEW</span>"
        if is_new
        else ""
    )

    return html_block(
        f"""
        <div class="feed-card">
            <div class="feed-header">
                <div>
                    <span class="type-badge-filing">SEC Filing</span>
                    <span style="margin-left: 8px; font-weight: bold; color: #f78166;">{html_escape(form)}</span>
                </div>
                <span style="font-size: 13px; color: #8b949e;">{html_escape(time_str)}</span>
            </div>
            <div class="feed-title" style="color: #c9d1d9;">
                {new_marker}
                {ticker_badge}
                <strong>{html_escape(company_name)}</strong>
            </div>
            <div class="feed-summary">Official {html_escape(form)} filing submitted to the SEC.</div>
            <div class="feed-badges">
                <a href="{html_escape(filing_detail_url)}" target="_blank" style="background: rgba(56, 139, 253, 0.15); color: #58a6ff; padding: 4px 12px; border-radius: 4px; font-size: 13px; text-decoration: none; font-weight: 600;">SEC Filing Page</a>
                {raw_document_link}
            </div>
        </div>
        """
    )
