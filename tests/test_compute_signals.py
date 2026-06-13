from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import (
    CapexObservation,
    Company,
    EarningsEvent,
    MacroObservation,
    MacroSeries,
    NewsItem,
    NewsMention,
    PriceBar,
    SignalDaily,
)
from argus.pipelines.compute_signals import compute_signals


def _patch_session(sqlite_engine, monkeypatch):
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    return db_module


def _seed_prices(session: Session, company: Company, start_date: date, prices: list[float]) -> None:
    for offset, price in enumerate(prices):
        session.add(
            PriceBar(
                company_id=company.id,
                date=start_date + timedelta(days=offset),
                adj_close=price,
                close=price,
                provider="yfinance",
                interval="1d",
            )
        )


def _price_path(base: float, count: int) -> list[float]:
    price = base
    prices = []
    for idx in range(count):
        daily_return = 0.002 + ((idx % 7) - 3) * 0.001
        price *= 1.0 + daily_return
        prices.append(price)
    return prices


def test_compute_signals_writes_rich_signal_row(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    start = date(2026, 1, 1)
    prices = _price_path(100.0, 75)

    with db_module.session_scope() as session:
        target = Company(symbol="ETN", name="Eaton", is_active=True)
        nvda = Company(symbol="NVDA", name="NVIDIA", is_active=True)
        hyperscalers = [
            Company(symbol="MSFT", name="Microsoft", is_active=True, is_hyperscaler=True),
            Company(symbol="AMZN", name="Amazon", is_active=True, is_hyperscaler=True),
            Company(symbol="GOOGL", name="Alphabet", is_active=True, is_hyperscaler=True),
            Company(symbol="META", name="Meta", is_active=True, is_hyperscaler=True),
        ]
        session.add_all([target, nvda, *hyperscalers])
        session.flush()

        for company in [target, nvda, *hyperscalers]:
            _seed_prices(session, company, start, prices)

        published_at = datetime(2026, 3, 10, 12, 0)
        news = NewsItem(
            title="Eaton wins data center power contract as demand accelerates",
            summary="AI infrastructure expansion supports growth.",
            url="https://example.com/etn",
            published_at=published_at,
            provider="rss",
            source_name="Example",
            sentiment_score=1.0,
            relevance_score=1.0,
        )
        session.add(news)
        session.flush()
        session.add(
            NewsMention(
                news_id=news.id,
                company_id=target.id,
                ticker="ETN",
                is_primary_match=True,
                matched_keywords="ETN, data center, power grid",
            )
        )

        for offset in (20, 32, 44, 56):
            session.add(
                EarningsEvent(company_id=nvda.id, event_date=start + timedelta(days=offset))
            )

        for company in hyperscalers:
            session.add(
                CapexObservation(
                    company_id=company.id,
                    fiscal_period_end=date(2025, 3, 31),
                    capex_amount=10.0,
                )
            )
            session.add(
                CapexObservation(
                    company_id=company.id,
                    fiscal_period_end=date(2026, 3, 31),
                    capex_amount=12.0,
                )
            )

    result = compute_signals(as_of_date=date(2026, 3, 16))

    assert result["status"] == "success"
    assert result["rows_written"] == 6
    with db_module.session_scope() as session:
        target = session.query(Company).filter_by(symbol="ETN").one()
        signal = session.query(SignalDaily).filter_by(company_id=target.id).one()
        assert signal.date == date(2026, 3, 16)
        assert signal.sentiment_proxy_7d == pytest.approx(1.0)
        assert signal.news_relevance_7d == pytest.approx(0.9)
        assert signal.corr_nvda_60d == pytest.approx(1.0)
        assert signal.corr_hyperscaler_60d == pytest.approx(1.0)
        assert signal.earnings_sensitivity is not None
        assert signal.power_signal is None
        assert signal.capex_signal == pytest.approx(0.2)


def test_compute_signals_keeps_insufficient_values_unavailable(
    sqlite_engine,
    monkeypatch,
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    with db_module.session_scope() as session:
        company = Company(symbol="VRT", name="Vertiv", is_active=True)
        session.add(company)
        session.flush()
        _seed_prices(session, company, date(2026, 1, 1), [100.0, 101.0, 102.0])

    result = compute_signals(as_of_date=date(2026, 1, 3))

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        signal = session.query(SignalDaily).one()
        assert signal.sentiment_proxy_7d is None
        assert signal.news_relevance_7d is None
        assert signal.corr_nvda_60d is None
        assert signal.corr_hyperscaler_60d is None
        assert signal.earnings_sensitivity is None
        assert signal.power_signal is None
        assert signal.capex_signal is None


def test_compute_signals_uses_company_specific_news_relevance(
    sqlite_engine,
    monkeypatch,
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    with db_module.session_scope() as session:
        primary = Company(symbol="ETN", name="Eaton", is_active=True)
        secondary = Company(symbol="VRT", name="Vertiv", is_active=True)
        session.add_all([primary, secondary])
        session.flush()
        _seed_prices(session, primary, date(2026, 1, 1), [100.0, 101.0, 102.0])
        _seed_prices(session, secondary, date(2026, 1, 1), [50.0, 51.0, 52.0])
        news = NewsItem(
            title="Eaton wins data center contract with Vertiv supplier mention",
            summary="AI infrastructure demand accelerates.",
            url="https://example.com/multi-company",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Example",
            sentiment_score=1.0,
            relevance_score=0.9,
        )
        session.add(news)
        session.flush()
        session.add_all(
            [
                NewsMention(
                    news_id=news.id,
                    company_id=primary.id,
                    ticker="ETN",
                    is_primary_match=True,
                    matched_keywords="ETN, data center, power grid",
                ),
                NewsMention(
                    news_id=news.id,
                    company_id=secondary.id,
                    ticker="VRT",
                    is_primary_match=False,
                    matched_keywords="VRT",
                ),
            ]
        )

    result = compute_signals(as_of_date=date(2026, 1, 3))

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        primary = session.query(Company).filter_by(symbol="ETN").one()
        secondary = session.query(Company).filter_by(symbol="VRT").one()
        primary_signal = session.query(SignalDaily).filter_by(company_id=primary.id).one()
        secondary_signal = session.query(SignalDaily).filter_by(company_id=secondary.id).one()
        assert primary_signal.news_relevance_7d > secondary_signal.news_relevance_7d
        assert primary_signal.news_relevance_7d == pytest.approx(0.9)
        assert secondary_signal.news_relevance_7d == pytest.approx(0.45)


def test_compute_signals_treats_no_match_news_as_neutral_in_sentiment(
    sqlite_engine,
    monkeypatch,
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    with db_module.session_scope() as session:
        company = Company(symbol="ETN", name="Eaton", is_active=True)
        session.add(company)
        session.flush()
        _seed_prices(session, company, date(2026, 1, 1), [100.0, 101.0, 102.0])

        positive = NewsItem(
            title="Eaton wins contract",
            url="https://example.com/positive",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Yahoo Finance",
            sentiment_score=1.0,
            relevance_score=0.9,
        )
        neutral = NewsItem(
            title="Eaton hosts investor meeting",
            url="https://example.com/neutral",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Yahoo Finance",
            sentiment_score=None,
            relevance_score=0.9,
        )
        session.add_all([positive, neutral])
        session.flush()
        for item in (positive, neutral):
            session.add(
                NewsMention(
                    news_id=item.id,
                    company_id=company.id,
                    ticker="ETN",
                    is_primary_match=True,
                    matched_keywords="ETN, data center, power grid",
                )
            )

    result = compute_signals(as_of_date=date(2026, 1, 3))

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        signal = session.query(SignalDaily).one()
        assert signal.sentiment_proxy_7d == pytest.approx(0.5)


def test_compute_signals_weights_sentiment_by_source_and_relevance(
    sqlite_engine,
    monkeypatch,
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    with db_module.session_scope() as session:
        company = Company(symbol="ETN", name="Eaton", is_active=True)
        session.add(company)
        session.flush()
        _seed_prices(session, company, date(2026, 1, 1), [100.0, 101.0, 102.0])

        reuters_news = NewsItem(
            title="Eaton wins contract",
            url="https://example.com/reuters",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Reuters",
            sentiment_score=1.0,
            relevance_score=0.9,
        )
        opinion_news = NewsItem(
            title="Eaton faces outage",
            url="https://example.com/opinion",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Motley Fool",
            sentiment_score=-1.0,
            relevance_score=0.9,
        )
        session.add_all([reuters_news, opinion_news])
        session.flush()
        for item in (reuters_news, opinion_news):
            session.add(
                NewsMention(
                    news_id=item.id,
                    company_id=company.id,
                    ticker="ETN",
                    is_primary_match=True,
                    matched_keywords="ETN, data center, power grid",
                )
            )

    result = compute_signals(as_of_date=date(2026, 1, 3))

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        signal = session.query(SignalDaily).one()
        assert signal.sentiment_proxy_7d == pytest.approx(1 / 3)


def test_compute_signals_caps_same_day_syndicated_sentiment_duplicates(
    sqlite_engine,
    monkeypatch,
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    with db_module.session_scope() as session:
        company = Company(symbol="ETN", name="Eaton", is_active=True)
        session.add(company)
        session.flush()
        _seed_prices(session, company, date(2026, 1, 1), [100.0, 101.0, 102.0])

        duplicate_a = NewsItem(
            title="Eaton wins data center contract",
            url="https://example.com/dupe-a",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Yahoo Finance",
            sentiment_score=1.0,
            relevance_score=0.9,
        )
        duplicate_b = NewsItem(
            title="Eaton wins data center contract",
            url="https://example.com/dupe-b",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Yahoo Finance",
            sentiment_score=1.0,
            relevance_score=0.9,
        )
        negative = NewsItem(
            title="Eaton faces outage",
            url="https://example.com/negative",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Yahoo Finance",
            sentiment_score=-1.0,
            relevance_score=0.9,
        )
        session.add_all([duplicate_a, duplicate_b, negative])
        session.flush()
        for item in (duplicate_a, duplicate_b, negative):
            session.add(
                NewsMention(
                    news_id=item.id,
                    company_id=company.id,
                    ticker="ETN",
                    is_primary_match=True,
                    matched_keywords="ETN, data center, power grid",
                )
            )

    result = compute_signals(as_of_date=date(2026, 1, 3))

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        signal = session.query(SignalDaily).one()
        assert signal.sentiment_proxy_7d == pytest.approx(0.0)


def test_compute_signals_preserves_article_relevance_for_neutral_multi_company_news(
    sqlite_engine,
    monkeypatch,
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    with db_module.session_scope() as session:
        primary = Company(symbol="ETN", name="Eaton", is_active=True)
        secondary = Company(symbol="VRT", name="Vertiv", is_active=True)
        session.add_all([primary, secondary])
        session.flush()
        _seed_prices(session, primary, date(2026, 1, 1), [100.0, 101.0, 102.0])
        _seed_prices(session, secondary, date(2026, 1, 1), [50.0, 51.0, 52.0])

        news = NewsItem(
            title="Eaton and Vertiv present at infrastructure conference",
            url="https://example.com/neutral-multi",
            published_at=datetime(2026, 1, 3, 12, 0),
            provider="rss",
            source_name="Yahoo Finance",
            sentiment_score=None,
            relevance_score=0.9,
        )
        session.add(news)
        session.flush()
        session.add_all(
            [
                NewsMention(
                    news_id=news.id,
                    company_id=primary.id,
                    ticker="ETN",
                    is_primary_match=True,
                    matched_keywords="ETN, data center, power grid",
                ),
                NewsMention(
                    news_id=news.id,
                    company_id=secondary.id,
                    ticker="VRT",
                    is_primary_match=False,
                    matched_keywords="VRT",
                ),
            ]
        )

    result = compute_signals(as_of_date=date(2026, 1, 3))

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        news = session.query(NewsItem).one()
        assert news.sentiment_score is None
        assert news.relevance_score == pytest.approx(0.9)


def test_compute_signals_requires_complete_hyperscaler_basket(
    sqlite_engine,
    monkeypatch,
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    start = date(2026, 1, 1)
    prices = _price_path(100.0, 75)
    with db_module.session_scope() as session:
        target = Company(symbol="ETN", name="Eaton", is_active=True)
        msft = Company(symbol="MSFT", name="Microsoft", is_active=True, is_hyperscaler=True)
        session.add_all([target, msft])
        session.flush()
        _seed_prices(session, target, start, prices)
        _seed_prices(session, msft, start, prices)

    result = compute_signals(as_of_date=date(2026, 3, 16))

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        target = session.query(Company).filter_by(symbol="ETN").one()
        signal = session.query(SignalDaily).filter_by(company_id=target.id).one()
        assert signal.corr_hyperscaler_60d is None


def test_compute_signals_requires_comparable_capex_coverage(
    sqlite_engine,
    monkeypatch,
) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    with db_module.session_scope() as session:
        target = Company(symbol="ETN", name="Eaton", is_active=True)
        hyperscalers = [
            Company(symbol="MSFT", name="Microsoft", is_active=True, is_hyperscaler=True),
            Company(symbol="AMZN", name="Amazon", is_active=True, is_hyperscaler=True),
            Company(symbol="GOOGL", name="Alphabet", is_active=True, is_hyperscaler=True),
            Company(symbol="META", name="Meta", is_active=True, is_hyperscaler=True),
        ]
        session.add_all([target, *hyperscalers])
        session.flush()
        _seed_prices(session, target, date(2026, 1, 1), [100.0, 101.0, 102.0])
        for company in hyperscalers:
            session.add(
                CapexObservation(
                    company_id=company.id,
                    fiscal_period_end=date(2025, 3, 31),
                    capex_amount=10.0,
                )
            )
        session.add(
            CapexObservation(
                company_id=hyperscalers[0].id,
                fiscal_period_end=date(2026, 3, 31),
                capex_amount=12.0,
            )
        )

    result = compute_signals(as_of_date=date(2026, 1, 3))

    assert result["status"] == "success"
    with db_module.session_scope() as session:
        signal = session.query(SignalDaily).join(Company).filter(Company.symbol == "ETN").one()
        assert signal.capex_signal is None


def test_compute_signals_with_power_signal(sqlite_engine, monkeypatch) -> None:
    db_module = _patch_session(sqlite_engine, monkeypatch)
    as_of = date(2026, 3, 16)

    with db_module.session_scope() as session:
        target = Company(symbol="ETN", name="Eaton", is_active=True)
        session.add(target)
        session.add(MacroSeries(code="EIA_ELEC_PRICE", name="Electricity Price", source="eia"))
        session.add(MacroSeries(code="EIA_ELEC_DEMAND", name="Electricity Demand", source="eia"))
        session.flush()

        # Seed price data so company has returns
        _seed_prices(session, target, date(2026, 1, 1), _price_path(100.0, 75))

        # Seed EIA observations
        # EIA_ELEC_PRICE (monthly)
        # Latest
        session.add(
            MacroObservation(
                series_code="EIA_ELEC_PRICE",
                observation_date=date(2026, 3, 1),
                value=15.0,  # 15 cents
                provider="eia",
            )
        )
        # Prior year (365 days ago, or closest)
        session.add(
            MacroObservation(
                series_code="EIA_ELEC_PRICE",
                observation_date=date(2025, 3, 1),
                value=10.0,  # 10 cents (YoY = +50%)
                provider="eia",
            )
        )

        # EIA_ELEC_DEMAND (daily)
        # Seed 7 days for latest
        for offset in range(7):
            session.add(
                MacroObservation(
                    series_code="EIA_ELEC_DEMAND",
                    observation_date=date(2026, 3, 16) - timedelta(days=offset),
                    value=4000000.0,  # 4M MWh
                    provider="eia",
                )
            )
        # Seed 7 days for prior year (365 days ago)
        for offset in range(7):
            session.add(
                MacroObservation(
                    series_code="EIA_ELEC_DEMAND",
                    observation_date=date(2025, 3, 16) - timedelta(days=offset),
                    value=2000000.0,  # 2M MWh (YoY = +100%)
                    provider="eia",
                )
            )

    result = compute_signals(as_of_date=as_of)
    assert result["status"] == "success"

    with db_module.session_scope() as session:
        signal = session.query(SignalDaily).join(Company).filter(Company.symbol == "ETN").one()
        # Price YoY = 0.5, Demand YoY = 1.0 -> Power signal = (0.5 + 1.0) / 2.0 = 0.75
        assert signal.power_signal == pytest.approx(0.75)
