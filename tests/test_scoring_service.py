from datetime import datetime, timedelta, UTC

import pandas as pd
import pytest

from argus.core.models import (
    Company,
    CompanyThemeExposure,
    Theme,
    NewsItem,
    NewsMention,
    SecFiling,
    EarningsEvent,
)
from argus.services.scoring_service import build_score_inputs, load_scoring_inputs_for_active_companies


def test_load_scoring_inputs(sqlite_engine, db_session) -> None:
    # 1. Create themes and companies
    theme1 = Theme(code="ai_compute", name="AI Compute")
    theme2 = Theme(code="ai_logic", name="AI Logic")
    db_session.add_all([theme1, theme2])
    db_session.flush()

    c1 = Company(symbol="AAPL", name="Apple Inc", is_active=True)
    c2 = Company(symbol="GOOGL", name="Google LLC", is_active=True)
    c3 = Company(symbol="MSFT", name="Microsoft Corp", is_active=False)  # inactive
    db_session.add_all([c1, c2, c3])
    db_session.flush()

    # 2. Add Theme Exposure (c1 has exposure, c2 has multiple exposures, c3 has exposure)
    cte1 = CompanyThemeExposure(company_id=c1.id, theme_id=theme1.id, exposure_score=3.5)
    cte2_1 = CompanyThemeExposure(company_id=c2.id, theme_id=theme1.id, exposure_score=2.0)
    cte2_2 = CompanyThemeExposure(company_id=c2.id, theme_id=theme2.id, exposure_score=4.5)  # max is 4.5
    cte3 = CompanyThemeExposure(company_id=c3.id, theme_id=theme1.id, exposure_score=5.0)
    db_session.add_all([cte1, cte2_1, cte2_2, cte3])

    # 3. Add News Items & Mentions (c1 has 1 recent, 1 old; c2 has none)
    now = datetime.now(UTC).replace(tzinfo=None)
    news_recent = NewsItem(
        title="Apple compute stuff",
        url="http://apple.com/news1",
        published_at=now - timedelta(days=2),
    )
    news_old = NewsItem(
        title="Apple old news",
        url="http://apple.com/news2",
        published_at=now - timedelta(days=10),  # older than 7 days
    )
    db_session.add_all([news_recent, news_old])
    db_session.flush()

    nm1 = NewsMention(company_id=c1.id, news_id=news_recent.id, is_primary_match=True)
    nm2 = NewsMention(company_id=c1.id, news_id=news_old.id, is_primary_match=True)
    db_session.add_all([nm1, nm2])

    # 4. Add SEC Filings (c1 has 1 recent, 1 old; c2 has none)
    filing_recent = SecFiling(
        company_id=c1.id,
        accession_no="0001-recent",
        form="10-Q",
        filing_date=(now - timedelta(days=5)).date(),
        acceptance_datetime=now - timedelta(days=5),
        primary_doc_url="http://sec.gov/1",
        filing_detail_url="http://sec.gov/1d",
    )
    filing_old = SecFiling(
        company_id=c1.id,
        accession_no="0001-old",
        form="10-Q",
        filing_date=(now - timedelta(days=40)).date(),  # older than 30 days
        acceptance_datetime=now - timedelta(days=40),
        primary_doc_url="http://sec.gov/2",
        filing_detail_url="http://sec.gov/2d",
    )
    db_session.add_all([filing_recent, filing_old])

    # 5. Add Earnings Events (c1 has 1 upcoming, 1 past)
    ee_upcoming = EarningsEvent(
        company_id=c1.id,
        event_date=(now + timedelta(days=15)).date(),
        source="yfinance",
    )
    ee_past = EarningsEvent(
        company_id=c1.id,
        event_date=(now - timedelta(days=5)).date(),
        source="yfinance",
    )
    db_session.add_all([ee_upcoming, ee_past])

    db_session.commit()

    # 6. Execute load_scoring_inputs_for_active_companies
    inputs = load_scoring_inputs_for_active_companies(db_session)

    # 7. Assertions
    # Only active companies c1 (AAPL) and c2 (GOOGL) should be returned
    assert c1.id in inputs
    assert c2.id in inputs
    assert c3.id not in inputs

    # AAPL assertions
    aapl_inputs = inputs[c1.id]
    assert aapl_inputs["theme_exposure_score"] == 3.5
    assert aapl_inputs["recent_news_count"] == 1
    assert aapl_inputs["recent_filing_count"] == 1
    assert aapl_inputs["upcoming_earnings_days"] == pytest.approx(15.0)

    # GOOGL assertions
    googl_inputs = inputs[c2.id]
    assert googl_inputs["theme_exposure_score"] == 4.5  # max score of multiple exposures
    assert googl_inputs["recent_news_count"] == 0
    assert googl_inputs["recent_filing_count"] == 0
    assert googl_inputs["upcoming_earnings_days"] is None


def test_build_score_inputs_normalizes_shared_pipeline_and_ui_fields() -> None:
    inputs = build_score_inputs(
        {
            "theme_exposure_score": 4.0,
            "drawdown_52w": -0.2,
            "rsi_14": 35.0,
            "distance_from_200dma": 0.02,
            "relative_return_vs_qqq_3m": 0.04,
            "watch_status": "high_priority",
            "recent_news_count": 2.0,
            "recent_filing_count": 1.0,
            "upcoming_earnings_days": 3.6,
            "return_1w": -0.03,
            "sector": "Power and Grid",
        },
        macro_pressure_level=2,
    )

    assert inputs.recent_news_count == 2
    assert inputs.recent_filing_count == 1
    assert inputs.upcoming_earnings_days == 4
    assert inputs.macro_pressure_level == 2
    assert inputs.sector == "Power and Grid"


def test_build_score_inputs_handles_missing_and_negative_earnings_days() -> None:
    missing_inputs = build_score_inputs(
        {
            "recent_news_count": pd.NA,
            "recent_filing_count": None,
            "upcoming_earnings_days": pd.NA,
        }
    )
    negative_inputs = build_score_inputs({"upcoming_earnings_days": -2.4})

    assert missing_inputs.recent_news_count is None
    assert missing_inputs.recent_filing_count is None
    assert missing_inputs.upcoming_earnings_days is None
    assert negative_inputs.upcoming_earnings_days == 0
