from datetime import date

import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, DailyMetric, PriceBar, Watchlist, WatchlistItem
from argus.services.watchlist_service import load_watchlist_table, update_watchlist_items


def _seed_watchlist_fixture(db_session) -> int:
    company = Company(symbol="NVDA", name="NVIDIA", sector="AI Capex Benchmarks", is_active=True)
    watchlist = Watchlist(name="AI Capex Benchmarks", is_system=True)
    db_session.add_all([company, watchlist])
    db_session.flush()

    item = WatchlistItem(
        watchlist_id=watchlist.id,
        company_id=company.id,
        watch_status="watch",
        notes="initial note",
    )
    db_session.add(item)
    db_session.add(
        PriceBar(
            company_id=company.id,
            date=date(2026, 1, 2),
            close=100.0,
            adj_close=99.0,
            provider="yfinance",
            interval="1d",
        )
    )
    db_session.add(
        DailyMetric(
            company_id=company.id,
            date=date(2026, 1, 2),
            return_1d=0.01,
            return_1w=0.02,
            return_1m=0.03,
            return_3m=0.04,
            return_ytd=0.05,
            high_52w=120.0,
            drawdown_52w=-0.10,
            ma_50=95.0,
            ma_200=90.0,
            rsi_14=42.0,
        )
    )
    db_session.commit()
    return item.id


def test_load_watchlist_table_includes_metrics(sqlite_engine, db_session) -> None:
    _seed_watchlist_fixture(db_session)
    df = load_watchlist_table(sqlite_engine)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ticker"] == "NVDA"
    assert row["theme"] == "AI Capex Benchmarks"
    assert row["watch_status"] == "watch"
    assert row["price"] == 99.0
    assert row["return_1m"] == 0.03


def test_load_watchlist_table_filters(sqlite_engine, db_session) -> None:
    _seed_watchlist_fixture(db_session)
    df_theme = load_watchlist_table(sqlite_engine, theme="AI Capex Benchmarks")
    assert len(df_theme) == 1
    df_ticker = load_watchlist_table(sqlite_engine, ticker_query="NV")
    assert len(df_ticker) == 1
    df_status = load_watchlist_table(sqlite_engine, watch_statuses=["owned"])
    assert df_status.empty


def test_load_watchlist_table_includes_custom_watchlists(sqlite_engine, db_session) -> None:
    company = Company(symbol="ETN", name="Eaton", is_active=True)
    custom_watchlist = Watchlist(name="Dad Picks", is_system=False)
    db_session.add_all([company, custom_watchlist])
    db_session.flush()
    db_session.add(
        WatchlistItem(
            watchlist_id=custom_watchlist.id,
            company_id=company.id,
            watch_status="high_priority",
            notes="custom note",
        )
    )
    db_session.commit()

    df = load_watchlist_table(sqlite_engine)

    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "ETN"
    assert df.iloc[0]["theme"] == "Dad Picks"
    assert df.iloc[0]["notes"] == "custom note"


def test_update_watchlist_items_persists_changes(sqlite_engine, db_session, monkeypatch) -> None:
    from argus.core import db as db_module

    item_id = _seed_watchlist_fixture(db_session)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": item_id, "watch_status": "owned", "notes": "updated note"}]
    )
    assert errors == []
    assert updated_count == 1

    row = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()
    assert row.watch_status == "owned"
    assert row.notes == "updated note"


def test_update_watchlist_items_preserves_note_whitespace(sqlite_engine, db_session, monkeypatch) -> None:
    from argus.core import db as db_module

    item_id = _seed_watchlist_fixture(db_session)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": item_id, "watch_status": "watch", "notes": "  keep spacing  "}]
    )

    assert errors == []
    assert updated_count == 1
    row = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()
    assert row.notes == "  keep spacing  "


@pytest.mark.parametrize("note_value", [None, pd.NA, float("nan")])
def test_update_watchlist_items_handles_null_notes(note_value, sqlite_engine, db_session, monkeypatch) -> None:
    from argus.core import db as db_module

    item_id = _seed_watchlist_fixture(db_session)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": item_id, "watch_status": "watch", "notes": note_value}]
    )

    assert errors == []
    assert updated_count == 1
    row = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()
    assert row.notes == ""


def test_update_watchlist_items_rejects_invalid_status(sqlite_engine, db_session, monkeypatch) -> None:
    from argus.core import db as db_module

    item_id = _seed_watchlist_fixture(db_session)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": item_id, "watch_status": "not_valid", "notes": "updated note"}]
    )
    assert updated_count == 0
    assert errors


def test_update_watchlist_items_does_not_partially_save_invalid_batch(sqlite_engine, db_session, monkeypatch) -> None:
    from argus.core import db as db_module

    item_id = _seed_watchlist_fixture(db_session)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    updated_count, errors = update_watchlist_items(
        [
            {"watchlist_item_id": item_id, "watch_status": "owned", "notes": "updated note"},
            {"watchlist_item_id": item_id + 1, "watch_status": "not_valid", "notes": "bad note"},
        ]
    )

    assert updated_count == 0
    assert errors
    row = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()
    assert row.watch_status == "watch"
    assert row.notes == "initial note"


def test_watchlist_status_check_constraint_rejects_invalid_values(db_session) -> None:
    company = Company(symbol="BAD", name="Bad Status Co")
    watchlist = Watchlist(name="Bad Status Watchlist")
    db_session.add_all([company, watchlist])
    db_session.flush()
    db_session.add(
        WatchlistItem(
            watchlist_id=watchlist.id,
            company_id=company.id,
            watch_status="not_valid",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
