from datetime import UTC, date, datetime
import pytest
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, JobRun, NewsItem, NewsMention, SecFiling
from argus.pipelines.refresh_filings import refresh_filings
from argus.pipelines.refresh_news import detect_mentions_and_keywords, refresh_news
from argus.sources.gdelt_client import parse_gdelt_date
from argus.sources.sec_client import parse_sec_date, parse_sec_datetime


# Date parser tests
def test_parse_sec_date() -> None:
    assert parse_sec_date("2024-03-20") == date(2024, 3, 20)
    assert parse_sec_date("") is None
    assert parse_sec_date("invalid") is None


def test_parse_sec_datetime() -> None:
    expected = datetime(2024, 3, 20, 16, 15, 0)
    assert parse_sec_datetime("2024-03-20T16:15:00.000Z") == expected
    assert parse_sec_datetime("") is None
    assert parse_sec_datetime("invalid") is None


def test_parse_gdelt_date() -> None:
    expected = datetime(2025, 5, 30, 23, 30, 0)
    assert parse_gdelt_date("20250530T233000Z") == expected
    assert parse_gdelt_date("20250530233000") == expected
    assert parse_gdelt_date("") is not None  # defaults to now


# Mention detection logic tests
def test_detect_mentions_and_keywords() -> None:
    companies = [
        Company(id=1, symbol="NVDA", name="NVIDIA Corporation", is_active=True),
        Company(id=2, symbol="MSFT", name="Microsoft Corp.", is_active=True),
    ]

    # Match in title, infrastructure keyword in summary
    title = "NVDA unveils new chip"
    summary = "The chip is targeting high performance AI and liquid cooling in data centers."
    mentions = detect_mentions_and_keywords(title, summary, companies)

    assert len(mentions) == 1
    m = mentions[0]
    assert m["company_id"] == 1
    assert m["ticker"] == "NVDA"
    assert m["is_primary_match"] is True
    assert "NVDA" in m["matched_keywords"]
    assert "ai" in m["matched_keywords"]
    assert "liquid cooling" in m["matched_keywords"]

    # Match in description only (not primary)
    title = "New AI developments are here"
    summary = "This might impact Microsoft and cloud servers."
    mentions2 = detect_mentions_and_keywords(title, summary, companies)

    assert len(mentions2) == 1
    m2 = mentions2[0]
    assert m2["company_id"] == 2
    assert m2["ticker"] == "MSFT"
    assert m2["is_primary_match"] is False
    assert "MICROSOFT" in m2["matched_keywords"]
    assert "ai" in m2["matched_keywords"]


# Filing refresh pipeline and idempotency test
def test_refresh_filings_pipeline(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_filings as filings_module

    # Mock SEC client to return 1 tracked filing and 1 untracked filing
    def mock_fetch_filings(cik: str | int) -> list[dict]:
        assert str(cik) == "0001045810"
        return [
            {
                "accession_no": "0001045810-24-000057",
                "form": "10-K",
                "filing_date": date(2024, 3, 20),
                "acceptance_datetime": datetime(2024, 3, 20, 16, 15, 0),
                "primary_doc_url": "https://sec.gov/doc.htm",
                "filing_detail_url": "https://sec.gov/detail.htm",
            }
        ]

    # Enable User-Agent
    monkeypatch.setattr("argus.core.settings.settings.sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(filings_module, "fetch_filings", mock_fetch_filings)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", cik="0001045810", is_active=True))

    # Run pipeline first time
    res1 = refresh_filings()
    assert res1["status"] == "success"
    assert res1["rows_read"] == 1
    assert res1["rows_written"] == 1

    with db_module.session_scope() as session:
        filing = session.query(SecFiling).one()
        assert filing.accession_no == "0001045810-24-000057"
        assert filing.is_new is True

        # Manually mark read
        filing.is_new = False
        session.commit()

    # Run pipeline second time (must not mark read filings back to is_new = True)
    res2 = refresh_filings()
    assert res2["status"] == "success"
    assert res2["rows_written"] == 1

    with db_module.session_scope() as session:
        assert session.query(SecFiling).count() == 1
        filing = session.query(SecFiling).one()
        assert filing.is_new is False  # preserved!

        # Check job run
        jobs = session.query(JobRun).order_by(JobRun.id.asc()).all()
        assert len(jobs) == 2
        assert jobs[0].status == "success"
        assert jobs[0].job_name == "refresh_filings"


