from datetime import date
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, DailyMetric, PriceBar, Watchlist, WatchlistItem
from argus.services.watchlist_service import (
    load_watchlist_table,
    normalize_note_value,
    update_watchlist_items,
)


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


def _patch_session(sqlite_engine, monkeypatch):
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    return db_module


def _seed_multi_watchlist_fixture(db_session) -> dict[str, Any]:
    watchlist_a = Watchlist(name="Theme A", is_system=True)
    watchlist_b = Watchlist(name="Theme B", is_system=False)
    nvda = Company(symbol="NVDA", name="NVIDIA", is_active=True)
    amd = Company(symbol="AMD", name="Advanced Micro Devices", is_active=True)
    etn = Company(symbol="ETN", name="Eaton", is_active=True)
    db_session.add_all([watchlist_a, watchlist_b, nvda, amd, etn])
    db_session.flush()

    item_nvda = WatchlistItem(
        watchlist_id=watchlist_a.id,
        company_id=nvda.id,
        watch_status="watch",
        sort_order=1,
        notes="nvda note",
    )
    item_amd = WatchlistItem(
        watchlist_id=watchlist_a.id,
        company_id=amd.id,
        watch_status="owned",
        sort_order=2,
        notes="",
    )
    item_etn = WatchlistItem(
        watchlist_id=watchlist_b.id,
        company_id=etn.id,
        watch_status="high_priority",
        sort_order=10,
        notes="etn note",
    )
    db_session.add_all([item_nvda, item_amd, item_etn])
    db_session.add(
        PriceBar(
            company_id=nvda.id,
            date=date(2026, 1, 2),
            close=100.0,
            adj_close=99.0,
            provider="yfinance",
            interval="1d",
        )
    )
    db_session.add(
        DailyMetric(
            company_id=nvda.id,
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
    return {
        "item_nvda_id": item_nvda.id,
        "item_amd_id": item_amd.id,
        "item_etn_id": item_etn.id,
        "nvda_company_id": nvda.id,
        "amd_company_id": amd.id,
        "watchlist_a_id": watchlist_a.id,
        "watchlist_b_id": watchlist_b.id,
    }


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


def test_load_watchlist_table_returns_all_items_ordered_by_theme_and_ticker(
    sqlite_engine, db_session
) -> None:
    _seed_multi_watchlist_fixture(db_session)
    df = load_watchlist_table(sqlite_engine)

    assert len(df) == 3
    assert list(df["ticker"]) == ["AMD", "NVDA", "ETN"]
    assert list(df["theme"]) == ["Theme A", "Theme A", "Theme B"]


def test_load_watchlist_table_filters_by_theme(sqlite_engine, db_session) -> None:
    _seed_multi_watchlist_fixture(db_session)

    df = load_watchlist_table(sqlite_engine, theme="Theme B")

    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "ETN"


def test_load_watchlist_table_filters_by_ticker_case_insensitive(sqlite_engine, db_session) -> None:
    _seed_multi_watchlist_fixture(db_session)

    df = load_watchlist_table(sqlite_engine, ticker_query="  nv  ")

    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "NVDA"


def test_load_watchlist_table_ticker_filter_supports_partial_match(sqlite_engine, db_session) -> None:
    _seed_multi_watchlist_fixture(db_session)

    df = load_watchlist_table(sqlite_engine, ticker_query="AM")

    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "AMD"


def test_load_watchlist_table_filters_by_watch_status(sqlite_engine, db_session) -> None:
    _seed_multi_watchlist_fixture(db_session)

    df = load_watchlist_table(sqlite_engine, watch_statuses=["watch", "owned"])

    assert len(df) == 2
    assert set(df["ticker"]) == {"NVDA", "AMD"}
    assert set(df["watch_status"]) == {"watch", "owned"}


def test_load_watchlist_table_handles_missing_metrics(sqlite_engine, db_session) -> None:
    _seed_multi_watchlist_fixture(db_session)
    df = load_watchlist_table(sqlite_engine)

    nvda = df[df["ticker"] == "NVDA"].iloc[0]
    amd = df[df["ticker"] == "AMD"].iloc[0]

    assert nvda["price"] == 99.0
    assert nvda["return_1m"] == 0.03
    assert pd.isna(amd["price"])
    assert pd.isna(amd["return_1m"])
    assert pd.isna(amd["rsi_14"])


def test_update_watchlist_items_empty_edits_returns_zero(sqlite_engine, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    assert update_watchlist_items([]) == (0, [])


def test_update_watchlist_items_persists_status_only_change(
    sqlite_engine, db_session, monkeypatch
) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    item_id = _seed_watchlist_fixture(db_session)

    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": item_id, "watch_status": "high_priority", "notes": "initial note"}]
    )

    assert errors == []
    assert updated_count == 1
    row = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()
    assert row.watch_status == "high_priority"
    assert row.notes == "initial note"


def test_update_watchlist_items_persists_notes_only_change(
    sqlite_engine, db_session, monkeypatch
) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    item_id = _seed_watchlist_fixture(db_session)

    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": item_id, "watch_status": "watch", "notes": "notes only change"}]
    )

    assert errors == []
    assert updated_count == 1
    row = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()
    assert row.watch_status == "watch"
    assert row.notes == "notes only change"


def test_update_watchlist_items_skips_unchanged_rows(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    item_id = _seed_watchlist_fixture(db_session)

    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": item_id, "watch_status": "watch", "notes": "initial note"}]
    )

    assert errors == []
    assert updated_count == 0


def test_update_watchlist_items_does_not_overwrite_unrelated_fields(
    sqlite_engine, db_session, monkeypatch
) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    seeded = _seed_multi_watchlist_fixture(db_session)
    item_id = seeded["item_nvda_id"]
    before = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()

    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": item_id, "watch_status": "owned", "notes": "updated nvda note"}]
    )

    assert errors == []
    assert updated_count == 1
    after = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()
    assert after.watchlist_id == before.watchlist_id
    assert after.company_id == before.company_id
    assert after.sort_order == before.sort_order


