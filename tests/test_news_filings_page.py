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