# News refresh pipeline and idempotency test
def test_refresh_news_pipeline(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    # Mock RSS
    def mock_fetch_rss(query: str) -> list[dict]:
        if "NVDA" in query:
            return [
                {
                    "title": "NVIDIA is winning the AI race",
                    "summary": "Data center chips sales are rising rapidly.",
                    "url": "https://finance.yahoo.com/nvda-ai",
                    "source_name": "Yahoo Finance",
                    "published_at": datetime(2025, 5, 30, 10, 0, 0),
                }
            ]
        return []

    # Mock GDELT
    def mock_fetch_gdelt(ticker: str, timespan: str) -> list[dict]:
        return []

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", mock_fetch_gdelt)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))

    res1 = refresh_news(force=True, queries=["NVDA"])
    assert res1["status"] == "success"
    assert res1["rows_read"] == 1
    assert res1["rows_written"] == 1

    with db_module.session_scope() as session:
        assert session.query(NewsItem).count() == 1
        assert session.query(NewsMention).count() == 1

        mention = session.query(NewsMention).one()
        assert mention.ticker == "NVDA"
        assert mention.is_primary_match is True
        assert "ai" in mention.matched_keywords

    # Rerun to check idempotency (should write 0 new items/mentions)
    res2 = refresh_news(force=True, queries=["NVDA"])
    assert res2["status"] == "success"
    assert res2["rows_written"] == 0

    with db_module.session_scope() as session:
        assert session.query(NewsItem).count() == 1
        assert session.query(NewsMention).count() == 1


# Case-sensitive matching of short tickers test
def test_detect_mentions_and_keywords_case_sensitive_short_tickers() -> None:
    companies = [
        Company(id=1, symbol="SO", name="Southern Company", is_active=True),
        Company(id=2, symbol="IT", name="Gartner Inc", is_active=True),
        Company(id=3, symbol="NVDA", name="NVIDIA Corporation", is_active=True),
    ]

    # Lowercase "so" and "it" should NOT match SO and IT.
    # Uppercase "SO" and "IT" SHOULD match SO and IT.
    # Lowercase "nvda" SHOULD match NVDA because it is length >= 4.
    title = "Why is it so hot today?"
    summary = "We are using nvda chips."
    mentions = detect_mentions_and_keywords(title, summary, companies)
    # Only NVDA should be detected because "it" and "so" are lowercase
    assert len(mentions) == 1
    assert mentions[0]["ticker"] == "NVDA"

    title_upper = "SO and IT are leading the utility sector."
    summary_upper = "No other mention."
    mentions_upper = detect_mentions_and_keywords(title_upper, summary_upper, companies)
    # SO and IT should be detected because they are uppercase
    assert len(mentions_upper) == 2
    tickers = {m["ticker"] for m in mentions_upper}
    assert tickers == {"SO", "IT"}


def test_fetch_rss_news_retries(monkeypatch) -> None:
    from argus.sources.news_rss_client import fetch_rss_news
    import httpx

    call_count = 0

    def mock_get(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # First two calls trigger a 429
            return httpx.Response(status_code=429, request=httpx.Request("GET", url))
        # Third call succeeds
        rss_content = b"""<?xml version="1.0" encoding="UTF-8" ?>
        <rss version="2.0">
        <channel>
            <title>Yahoo Finance RSS</title>
            <item>
                <title>Test Success Article</title>
                <link>https://finance.yahoo.com/test</link>
                <description>A test description.</description>
                <pubDate>Sat, 30 May 2026 10:00:00 -0400</pubDate>
            </item>
        </channel>
        </rss>
        """
        return httpx.Response(status_code=200, content=rss_content, request=httpx.Request("GET", url))

    # Mock time.sleep to run immediately in tests
    import time
    monkeypatch.setattr(time, "sleep", lambda x: None)
    monkeypatch.setattr(httpx, "get", mock_get)

    items = fetch_rss_news("AAPL")
    assert call_count == 3
    assert len(items) == 1
    assert items[0]["title"] == "Test Success Article"
    assert items[0]["url"] == "https://finance.yahoo.com/test"


def test_fetch_gdelt_news_retries(monkeypatch) -> None:
    from argus.sources.gdelt_client import fetch_gdelt_news
    import httpx

    call_count = 0

    def mock_get(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # First two calls trigger a 429 rate limit
            return httpx.Response(status_code=429, request=httpx.Request("GET", url))
        # Third call succeeds
        import json
        dummy_data = {
            "articles": [
                {
                    "title": "Test GDELT Success",
                    "url": "https://gdelt.org/test",
                    "domain": "gdelt.org",
                    "seendate": "20260530T100000Z"
                }
            ]
        }
        return httpx.Response(
            status_code=200,
            content=json.dumps(dummy_data).encode("utf-8"),
            request=httpx.Request("GET", url)
        )

    # Mock time.sleep to run immediately in tests
    import time
    monkeypatch.setattr(time, "sleep", lambda x: None)
    monkeypatch.setattr(httpx, "get", mock_get)

    items = fetch_gdelt_news("AAPL")
    assert call_count == 3
    assert len(items) == 1
    assert items[0]["title"] == "Test GDELT Success"
    assert items[0]["url"] == "https://gdelt.org/test"


# SEC User-Agent requirement test
def test_sec_client_user_agent_required(monkeypatch) -> None:
    from argus.sources.sec_client import fetch_filings
    from argus.core.settings import settings

    # Ensure SEC_USER_AGENT is empty
    monkeypatch.setattr(settings, "sec_user_agent", "")
    
    with pytest.raises(ValueError) as excinfo:
        fetch_filings("0001045810")
    assert "SEC_USER_AGENT is not configured" in str(excinfo.value)


# SEC submissions API response fixture
@pytest.fixture
def sec_submission_payload() -> dict:
    return {
        "cik": "0001045810",
        "name": "NVIDIA CORP",
        "filings": {
            "recent": {
                "accessionNumber": ["0001045810-24-000057", "0001045810-24-000058"],
                "form": ["10-K", "13F-HR"],  # 13F-HR is untracked
                "filingDate": ["2024-03-20", "2024-03-21"],
                "acceptanceDateTime": ["2024-03-20T16:15:00.000Z", "2024-03-21T17:15:00.000Z"],
                "primaryDocument": ["nvda-10k.htm", "nvda-13f.htm"]
            }
        }
    }


# SEC client parsing with mocked response test
def test_fetch_filings_client_parsing(monkeypatch, sec_submission_payload) -> None:
    from argus.sources.sec_client import fetch_filings
    from argus.core.settings import settings
    import httpx

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")

    def mock_get(url, *args, **kwargs):
        assert "0001045810" in url
        return httpx.Response(200, json=sec_submission_payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", mock_get)

    # Fetch and verify parsing
    filings = fetch_filings("0001045810")
    # Only 10-K is tracked
    assert len(filings) == 1
    f = filings[0]
    assert f["accession_no"] == "0001045810-24-000057"
    assert f["form"] == "10-K"
    assert f["filing_date"] == date(2024, 3, 20)
    assert f["acceptance_datetime"] == datetime(2024, 3, 20, 16, 15, 0)
    assert "nvda-10k.htm" in f["primary_doc_url"]


# SEC filing deduplication test
def test_refresh_filings_deduplication(sqlite_engine, monkeypatch, sec_submission_payload) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    import httpx

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    
    def mock_get(url, *args, **kwargs):
        return httpx.Response(200, json=sec_submission_payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", mock_get)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", cik="0001045810", is_active=True))

    # First run
    res1 = refresh_filings()
    assert res1["rows_written"] == 1

    with db_module.session_scope() as session:
        filing = session.query(SecFiling).one()
        assert filing.accession_no == "0001045810-24-000057"
        assert filing.is_new is True
        # Mark as read
        filing.is_new = False
        session.commit()

    # Second run: should not duplicate, and should preserve is_new = False
    res2 = refresh_filings()
    assert res2["rows_written"] == 1

    with db_module.session_scope() as session:
        assert session.query(SecFiling).count() == 1
        filing = session.query(SecFiling).one()
        assert filing.is_new is False


# Missing CIK handling test
def test_refresh_filings_missing_cik(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NO_CIK", name="No CIK Company", is_active=True))

    res = refresh_filings()
    assert res["status"] == "success"
    assert res["rows_read"] == 0
    assert res["rows_written"] == 0


# RSS feed XML payload fixture
@pytest.fixture
def rss_feed_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
    <channel>
        <title>Yahoo Finance RSS</title>
        <item>
            <title>NVIDIA AI Chip Surge</title>
            <link>https://finance.yahoo.com/nvda-surge</link>
            <description>NVIDIA experiences huge demand for AI chips.</description>
            <pubDate>Sat, 30 May 2026 10:00:00 -0400</pubDate>
            <source>Yahoo Finance</source>
        </item>
    </channel>
    </rss>
    """


# RSS news parsing test
def test_fetch_rss_news_parsing(monkeypatch, rss_feed_xml) -> None:
    from argus.sources.news_rss_client import fetch_rss_news
    import httpx

    def mock_get(url, *args, **kwargs):
        return httpx.Response(200, content=rss_feed_xml, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", mock_get)

    items = fetch_rss_news("NVDA")
    assert len(items) == 1
    assert items[0]["title"] == "NVIDIA AI Chip Surge"
    assert items[0]["url"] == "https://finance.yahoo.com/nvda-surge"
    assert items[0]["summary"] == "NVIDIA experiences huge demand for AI chips."
    assert isinstance(items[0]["published_at"], datetime)


# GDELT JSON payload fixture
@pytest.fixture
def gdelt_json_payload() -> dict:
    return {
        "articles": [
            {
                "title": "NVIDIA GPU Advanced Cooling",
                "url": "https://gdelt.org/nvda-cooling",
                "domain": "coolingnews.com",
                "seendate": "20260530T153000Z"
            }
        ]
    }


# GDELT news parsing test
def test_fetch_gdelt_news_parsing(monkeypatch, gdelt_json_payload) -> None:
    from argus.sources.gdelt_client import fetch_gdelt_news
    import httpx
    import json

    def mock_get(url, *args, **kwargs):
        return httpx.Response(200, content=json.dumps(gdelt_json_payload).encode("utf-8"), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", mock_get)

    items = fetch_gdelt_news("NVDA")
    assert len(items) == 1
    assert items[0]["title"] == "NVIDIA GPU Advanced Cooling"
    assert items[0]["url"] == "https://gdelt.org/nvda-cooling"
    assert items[0]["source_name"] == "coolingnews.com"
    assert items[0]["published_at"] == datetime(2026, 5, 30, 15, 30, 0)


# News URL deduplication test
def test_refresh_news_url_deduplication(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    def mock_fetch_rss(query: str) -> list[dict]:
        return [
            {
                "title": "Duplicate Article about NVDA",
                "summary": "This should be deduped.",
                "url": "https://example.com/dup",
                "source_name": "Source A",
                "published_at": datetime(2026, 5, 30, 10, 0, 0),
            }
        ]

    def mock_fetch_gdelt(query: str, timespan: str) -> list[dict]:
        return [
            {
                "title": "Duplicate Article about NVDA (Alternate)",
                "summary": None,
                "url": "https://example.com/dup",
                "source_name": "Source B",
                "published_at": datetime(2026, 5, 30, 10, 0, 0),
            }
        ]

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", mock_fetch_gdelt)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))

    res = refresh_news(force=True, queries=["NVDA"])
    assert res["status"] == "success"
    assert res["rows_read"] == 2
    assert res["rows_written"] == 1

    with db_module.session_scope() as session:
        assert session.query(NewsItem).count() == 1
        assert session.query(NewsMention).count() == 1


# Mention detection precision, keyword extraction, and copyright storage check
def test_detect_mentions_no_copyright_storage_and_precision() -> None:
    companies = [
        Company(id=1, symbol="NVDA", name="NVIDIA Corp", is_active=True),
        Company(id=2, symbol="IT", name="Gartner Inc", is_active=True),
    ]

    # 1. Precision & Case-sensitivity
    text_lower = "Let's check if it works on nvda."
    mentions1 = detect_mentions_and_keywords("Title", text_lower, companies)
    assert len(mentions1) == 1
    assert mentions1[0]["ticker"] == "NVDA"

    # 2. Keyword matching and extraction (AI infra + ticker + company clean name)
    text_kws = "NVIDIA Corp targets GPU packaging in a data center for IT."
    mentions2 = detect_mentions_and_keywords("Title", text_kws, companies)
    assert len(mentions2) == 2
    
    nvda_mention = next(m for m in mentions2 if m["ticker"] == "NVDA")
    it_mention = next(m for m in mentions2 if m["ticker"] == "IT")

    assert "gpu" in nvda_mention["matched_keywords"]
    assert "data center" in nvda_mention["matched_keywords"]
    assert "NVIDIA" in nvda_mention["matched_keywords"]
    assert "IT" in it_mention["matched_keywords"]

    # 3. No full copyrighted article text storage test
    long_description = "A" * 5000
    mock_art = {
        "title": "Title",
        "summary": long_description,
        "url": "https://example.com/long",
        "source_name": "Test",
        "provider": "rss",
        "published_at": datetime.now(),
    }
    
    from argus.pipelines.refresh_news import _upsert_news_item
    class DummySession:
        def __init__(self):
            self.added = []
        def query(self, *args):
            class Query:
                def filter(self, *args):
                    return self
                def one_or_none(self):
                    return None
            return Query()
        def add(self, obj):
            self.added.append(obj)
        def flush(self):
            pass
            
    sess = DummySession()
    _upsert_news_item(sess, mock_art, [{"company_id": 1, "ticker": "NVDA", "is_primary_match": True, "matched_keywords": "ai"}])
    assert len(sess.added) > 0
    saved_news_item = next(x for x in sess.added if isinstance(x, NewsItem))
    assert len(saved_news_item.summary) <= 2000


# Partial failure pipeline and JobRun logs test
def test_refresh_news_partial_failure(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    # Mock RSS to succeed for one broad query but fail for another.
    def mock_fetch_rss(query: str) -> list[dict]:
        if query == "bad query":
            raise RuntimeError("RSS Fetch Error")
        return [
            {
                "title": "NVIDIA AI news",
                "summary": "Success summary",
                "url": "https://example.com/nvda",
                "source_name": "Success Source",
                "published_at": datetime(2026, 5, 30, 10, 0, 0),
            }
        ]

    def mock_fetch_gdelt(query: str, timespan: str) -> list[dict]:
        return []

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", mock_fetch_gdelt)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))
        session.add(Company(symbol="MSFT", name="Microsoft Corp.", is_active=True))

    res = refresh_news(force=True, queries=["good query", "bad query"])
    assert res["status"] == "partial_success"
    assert "bad query" in res["failed_queries"]
    assert "rss" in res["failed_providers"]
    assert res["rows_read"] == 1
    assert res["rows_written"] == 1

    with db_module.session_scope() as session:
        job = session.query(JobRun).order_by(JobRun.id.desc()).first()
        assert job.status == "partial_success"
        assert "bad query" in job.error_text


def test_fetch_rss_news_429_then_failure(monkeypatch) -> None:
    from argus.sources.news_rss_client import NewsProviderRateLimitError, fetch_rss_news_query
    import httpx
    import time

    calls = 0

    def mock_get(url, *args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(
            status_code=429,
            headers={"Retry-After": "1"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    monkeypatch.setattr(httpx, "get", mock_get)

    with pytest.raises(NewsProviderRateLimitError):
        fetch_rss_news_query("data center AI")

    assert calls == 3


def test_refresh_news_normalized_url_deduplication(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    def mock_fetch_rss(query: str) -> list[dict]:
        return [
            {
                "title": "NVIDIA AI data center story",
                "summary": "NVIDIA data center demand.",
                "url": "https://example.com/story?utm_source=x&utm_campaign=y",
                "source_name": "Source A",
                "published_at": datetime(2026, 5, 30, 10, 0, 0),
            }
        ]

    def mock_fetch_gdelt(query: str, timespan: str) -> list[dict]:
        return [
            {
                "title": "NVIDIA AI data center story",
                "summary": None,
                "url": "https://example.com/story",
                "source_name": "Source B",
                "published_at": datetime(2026, 5, 30, 10, 0, 0),
            }
        ]

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", mock_fetch_gdelt)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))

    result = refresh_news(force=True, queries=["data center AI"])

    assert result["status"] == "success"
    assert result["rows_read"] == 2
    assert result["rows_written"] == 1
    with db_module.session_scope() as session:
        item = session.query(NewsItem).one()
        assert item.url == "https://example.com/story"


def test_refresh_news_skips_when_recent_success(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    calls = 0

    def mock_fetch_rss(query: str) -> list[dict]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", lambda query, timespan: [])
    monkeypatch.setattr(news_module.settings, "news_refresh_min_hours", 3.0)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(
            JobRun(
                job_name="refresh_news",
                started_at=datetime(2026, 5, 30, 9, 0, 0),
                finished_at=datetime.now(UTC).replace(tzinfo=None, microsecond=0),
                status="success",
            )
        )

    result = refresh_news(force=False, queries=["data center AI"])

    assert result["status"] == "skipped"
    assert calls == 0
    with db_module.session_scope() as session:
        job = session.query(JobRun).order_by(JobRun.id.desc()).first()
        assert job.status == "skipped"


def test_refresh_news_force_bypasses_refresh_throttle(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    calls = 0

    def mock_fetch_rss(query: str) -> list[dict]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", lambda query, timespan: [])
    monkeypatch.setattr(news_module.settings, "news_refresh_min_hours", 3.0)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(
            JobRun(
                job_name="refresh_news",
                started_at=datetime(2026, 5, 30, 9, 0, 0),
                finished_at=datetime.now(UTC).replace(tzinfo=None, microsecond=0),
                status="success",
            )
        )

    result = refresh_news(force=True, queries=["data center AI"])

    assert result["status"] == "success"
    assert calls == 1