def test_update_watchlist_items_rejects_duplicate_item_ids_in_batch(
    sqlite_engine, db_session, monkeypatch
) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    item_id = _seed_watchlist_fixture(db_session)

    updated_count, errors = update_watchlist_items(
        [
            {"watchlist_item_id": item_id, "watch_status": "owned", "notes": "first"},
            {"watchlist_item_id": item_id, "watch_status": "watch", "notes": "second"},
        ]
    )

    assert updated_count == 0
    assert any("Duplicate edit" in error for error in errors)
    row = db_session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one()
    assert row.watch_status == "watch"
    assert row.notes == "initial note"


def test_update_watchlist_items_rejects_missing_item_id(sqlite_engine, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)

    updated_count, errors = update_watchlist_items([{"watch_status": "watch", "notes": ""}])

    assert updated_count == 0
    assert "Invalid watchlist item id" in errors


def test_update_watchlist_items_rejects_unknown_item_id(
    sqlite_engine, db_session, monkeypatch
) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    _seed_watchlist_fixture(db_session)

    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": 99999, "watch_status": "watch", "notes": ""}]
    )

    assert updated_count == 0
    assert any("99999" in error for error in errors)


def test_watchlist_items_unique_constraint_prevents_duplicates(db_session) -> None:
    company = Company(symbol="DUP", name="Duplicate Co")
    watchlist = Watchlist(name="Duplicate Watchlist")
    db_session.add_all([company, watchlist])
    db_session.flush()
    db_session.add(
        WatchlistItem(
            watchlist_id=watchlist.id,
            company_id=company.id,
            watch_status="watch",
        )
    )
    db_session.commit()

    db_session.add(
        WatchlistItem(
            watchlist_id=watchlist.id,
            company_id=company.id,
            watch_status="owned",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (pd.NA, ""),
        (float("nan"), ""),
        ("hello", "hello"),
        (42, "42"),
    ],
)
def test_normalize_note_value(value, expected) -> None:
    assert normalize_note_value(value) == expected


def test_update_watchlist_items_syncs_status_globally(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    
    # Create a company and two watchlists
    company = Company(symbol="NVDA", name="NVIDIA", is_active=True)
    wl1 = Watchlist(name="System Watchlist", is_system=True)
    wl2 = Watchlist(name="Custom Watchlist", is_system=False)
    db_session.add_all([company, wl1, wl2])
    db_session.flush()

    wi1 = WatchlistItem(watchlist_id=wl1.id, company_id=company.id, watch_status="watch", notes="system note")
    wi2 = WatchlistItem(watchlist_id=wl2.id, company_id=company.id, watch_status="watch", notes="custom note")
    db_session.add_all([wi1, wi2])
    db_session.commit()

    # Update only wi1 to 'owned'
    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": wi1.id, "watch_status": "owned", "notes": "system note"}]
    )
    assert errors == []
    assert updated_count == 1

    # Verify both watchlist items are now 'owned'
    db_session.expire_all()
    item1 = db_session.query(WatchlistItem).filter(WatchlistItem.id == wi1.id).one()
    item2 = db_session.query(WatchlistItem).filter(WatchlistItem.id == wi2.id).one()
    assert item1.watch_status == "owned"
    assert item2.watch_status == "owned"

    # Verify notes remain separate
    assert item1.notes == "system note"
    assert item2.notes == "custom note"


def test_update_watchlist_items_does_not_sync_notes_globally(
    sqlite_engine, db_session, monkeypatch
) -> None:
    _patch_session(sqlite_engine, monkeypatch)

    company = Company(symbol="NVDA", name="NVIDIA", is_active=True)
    wl1 = Watchlist(name="System Watchlist", is_system=True)
    wl2 = Watchlist(name="Custom Watchlist", is_system=False)
    db_session.add_all([company, wl1, wl2])
    db_session.flush()

    wi1 = WatchlistItem(
        watchlist_id=wl1.id,
        company_id=company.id,
        watch_status="watch",
        notes="system note",
    )
    wi2 = WatchlistItem(
        watchlist_id=wl2.id,
        company_id=company.id,
        watch_status="watch",
        notes="custom note",
    )
    db_session.add_all([wi1, wi2])
    db_session.commit()

    updated_count, errors = update_watchlist_items(
        [{"watchlist_item_id": wi1.id, "watch_status": "watch", "notes": "updated system note"}]
    )

    assert errors == []
    assert updated_count == 1
    db_session.expire_all()
    item1 = db_session.query(WatchlistItem).filter(WatchlistItem.id == wi1.id).one()
    item2 = db_session.query(WatchlistItem).filter(WatchlistItem.id == wi2.id).one()
    assert item1.notes == "updated system note"
    assert item2.notes == "custom note"
