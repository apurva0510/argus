import importlib


news_filings_page = importlib.import_module("app.pages.5_News_Filings")


def test_should_load_filings_excludes_news_only_filters() -> None:
    assert news_filings_page._should_load_filings(
        item_type="All",
        selected_source="All",
        min_relevance=0.0,
        sentiment_band="All",
    )

    assert not news_filings_page._should_load_filings(
        item_type="All",
        selected_source="All",
        min_relevance=0.5,
        sentiment_band="All",
    )

    assert not news_filings_page._should_load_filings(
        item_type="All",
        selected_source="All",
        min_relevance=0.0,
        sentiment_band="Positive",
    )


def test_should_load_filings_allows_explicit_filing_only() -> None:
    assert news_filings_page._should_load_filings(
        item_type="Filing Only",
        selected_source="All",
        min_relevance=0.0,
        sentiment_band="All",
    )

    assert not news_filings_page._should_load_filings(
        item_type="All",
        selected_source="TechCrunch",
        min_relevance=0.0,
        sentiment_band="All",
    )


def test_html_block_removes_optional_blank_lines() -> None:
    rendered = news_filings_page._html_block(
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


def test_news_and_sec_filters_active(monkeypatch) -> None:
    import streamlit as st

    # 1. Test _news_only_filters_active
    # Case 1.1: Filing Only item type -> False
    assert not news_filings_page._news_only_filters_active("Filing Only")

    # Case 1.2: No filters active -> False
    monkeypatch.setattr(st, "session_state", {})
    assert not news_filings_page._news_only_filters_active("All")

    # Case 1.3: Relevance filter active -> True
    monkeypatch.setattr(st, "session_state", {"news_min_relevance_filter": 0.5})
    assert news_filings_page._news_only_filters_active("All")

    # Case 1.4: Sentiment active -> True
    monkeypatch.setattr(st, "session_state", {"news_sentiment_band_filter": "Positive"})
    assert news_filings_page._news_only_filters_active("All")

    # Case 1.5: Source active -> True
    monkeypatch.setattr(st, "session_state", {"news_source_filter": "Bloomberg"})
    assert news_filings_page._news_only_filters_active("All")

    # 2. Test _sec_only_filters_active
    # Case 2.1: News Only item type -> False
    assert not news_filings_page._sec_only_filters_active("News Only")

    # Case 2.2: No form filter active -> False
    monkeypatch.setattr(st, "session_state", {})
    assert not news_filings_page._sec_only_filters_active("All")

    # Case 2.3: Form filter active -> True
    monkeypatch.setattr(st, "session_state", {"news_form_filter": "10-K"})
    assert news_filings_page._sec_only_filters_active("All")
