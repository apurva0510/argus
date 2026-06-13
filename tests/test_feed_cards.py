from app.components.feed_cards import (
    html_block,
    render_filing_feed_card,
    render_news_feed_card,
    ticker_badges,
)


def test_html_block_removes_optional_blank_lines() -> None:
    rendered = html_block(
        """
        <div>
            {optional_empty}
            <a href="/Company_Detail?ticker=GOOGL">GOOGL</a>
        </div>
        """.format(optional_empty="")
    )

    assert "\n\n" not in rendered
    assert rendered.startswith("<div>")
    assert '<a href="/Company_Detail?ticker=GOOGL">GOOGL</a>' in rendered


def test_ticker_badges_sort_and_escape_tickers() -> None:
    rendered = ticker_badges("NVDA, A<B")

    assert rendered.index("A&lt;B") < rendered.index("NVDA")
    assert "/Company_Detail?ticker=A&lt;B" in rendered
    assert "/Company_Detail?ticker=NVDA" in rendered


def test_news_feed_card_escapes_content_and_renders_badges() -> None:
    rendered = render_news_feed_card(
        time_str="Jun 12, 2026 09:30 AM ET",
        title='A&B "wins"',
        summary="<script>alert(1)</script>",
        url='https://example.com/?q="x"',
        source_name="Source <One>",
        provider="rss",
        tickers="NVDA",
        sentiment_score=0.2,
        relevance_score=0.75,
    )

    assert "A&amp;B &quot;wins&quot;" in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert 'href="https://example.com/?q=&quot;x&quot;"' in rendered
    assert "Positive (+0.20)" in rendered
    assert "Relevance: 75%" in rendered
    assert "Provider: RSS" in rendered


def test_filing_feed_card_omits_raw_document_when_missing() -> None:
    rendered = render_filing_feed_card(
        time_str="Jun 12, 2026",
        ticker="NVDA",
        company_name="Nvidia",
        form="8-K",
        filing_detail_url="https://sec.example/filing",
        primary_doc_url=None,
        is_new=True,
    )

    assert "SEC Filing" in rendered
    assert "NEW" in rendered
    assert "Raw SEC Document" not in rendered
