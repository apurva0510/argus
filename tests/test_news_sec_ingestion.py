from datetime import UTC, date, datetime, timedelta
import pytest
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import (
    Company,
    JobRun,
    NewsItem,
    NewsMention,
    ProviderHealth,
    SecFiling,
    UserNote,
)
from argus.pipelines.refresh_filings import refresh_filings
from argus.pipelines.refresh_news import detect_mentions_and_keywords, refresh_news
from argus.sources.gdelt_client import parse_gdelt_date
from argus.sources.sec_client import (
    SecSubmissionNotFoundError,
    SecTickerIdentity,
    parse_sec_date,
    parse_sec_datetime,
)


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
    assert res2["rows_written"] == 0

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


def test_fetch_rss_news_raises_on_first_429(monkeypatch) -> None:
    from argus.sources.news_rss_client import NewsProviderRateLimitError, fetch_rss_news
    import httpx

    call_count = 0

    def mock_get(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(status_code=429, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", mock_get)

    with pytest.raises(NewsProviderRateLimitError):
        fetch_rss_news("AAPL")

    assert call_count == 1


def test_fetch_gdelt_news_raises_on_first_429(monkeypatch) -> None:
    from argus.sources.gdelt_client import fetch_gdelt_news
    from argus.sources.news_rss_client import NewsProviderRateLimitError
    import httpx

    call_count = 0

    def mock_get(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(status_code=429, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", mock_get)

    with pytest.raises(NewsProviderRateLimitError):
        fetch_gdelt_news("AAPL")

    assert call_count == 1


def test_fetch_gdelt_news_timeout_raises_429(monkeypatch) -> None:
    from argus.sources.gdelt_client import fetch_gdelt_news
    from argus.sources.news_rss_client import NewsProviderRateLimitError
    import httpx

    def mock_get(url, *args, **kwargs):
        raise httpx.TimeoutException("Handshake timeout")

    monkeypatch.setattr(httpx, "get", mock_get)

    with pytest.raises(NewsProviderRateLimitError):
        fetch_gdelt_news("AAPL")


def test_fetch_gdelt_news_invalid_json_raises_429(monkeypatch) -> None:
    from argus.sources.gdelt_client import fetch_gdelt_news
    from argus.sources.news_rss_client import NewsProviderRateLimitError
    import httpx

    def mock_get(url, *args, **kwargs):
        # Return 200 but HTML error page instead of JSON
        return httpx.Response(
            status_code=200, content=b"An error occurred", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx, "get", mock_get)

    with pytest.raises(NewsProviderRateLimitError):
        fetch_gdelt_news("AAPL")


def test_fetch_gdelt_news_persistent_http_error_raises_429(monkeypatch) -> None:
    from argus.sources.gdelt_client import fetch_gdelt_news
    from argus.sources.news_rss_client import NewsProviderRateLimitError
    import httpx
    import time

    call_count = 0

    def mock_get(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(status_code=503, request=httpx.Request("GET", url))

    # Disable sleeping to speed up the test
    monkeypatch.setattr(time, "sleep", lambda x: None)
    monkeypatch.setattr(httpx, "get", mock_get)

    with pytest.raises(NewsProviderRateLimitError):
        fetch_gdelt_news("AAPL")

    # Should try 3 times (1 initial + 2 retries) before raising
    assert call_count == 3


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
                "primaryDocument": ["nvda-10k.htm", "nvda-13f.htm"],
            }
        },
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
    assert res2["rows_written"] == 0

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
    assert res["status"] == "partial_success"
    assert res["rows_read"] == 0
    assert res["rows_written"] == 0
    assert res["missing_cik_symbols"] == ["NO_CIK"]


def test_refresh_filings_remaps_stale_cik_after_404(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    import argus.pipelines.refresh_filings as filings_module

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    calls: list[str] = []

    def mock_fetch_filings(cik: str | int) -> list[dict]:
        calls.append(str(cik))
        if str(cik) == "0000000001":
            raise SecSubmissionNotFoundError(str(cik))
        return [
            {
                "accession_no": "0001045810-24-000057",
                "form": "10-K",
                "filing_date": date(2024, 3, 20),
                "acceptance_datetime": datetime(2024, 3, 20, 16, 15),
                "primary_doc_url": "https://sec.gov/doc.htm",
                "filing_detail_url": "https://sec.gov/detail.htm",
            }
        ]

    monkeypatch.setattr(filings_module, "fetch_filings", mock_fetch_filings)
    monkeypatch.setattr(
        filings_module,
        "fetch_ticker_identities",
        lambda: {"NVDA": SecTickerIdentity("NVDA", "0001045810", "NVIDIA CORP", "Nasdaq")},
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", cik="0000000001", is_active=True))

    result = refresh_filings()

    assert result["status"] == "partial_success"
    assert result["remapped_symbols"] == ["NVDA"]
    assert result["failed_symbols"] == []
    assert result["not_found_symbols"] == ["NVDA"]
    assert calls == ["0000000001", "0001045810"]

    with db_module.session_scope() as session:
        company = session.query(Company).filter(Company.symbol == "NVDA").one()
        assert company.cik == "0001045810"
        assert session.query(SecFiling).count() == 1


def test_refresh_filings_reports_unresolved_404(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    import argus.pipelines.refresh_filings as filings_module

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(
        filings_module,
        "fetch_filings",
        lambda cik: (_ for _ in ()).throw(SecSubmissionNotFoundError(str(cik))),
    )
    monkeypatch.setattr(
        filings_module,
        "fetch_ticker_identities",
        lambda: {"NVDA": SecTickerIdentity("NVDA", "0000000001", "NVIDIA CORP", "Nasdaq")},
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA", cik="0000000001", is_active=True))

    result = refresh_filings()

    assert result["status"] == "partial_success"
    assert result["failed_symbols"] == ["NVDA"]
    assert result["not_found_symbols"] == ["NVDA"]
    assert "NVDA" in (result["error_text"] or "")


def test_refresh_filings_all_404s_remain_partial_success(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    import argus.pipelines.refresh_filings as filings_module

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(
        filings_module,
        "fetch_filings",
        lambda cik: (_ for _ in ()).throw(SecSubmissionNotFoundError(str(cik))),
    )
    monkeypatch.setattr(
        filings_module,
        "fetch_ticker_identities",
        lambda: {
            "AAA": SecTickerIdentity("AAA", "0000000001", "AAA", "NYSE"),
            "BBB": SecTickerIdentity("BBB", "0000000002", "BBB", "NYSE"),
        },
    )

    with db_module.session_scope() as session:
        session.add_all(
            [
                Company(symbol="AAA", name="AAA", cik="0000000001", is_active=True),
                Company(symbol="BBB", name="BBB", cik="0000000002", is_active=True),
            ]
        )

    result = refresh_filings()

    assert result["status"] == "partial_success"
    assert result["failed_symbols"] == ["AAA", "BBB"]
    assert result["not_found_symbols"] == ["AAA", "BBB"]

    with db_module.session_scope() as session:
        job = session.query(JobRun).filter(JobRun.job_name == "refresh_filings").one()
        assert job.status == "partial_success"
        assert "AAA" in (job.error_text or "")
        assert "BBB" in (job.error_text or "")


def test_refresh_filings_all_operational_failures_fail_job(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    import argus.pipelines.refresh_filings as filings_module

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(
        filings_module,
        "fetch_filings",
        lambda _cik: (_ for _ in ()).throw(TimeoutError("SEC unavailable")),
    )

    with db_module.session_scope() as session:
        session.add_all(
            [
                Company(symbol="AAA", name="AAA", cik="0000000001"),
                Company(symbol="BBB", name="BBB", cik="0000000002"),
            ]
        )

    result = refresh_filings()

    assert result["status"] == "failed"
    assert result["operational_failed_symbols"] == ["AAA", "BBB"]
    assert result["not_found_symbols"] == []


def test_refresh_filings_outage_is_failed_even_with_missing_cik(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    import argus.pipelines.refresh_filings as filings_module

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(
        filings_module,
        "fetch_filings",
        lambda _cik: (_ for _ in ()).throw(TimeoutError("SEC unavailable")),
    )
    with db_module.session_scope() as session:
        session.add_all(
            [
                Company(symbol="AAA", name="AAA", cik="0000000001"),
                Company(symbol="NO_CIK", name="No CIK"),
            ]
        )

    result = refresh_filings()

    assert result["status"] == "failed"
    assert result["operational_failed_symbols"] == ["AAA"]
    assert result["missing_cik_symbols"] == ["NO_CIK"]


def test_refresh_filings_refuses_conflicting_issuer_remap(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    import argus.pipelines.refresh_filings as filings_module

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(
        filings_module,
        "fetch_filings",
        lambda cik: (_ for _ in ()).throw(SecSubmissionNotFoundError(str(cik))),
    )
    monkeypatch.setattr(
        filings_module,
        "fetch_ticker_identities",
        lambda: {"NVDA": SecTickerIdentity("NVDA", "0001045810", "UNRELATED ENERGY CORP", "NYSE")},
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", cik="0000000001"))

    result = refresh_filings()

    assert result["status"] == "partial_success"
    assert result["identity_conflicts"] == ["NVDA"]
    with db_module.session_scope() as session:
        assert session.query(Company).one().cik == "0000000001"


def test_refresh_filings_does_not_hold_transaction_during_fetch(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    import argus.pipelines.refresh_filings as filings_module

    monkeypatch.setattr(settings, "sec_user_agent", "TestAgent/1.0")
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    calls = 0

    def mock_fetch_filings(_cik):
        nonlocal calls
        calls += 1
        if calls == 2:
            with db_module.session_scope() as session:
                company_id = session.query(Company.id).filter(Company.symbol == "AAA").scalar()
                session.add(UserNote(company_id=company_id, note_text="concurrent write"))
        return []

    monkeypatch.setattr(filings_module, "fetch_filings", mock_fetch_filings)
    with db_module.session_scope() as session:
        session.add_all(
            [
                Company(symbol="AAA", name="AAA", cik="0000000001"),
                Company(symbol="BBB", name="BBB", cik="0000000002"),
            ]
        )

    result = refresh_filings()

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        assert session.query(UserNote).count() == 1


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
                "seendate": "20260530T153000Z",
            }
        ]
    }


# GDELT news parsing test
def test_fetch_gdelt_news_parsing(monkeypatch, gdelt_json_payload) -> None:
    from argus.sources.gdelt_client import fetch_gdelt_news
    import httpx
    import json

    def mock_get(url, *args, **kwargs):
        return httpx.Response(
            200,
            content=json.dumps(gdelt_json_payload).encode("utf-8"),
            request=httpx.Request("GET", url),
        )

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
    _upsert_news_item(
        sess,
        mock_art,
        [{"company_id": 1, "ticker": "NVDA", "is_primary_match": True, "matched_keywords": "ai"}],
    )
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


def test_refresh_news_429_marks_provider_unhealthy_and_skips_remaining_queries(
    sqlite_engine,
    monkeypatch,
) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module
    from argus.sources.news_rss_client import NewsProviderRateLimitError

    rss_calls = 0
    gdelt_calls = 0

    def mock_fetch_rss(query: str) -> list[dict]:
        nonlocal rss_calls
        rss_calls += 1
        raise NewsProviderRateLimitError("rss", query)

    def mock_fetch_gdelt(query: str, timespan: str) -> list[dict]:
        nonlocal gdelt_calls
        gdelt_calls += 1
        return []

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", mock_fetch_gdelt)
    monkeypatch.setattr(news_module.settings, "provider_disable_hours", 24.0)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))

    result = refresh_news(force=True, queries=["first query", "second query"])

    assert result["status"] == "partial_success"
    assert rss_calls == 1
    assert gdelt_calls == 2
    assert "rss" in result["failed_providers"]
    assert "RSS disabled until tomorrow due to rate limit" in result["error_text"]

    with db_module.session_scope() as session:
        health = session.query(ProviderHealth).filter_by(provider="rss").one()
        assert health.status == "unhealthy"
        assert health.failure_count == 1
        assert health.disabled_until is not None
        assert health.last_error == "RSS disabled until tomorrow due to rate limit"


def test_refresh_news_skips_provider_disabled_from_previous_429(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    calls = 0

    def mock_fetch_gdelt(query: str, timespan: str) -> list[dict]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(news_module, "fetch_rss_news", lambda query: [])
    monkeypatch.setattr(news_module, "fetch_gdelt_news", mock_fetch_gdelt)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))
        session.add(
            ProviderHealth(
                provider="gdelt",
                status="unhealthy",
                failure_count=1,
                disabled_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=23),
                last_error="GDELT disabled until tomorrow due to rate limit",
            )
        )

    result = refresh_news(force=False, queries=["data center AI"])

    assert result["status"] == "partial_success"
    assert calls == 0
    assert "gdelt" in result["failed_providers"]
    assert "GDELT disabled until tomorrow due to rate limit" in result["error_text"]


def test_fetch_rss_news_429_does_not_retry(monkeypatch) -> None:
    from argus.sources.news_rss_client import NewsProviderRateLimitError, fetch_rss_news_query
    import httpx

    calls = 0

    def mock_get(url, *args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(
            status_code=429,
            headers={"Retry-After": "1"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", mock_get)

    with pytest.raises(NewsProviderRateLimitError):
        fetch_rss_news_query("data center AI")

    assert calls == 1


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


def test_upsert_news_item_populates_transparent_scores(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        company = Company(symbol="ETN", name="Eaton", is_active=True)
        session.add(company)
        session.flush()
        rows = news_module._upsert_news_item(
            session,
            {
                "title": "Eaton wins data center power contract",
                "summary": "AI infrastructure demand accelerates.",
                "url": "https://example.com/etn-win",
                "source_name": "Example",
                "provider": "rss",
                "published_at": datetime(2026, 3, 10, 12, 0),
            },
            [
                {
                    "company_id": company.id,
                    "ticker": "ETN",
                    "is_primary_match": True,
                    "matched_keywords": "ETN, data center, power grid",
                }
            ],
        )

    assert rows == 1
    with db_module.session_scope() as session:
        item = session.query(NewsItem).one()
        assert item.sentiment_score is not None
        assert item.sentiment_score > 0
        assert item.relevance_score == pytest.approx(0.9)


def test_upsert_news_item_relevance_uses_existing_and_new_mentions(
    sqlite_engine,
    monkeypatch,
) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        primary = Company(symbol="ETN", name="Eaton", is_active=True)
        secondary = Company(symbol="VRT", name="Vertiv", is_active=True)
        session.add_all([primary, secondary])
        session.flush()
        article = {
            "title": "Eaton wins data center power contract",
            "summary": "Vertiv mentioned as a supplier.",
            "url": "https://example.com/stable-relevance",
            "source_name": "Example",
            "provider": "rss",
            "published_at": datetime(2026, 3, 10, 12, 0),
        }
        news_module._upsert_news_item(
            session,
            article,
            [
                {
                    "company_id": primary.id,
                    "ticker": "ETN",
                    "is_primary_match": True,
                    "matched_keywords": "ETN, data center, power grid",
                }
            ],
        )
        news_module._upsert_news_item(
            session,
            article,
            [
                {
                    "company_id": secondary.id,
                    "ticker": "VRT",
                    "is_primary_match": False,
                    "matched_keywords": "VRT",
                }
            ],
        )

    with db_module.session_scope() as session:
        item = session.query(NewsItem).one()
        assert item.relevance_score == pytest.approx(0.9)


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


def test_refresh_news_bypass_recent_success_respects_provider_cooldown(
    sqlite_engine,
    monkeypatch,
) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    rss_calls = 0
    gdelt_calls = 0

    def mock_fetch_rss(query: str) -> list[dict]:
        nonlocal rss_calls
        rss_calls += 1
        return []

    def mock_fetch_gdelt(query: str, timespan: str) -> list[dict]:
        nonlocal gdelt_calls
        gdelt_calls += 1
        return []

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", mock_fetch_gdelt)
    monkeypatch.setattr(news_module.settings, "news_refresh_min_hours", 3.0)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    disabled_until = datetime.now(UTC).replace(tzinfo=None, microsecond=0) + timedelta(hours=2)
    with db_module.session_scope() as session:
        session.add(
            JobRun(
                job_name="refresh_news",
                started_at=datetime(2026, 5, 30, 9, 0, 0),
                finished_at=datetime.now(UTC).replace(tzinfo=None, microsecond=0),
                status="success",
            )
        )
        session.add(
            ProviderHealth(
                provider="rss",
                status="unhealthy",
                failure_count=1,
                disabled_until=disabled_until,
                last_error="RSS disabled until tomorrow due to rate limit",
            )
        )

    result = refresh_news(
        bypass_recent_success=True,
        queries=["data center AI"],
    )

    assert result["status"] == "partial_success"
    assert rss_calls == 0
    assert gdelt_calls == 1
    with db_module.session_scope() as session:
        health = session.query(ProviderHealth).filter_by(provider="rss").one()
        assert health.disabled_until == disabled_until


def test_refresh_news_deduplicates_duplicate_company_ids_defensively(
    sqlite_engine, monkeypatch
) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    # Mock RSS to return articles that match NVDA
    def mock_fetch_rss(query: str) -> list[dict]:
        return [
            {
                "title": "NVIDIA leads the way",
                "summary": "AI servers liquid cooling demand.",
                "url": "https://example.com/nvda-story",
                "source_name": "Yahoo Finance",
                "published_at": datetime(2026, 5, 30, 10, 0, 0),
            }
        ]

    monkeypatch.setattr(news_module, "fetch_rss_news", mock_fetch_rss)
    monkeypatch.setattr(news_module, "fetch_gdelt_news", lambda *a, **k: [])
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    # Seed NVDA once in DB
    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))

    with db_module.session_scope() as session:
        companies = session.query(Company).all()
        # Create duplicate list
        duplicate_companies = companies + companies

        # Verify detect_mentions_and_keywords filters duplicate results
        mentions = detect_mentions_and_keywords(
            "NVIDIA leads the way", "AI servers liquid cooling demand.", duplicate_companies
        )
        assert len(mentions) == 1

        # Verify _upsert_news_item does not fail with UNIQUE constraint even if passed duplicates
        dup_mention_payload = [
            {
                "company_id": companies[0].id,
                "ticker": "NVDA",
                "is_primary_match": True,
                "matched_keywords": "ai",
            },
            {
                "company_id": companies[0].id,
                "ticker": "NVDA",
                "is_primary_match": True,
                "matched_keywords": "ai",
            },
        ]

        # Run upsert
        res_first = news_module._upsert_news_item(
            session,
            {
                "title": "NVIDIA leads the way",
                "summary": "AI servers liquid cooling demand.",
                "url": "https://example.com/nvda-story",
                "source_name": "Yahoo Finance",
                "provider": "rss",
                "published_at": datetime(2026, 5, 30, 10, 0, 0),
            },
            dup_mention_payload,
        )
        assert res_first == 1
        session.flush()

        # Verify NewsMention count is exactly 1 (not 2)
        assert session.query(NewsMention).count() == 1


def test_refresh_ir_feeds_stores_company_ir_news(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_ir_feeds as ir_module

    def mock_fetch_ir_feed(symbol: str, url: str) -> list[dict]:
        assert symbol == "CRWD"
        assert url == "https://example.com/crwd-ir.xml"
        return [
            {
                "title": "CrowdStrike announces platform update",
                "summary": "Investor relations release for cybersecurity customers.",
                "url": "https://example.com/crwd-release",
                "source_name": "CRWD investor relations",
                "provider": "ir_feed",
                "published_at": datetime(2026, 5, 30, 10, 0, 0),
            }
        ]

    monkeypatch.setattr(ir_module, "IR_FEED_URLS", {"CRWD": "https://example.com/crwd-ir.xml"})
    monkeypatch.setattr(ir_module, "fetch_ir_feed", mock_fetch_ir_feed)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="CRWD", name="CrowdStrike Holdings, Inc.", is_active=True))

    result = ir_module.refresh_ir_feeds()

    assert result["status"] == "success"
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    with db_module.session_scope() as session:
        item = session.query(NewsItem).one()
        mention = session.query(NewsMention).one()
        assert item.provider == "ir_feed"
        assert item.source_name == "CRWD investor relations"
        assert mention.ticker == "CRWD"


def test_refresh_ir_feeds_429_marks_provider_unhealthy(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_ir_feeds as ir_module
    from argus.sources.news_rss_client import NewsProviderRateLimitError

    calls = 0

    def mock_fetch_ir_feed(symbol: str, url: str) -> list[dict]:
        nonlocal calls
        calls += 1
        raise NewsProviderRateLimitError("ir_feed", symbol)

    monkeypatch.setattr(ir_module, "IR_FEED_URLS", {"CRWD": "https://example.com/crwd-ir.xml"})
    monkeypatch.setattr(ir_module, "fetch_ir_feed", mock_fetch_ir_feed)
    monkeypatch.setattr(ir_module.settings, "provider_disable_hours", 24.0)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="CRWD", name="CrowdStrike Holdings, Inc.", is_active=True))

    result = ir_module.refresh_ir_feeds()

    assert result["status"] == "partial_success"
    assert calls == 1
    assert "IR feeds disabled until tomorrow due to rate limit" in result["error_text"]
    with db_module.session_scope() as session:
        health = session.query(ProviderHealth).filter_by(provider="ir_feed").one()
        assert health.status == "unhealthy"
        assert health.failure_count == 1
        assert health.disabled_until is not None
        assert health.last_error == "IR feeds disabled until tomorrow due to rate limit"


def test_refresh_news_records_provider_outcomes_success(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    monkeypatch.setattr(news_module, "fetch_rss_news", lambda query: [])
    monkeypatch.setattr(news_module, "fetch_gdelt_news", lambda query, timespan: [])
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))

    result = refresh_news(force=True, queries=["data center AI"])
    assert result["status"] == "success"

    with db_module.session_scope() as session:
        job = session.query(JobRun).order_by(JobRun.id.desc()).first()
        assert job.status == "success"
        assert "provider_outcomes: gdelt=success, rss=success" in job.error_text


def test_refresh_news_records_provider_outcomes_cooldown(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module

    monkeypatch.setattr(news_module, "fetch_rss_news", lambda query: [])
    monkeypatch.setattr(news_module, "fetch_gdelt_news", lambda query, timespan: [])
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", is_active=True))
        session.add(
            ProviderHealth(
                provider="rss",
                status="unhealthy",
                failure_count=1,
                disabled_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
                last_error="RSS disabled until tomorrow due to rate limit",
            )
        )

    result = refresh_news(force=False, queries=["data center AI"])
    assert result["status"] == "partial_success"

    with db_module.session_scope() as session:
        job = session.query(JobRun).order_by(JobRun.id.desc()).first()
        assert "provider_outcomes: gdelt=success, rss=cooldown" in job.error_text


def test_refresh_ir_feeds_records_provider_outcomes_success(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_ir_feeds as ir_module

    monkeypatch.setattr(ir_module, "IR_FEED_URLS", {"CRWD": "https://example.com/crwd-ir.xml"})
    monkeypatch.setattr(ir_module, "fetch_ir_feed", lambda symbol, url: [])
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="CRWD", name="CrowdStrike Holdings, Inc.", is_active=True))

    result = ir_module.refresh_ir_feeds()
    assert result["status"] == "success"

    with db_module.session_scope() as session:
        job = (
            session.query(JobRun)
            .filter(JobRun.job_name == "refresh_ir_feeds")
            .order_by(JobRun.id.desc())
            .first()
        )
        assert job.status == "success"
        assert "provider_outcomes: ir_feed=success" in job.error_text


def test_refresh_news_default_queries_split(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_news as news_module
    from argus.pipelines.refresh_news import refresh_news, NEWS_QUERIES

    rss_calls = []
    gdelt_calls = []

    def mock_fetch_rss(query: str) -> list[dict]:
        rss_calls.append(query)
        return []

    def mock_fetch_gdelt(query: str, timespan: str = "1d") -> list[dict]:
        gdelt_calls.append(query)
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
        session.add(Company(symbol="MSFT", name="Microsoft Corporation", is_active=True))
        session.add(Company(symbol="AAPL", name="Apple Inc.", is_active=False))

    result = refresh_news(force=True, queries=None)

    assert result["status"] == "success"
    # RSS should query active tickers NVDA and MSFT
    assert set(rss_calls) == {"NVDA", "MSFT"}
    # GDELT should query the default NEWS_QUERIES
    assert gdelt_calls == NEWS_QUERIES
