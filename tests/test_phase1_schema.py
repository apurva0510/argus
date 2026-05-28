from datetime import date

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from argus.core.db import Base, create_database_engine
from argus.core import models  # noqa: F401
from argus.core.models import (
    Alert,
    AlertEvent,
    Company,
    DailyMetric,
    PriceBar,
    Watchlist,
    WatchlistItem,
)


def test_phase1_required_tables_create() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    table_names = set(inspect(engine).get_table_names())
    required_tables = {
        "companies",
        "themes",
        "company_theme_exposure",
        "watchlists",
        "watchlist_items",
        "price_bars",
        "daily_metrics",
        "fundamentals_snapshot",
        "news_items",
        "news_mentions",
        "sec_filings",
        "earnings_events",
        "alerts",
        "alert_events",
        "user_notes",
        "job_runs",
        "app_settings",
    }
    assert required_tables.issubset(table_names)


def test_phase1_unique_constraints_exist() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)

    expected_constraints = {
        "company_theme_exposure": {"uq_company_theme_exposure"},
        "watchlist_items": {"uq_watchlist_items"},
        "price_bars": {"uq_price_bars"},
        "daily_metrics": {"uq_daily_metrics"},
        "fundamentals_snapshot": {"uq_fundamentals_snapshot"},
        "news_mentions": {"uq_news_mentions"},
        "earnings_events": {"uq_earnings_events"},
        "alert_events": {"uq_alert_events_dedupe_key"},
    }

    for table_name, expected_names in expected_constraints.items():
        constraint_names = {
            constraint["name"] for constraint in inspector.get_unique_constraints(table_name)
        }
        assert expected_names.issubset(constraint_names)


def test_sqlite_foreign_keys_are_enforced() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        session.add(
            PriceBar(
                company_id=999,
                date=date(2026, 1, 1),
                close=100.0,
                adj_close=100.0,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_watchlist_items_are_unique_per_watchlist_and_company() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        company = Company(symbol="TST", name="Test Co")
        watchlist = Watchlist(name="Test Watchlist")
        session.add_all([company, watchlist])
        session.flush()
        session.add_all(
            [
                WatchlistItem(watchlist_id=watchlist.id, company_id=company.id),
                WatchlistItem(watchlist_id=watchlist.id, company_id=company.id),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_daily_metrics_are_unique_per_company_and_date() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        company = Company(symbol="TST", name="Test Co")
        session.add(company)
        session.flush()
        metric_date = date(2026, 1, 1)
        session.add_all(
            [
                DailyMetric(company_id=company.id, date=metric_date, return_1d=0.01),
                DailyMetric(company_id=company.id, date=metric_date, return_1d=0.02),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_alert_events_require_unique_dedupe_keys() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        alert = Alert(name="Test alert", rule_type="price_below")
        session.add(alert)
        session.flush()
        session.add(AlertEvent(alert_id=alert.id, event_type="price_below"))

        with pytest.raises(IntegrityError):
            session.commit()

    with Session(engine) as session:
        alert = Alert(name="Second alert", rule_type="price_below")
        session.add(alert)
        session.flush()
        session.add_all(
            [
                AlertEvent(alert_id=alert.id, event_type="price_below", dedupe_key="same-key"),
                AlertEvent(alert_id=alert.id, event_type="price_below", dedupe_key="same-key"),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()
