from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import (
    CapexObservation,
    Company,
    EarningsEvent,
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
            session.add(EarningsEvent(company_id=nvda.id, event_date=start + timedelta(days=offset)))

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
