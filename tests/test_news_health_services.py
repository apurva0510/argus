from __future__ import annotations

from datetime import date, datetime
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, NewsItem, NewsMention, JobRun, PriceBar, ProviderHealth
from argus.services.news_filings_service import get_filtered_news

import importlib

admin_health_module = importlib.import_module("app.pages.7_Admin_Data_Health")
_load_health_data = admin_health_module._load_health_data


def test_get_filtered_news_relevance_and_sentiment(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    SessionLocal = sessionmaker(
        bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session
    )
    monkeypatch.setattr(db_module, "SessionLocal", SessionLocal)

    with db_module.session_scope() as session:
        comp = Company(symbol="NVDA", name="Nvidia", is_active=True)
        session.add(comp)
        session.flush()

        n1 = NewsItem(
            title="Nvidia surges on chip demand",
            url="https://example.com/1",
            source_name="TechCrunch",
            provider="rss",
            published_at=datetime(2026, 6, 1, 10, 0),
            sentiment_score=0.4,
            relevance_score=0.9,
            sentiment_explanation='{"method": "keyword_financial_v1"}',
        )
        n2 = NewsItem(
            title="Competitor releases chip",
            url="https://example.com/2",
            source_name="RSS",
            provider="rss",
            published_at=datetime(2026, 6, 1, 11, 0),
            sentiment_score=-0.2,
            relevance_score=0.3,
        )
        n3 = NewsItem(
            title="Nvidia board meeting",
            url="https://example.com/3",
            source_name="TechCrunch",
            provider="rss",
            published_at=datetime(2026, 6, 1, 12, 0),
            sentiment_score=0.0,
            relevance_score=0.7,
        )
        session.add_all([n1, n2, n3])
        session.flush()

        session.add(
            NewsMention(news_id=n1.id, company_id=comp.id, ticker="NVDA", matched_keywords="gpu")
        )
        session.add(
            NewsMention(news_id=n2.id, company_id=comp.id, ticker="NVDA", matched_keywords="gpu")
        )
        session.add(
            NewsMention(news_id=n3.id, company_id=comp.id, ticker="NVDA", matched_keywords="gpu")
        )

    # Test 1: min_relevance filter
    res = get_filtered_news(sqlite_engine, ticker="NVDA", min_relevance=0.5)
    assert len(res) == 2
    assert set(res["title"]) == {"Nvidia surges on chip demand", "Nvidia board meeting"}
    assert "sentiment_explanation" in res.columns
    assert res[res["title"] == "Nvidia surges on chip demand"].iloc[0][
        "sentiment_explanation"
    ] == '{"method": "keyword_financial_v1"}'

    # Test 2: sentiment_band="Positive"
    res = get_filtered_news(sqlite_engine, ticker="NVDA", sentiment_band="Positive")
    assert len(res) == 1
    assert res.iloc[0]["title"] == "Nvidia surges on chip demand"

    # Test 3: sentiment_band="Negative"
    res = get_filtered_news(sqlite_engine, ticker="NVDA", sentiment_band="Negative")
    assert len(res) == 1
    assert res.iloc[0]["title"] == "Competitor releases chip"

    # Test 4: sentiment_band="Neutral"
    res = get_filtered_news(sqlite_engine, ticker="NVDA", sentiment_band="Neutral")
    assert len(res) == 1
    assert res.iloc[0]["title"] == "Nvidia board meeting"


def test_admin_health_diagnostics(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    SessionLocal = sessionmaker(
        bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session
    )
    monkeypatch.setattr(db_module, "SessionLocal", SessionLocal)

    with db_module.session_scope() as session:
        c1 = Company(symbol="AAPL", name="Apple", is_active=True, cik="0000320193")
        c2 = Company(symbol="MSFT", name="Microsoft", is_active=True, cik=None)
        c3 = Company(symbol="GOOG", name="Google", is_active=True, cik="123")
        session.add_all([c1, c2, c3])
        session.flush()

        session.add_all(
            [
                PriceBar(
                    company_id=c1.id,
                    date=date(2026, 6, 3),
                    bar_time=datetime(2026, 6, 3),
                    close=100.0,
                    adj_close=100.0,
                    provider="yfinance",
                    interval="1d",
                ),
                PriceBar(
                    company_id=c1.id,
                    date=date(2026, 6, 4),
                    bar_time=datetime(2026, 6, 4, 20, 0),
                    close=101.0,
                    adj_close=101.0,
                    provider="yfinance",
                    interval="15m",
                ),
            ]
        )

        session.add(
            ProviderHealth(
                provider="rss",
                status="unhealthy",
                disabled_until=datetime(2026, 6, 4, 12, 0),
                failure_count=2,
            )
        )
        session.add(
            JobRun(
                job_name="refresh_news",
                started_at=datetime(2026, 6, 4, 10, 0),
                finished_at=datetime(2026, 6, 4, 10, 10),
                status="failed",
                error_text="timeout",
            )
        )

    monkeypatch.setattr("argus.core.settings.settings.database_url", str(sqlite_engine.url))
    monkeypatch.setattr("app.pages.7_Admin_Data_Health.get_db_engine", lambda: sqlite_engine)

    from argus.services.data_health_service import load_data_health_info
    today = date(2026, 6, 4)
    data = load_data_health_info(sqlite_engine, today)

    # Verify compatibility wrapper also works
    wrapper_data = _load_health_data(today)
    assert len(wrapper_data["cik_integrity"]) == 2

    cik_df = data["cik_integrity"]
    assert len(cik_df) == 2
    assert set(cik_df["symbol"]) == {"MSFT", "GOOG"}

    err_df = data["recent_errors"]
    assert len(err_df) == 1
    assert err_df.iloc[0]["job_name"] == "refresh_news"

    latest_prices = data["latest_prices"]
    assert len(latest_prices) == 1
    assert latest_prices.iloc[0]["interval"] == "1d"
    assert str(latest_prices.iloc[0]["val"]).startswith("2026-06-03")

    ph_df = data["provider_health"]
    assert len(ph_df) == 1
    assert ph_df.iloc[0]["provider"] == "rss"
    assert ph_df.iloc[0]["status"] == "unhealthy"
