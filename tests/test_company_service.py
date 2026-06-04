from datetime import date, datetime
import importlib
import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import (
    Company,
    DailyMetric,
    FundamentalsSnapshot,
    NewsItem,
    NewsMention,
    PriceBar,
    SecFiling,
    Watchlist,
    WatchlistItem,
)
from argus.services.company_service import (
    build_relative_performance_frame,
    get_company_options,
    get_company_by_symbol,
    get_company_metrics,
    get_company_price_history,
    get_company_fundamentals,
    get_company_news,
    get_company_filings,
    get_company_notes,
    add_company_note,
    get_watch_status,
    update_watch_status,
    get_watchlist_notes,
)


def _patch_session(sqlite_engine, monkeypatch):
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    return db_module


def test_get_company_options(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c1 = Company(symbol="AAPL", name="Apple", is_active=True)
    c2 = Company(symbol="MSFT", name="Microsoft", is_active=True)
    c3 = Company(symbol="TSLA", name="Tesla", is_active=False)
    db_session.add_all([c1, c2, c3])
    db_session.commit()

    options = get_company_options()
    assert options == ["AAPL", "MSFT"]


def test_get_company_by_symbol(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c1 = Company(symbol="AAPL", name="Apple", is_active=True, sector="Tech")
    db_session.add(c1)
    db_session.commit()

    res = get_company_by_symbol("AAPL")
    assert res is not None
    assert res["name"] == "Apple"
    assert res["sector"] == "Tech"

    res_missing = get_company_by_symbol("MSFT")
    assert res_missing is None


def test_get_company_metrics(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True)
    db_session.add(c)
    db_session.flush()

    m1 = DailyMetric(company_id=c.id, date=date(2026, 1, 1), return_1d=0.02, rsi_14=50.0)
    m2 = DailyMetric(
        company_id=c.id,
        date=date(2026, 1, 2),
        return_1d=0.03,
        rsi_14=55.0,
        high_52w=225.0,
        low_52w=150.0,
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    metrics = get_company_metrics(c.id)
    assert metrics is not None
    assert metrics["date"] == date(2026, 1, 2)
    assert metrics["return_1d"] == 0.03
    assert metrics["rsi_14"] == 55.0
    assert metrics["high_52w"] == 225.0
    assert metrics["low_52w"] == 150.0

    res_missing = get_company_metrics(9999)
    assert res_missing is None


def test_get_company_price_history(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True)
    db_session.add(c)
    db_session.flush()

    p1 = PriceBar(company_id=c.id, date=date(2026, 1, 1), adj_close=150.0, provider="yfinance", interval="1d")
    p2 = PriceBar(company_id=c.id, date=date(2026, 1, 2), adj_close=152.0, provider="yfinance", interval="1d")
    db_session.add_all([p1, p2])
    db_session.commit()

    df = get_company_price_history(c.id)
    assert len(df) == 2
    assert list(df["adj_close"]) == [150.0, 152.0]


def test_get_company_fundamentals(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True)
    db_session.add(c)
    db_session.flush()

    f1 = FundamentalsSnapshot(company_id=c.id, as_of_date=date(2025, 12, 31), market_cap=1e12, provider="yfinance")
    f2 = FundamentalsSnapshot(company_id=c.id, as_of_date=date(2026, 3, 31), market_cap=1.2e12, provider="yfinance")
    db_session.add_all([f1, f2])
    db_session.commit()

    fun = get_company_fundamentals(c.id)
    assert fun is not None
    assert fun["as_of_date"] == date(2026, 3, 31)
    assert fun["market_cap"] == 1.2e12

    res_missing = get_company_fundamentals(9999)
    assert res_missing is None


def test_get_company_news_and_filings(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True)
    db_session.add(c)
    db_session.flush()

    news_item = NewsItem(title="Apple Big Launch", url="https://apple.com/launch", published_at=datetime(2026, 1, 1, 10, 0))
    db_session.add(news_item)
    db_session.flush()

    mention = NewsMention(news_id=news_item.id, company_id=c.id, ticker="AAPL")
    filing = SecFiling(company_id=c.id, accession_no="123-456", form="10-K", filing_date=date(2026, 1, 1))
    db_session.add_all([mention, filing])
    db_session.commit()

    news = get_company_news(c.id)
    assert len(news) == 1
    assert news[0]["title"] == "Apple Big Launch"

    filings = get_company_filings(c.id)
    assert len(filings) == 1
    assert filings[0]["form"] == "10-K"


def test_user_notes_crud(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True)
    wl = Watchlist(name="Test Watchlist", is_system=True)
    db_session.add_all([c, wl])
    db_session.flush()

    wi = WatchlistItem(watchlist_id=wl.id, company_id=c.id, watch_status="watch", notes="")
    db_session.add(wi)
    db_session.commit()

    # Get empty notes
    assert get_company_notes(c.id) == []

    # Add note
    add_company_note(c.id, "First note for AAPL", created_by="Apurva")

    # Research notes should not overwrite watchlist-specific notes.
    db_session.expire_all()
    item = db_session.query(WatchlistItem).filter(WatchlistItem.id == wi.id).one()
    assert item.notes == ""

    add_company_note(c.id, "Second note for AAPL", created_by="Dad")

    db_session.expire_all()
    item = db_session.query(WatchlistItem).filter(WatchlistItem.id == wi.id).one()
    assert item.notes == ""

    add_company_note(c.id, "   ", created_by="Apurva")  # empty note should be ignored

    notes = get_company_notes(c.id)
    assert len(notes) == 2
    assert notes[0]["note_text"] == "Second note for AAPL"
    assert notes[0]["created_by"] == "Dad"
    assert notes[1]["note_text"] == "First note for AAPL"
    assert notes[1]["created_by"] == "Apurva"


def test_watch_status_get_and_set(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True, sector="Tech")
    wl = Watchlist(name="Tech", is_system=True)
    db_session.add_all([c, wl])
    db_session.commit()

    # Get default status when no WatchlistItem exists
    assert get_watch_status(c.id) == "watch"

    # Update status (should create new WatchlistItem)
    update_watch_status(c.id, "high_priority")
    assert get_watch_status(c.id) == "high_priority"

    db_session.expire_all()
    item = db_session.query(WatchlistItem).filter(WatchlistItem.company_id == c.id).one()
    assert item.watch_status == "high_priority"
    assert item.watchlist_id == wl.id

    # Update status again (should update existing item)
    update_watch_status(c.id, "owned")
    assert get_watch_status(c.id) == "owned"

    db_session.expire_all()
    items = db_session.query(WatchlistItem).filter(WatchlistItem.company_id == c.id).all()
    assert len(items) == 1
    assert items[0].watch_status == "owned"


def test_get_watchlist_notes(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True)
    wl1 = Watchlist(name="System Watchlist", is_system=True)
    wl2 = Watchlist(name="Custom Watchlist 1", is_system=False)
    wl3 = Watchlist(name="Custom Watchlist 2", is_system=False)
    db_session.add_all([c, wl1, wl2, wl3])
    db_session.flush()

    wi1 = WatchlistItem(watchlist_id=wl1.id, company_id=c.id, watch_status="watch", notes="system note")
    wi2 = WatchlistItem(watchlist_id=wl2.id, company_id=c.id, watch_status="watch", notes="  ")
    wi3 = WatchlistItem(watchlist_id=wl3.id, company_id=c.id, watch_status="watch", notes="custom note")
    db_session.add_all([wi1, wi2, wi3])
    db_session.commit()

    notes = get_watchlist_notes(c.id)
    assert len(notes) == 2
    assert notes[0]["watchlist"] == "System Watchlist"
    assert notes[0]["notes"] == "system note"
    assert notes[1]["watchlist"] == "Custom Watchlist 2"
    assert notes[1]["notes"] == "custom note"


def test_get_relative_perf_df() -> None:
    detail_page = importlib.import_module("app.pages.3_Company_Detail")
    get_relative_perf_df = detail_page.get_relative_perf_df

    df_comp = pd.DataFrame({
        "date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
        "adj_close": [100.0, 105.0, 110.0]
    })
    df_qqq = pd.DataFrame({
        "date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
        "adj_close": [200.0, 202.0, 198.0]
    })
    df_nvda = pd.DataFrame({
        "date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
        "adj_close": [50.0, 55.0, 60.0]
    })

    res = get_relative_perf_df(df_comp, df_qqq, df_nvda, date(2026, 1, 1))

    assert len(res) == 3
    assert list(res["comp_ret"]) == pytest.approx([0.0, 5.0, 10.0])
    assert list(res["qqq_ret"]) == pytest.approx([0.0, 1.0, -1.0])
    assert list(res["nvda_ret"]) == pytest.approx([0.0, 10.0, 20.0])


def test_get_relative_perf_df_missing_benchmark() -> None:
    df_comp = pd.DataFrame({
        "date": [date(2026, 1, 1), date(2026, 1, 2)],
        "adj_close": [100.0, 105.0]
    })

    res = build_relative_performance_frame(df_comp, pd.DataFrame(), pd.DataFrame(), date(2026, 1, 1))

    assert len(res) == 2
    assert list(res["comp_ret"]) == pytest.approx([0.0, 5.0])
    assert res["qqq_ret"].isna().all()
    assert res["nvda_ret"].isna().all()


def test_get_relative_perf_df_missing_dates() -> None:
    detail_page = importlib.import_module("app.pages.3_Company_Detail")
    get_relative_perf_df = detail_page.get_relative_perf_df

    df_comp = pd.DataFrame({
        "date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
        "adj_close": [100.0, 105.0, 110.0]
    })
    # QQQ has missing date on 1-2
    df_qqq = pd.DataFrame({
        "date": [date(2026, 1, 1), date(2026, 1, 3)],
        "adj_close": [200.0, 204.0]
    })
    # NVDA starts late (no price on 1-1, starts 1-2)
    df_nvda = pd.DataFrame({
        "date": [date(2026, 1, 2), date(2026, 1, 3)],
        "adj_close": [50.0, 55.0]
    })

    res = get_relative_perf_df(df_comp, df_qqq, df_nvda, date(2026, 1, 1))

    assert len(res) == 3
    # QQQ forward-fills a missing middle date. NVDA starts late and should not
    # be backfilled into 1-1, because that would use future data.
    assert pd.isna(res["nvda_ret"].iloc[0])
    assert list(res["nvda_ret"].iloc[1:]) == pytest.approx([0.0, 10.0])
    # QQQ is 200 on 1-1, ffill makes it 200 on 1-2, 204 on 1-3. Returns: 0.0%, 0.0%, 2.0%
    assert list(res["qqq_ret"]) == pytest.approx([0.0, 0.0, 2.0])


def test_user_notes_does_not_overwrite(sqlite_engine, db_session, monkeypatch) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True)
    db_session.add(c)
    db_session.commit()

    add_company_note(c.id, "Note 1")
    add_company_note(c.id, "Note 2")

    notes = get_company_notes(c.id)
    assert len(notes) == 2
    assert notes[0]["note_text"] == "Note 2"
    assert notes[1]["note_text"] == "Note 1"


def test_add_company_note_does_not_overwrite_watchlist_notes(
    sqlite_engine, db_session, monkeypatch
) -> None:
    _patch_session(sqlite_engine, monkeypatch)
    c = Company(symbol="AAPL", name="Apple", is_active=True)
    wl = Watchlist(name="Watchlist", is_system=True)
    db_session.add_all([c, wl])
    db_session.flush()
    item = WatchlistItem(
        watchlist_id=wl.id,
        company_id=c.id,
        watch_status="watch",
        notes="watchlist note",
    )
    db_session.add(item)
    db_session.commit()

    add_company_note(c.id, "Research note")

    db_session.expire_all()
    item = db_session.query(WatchlistItem).filter(WatchlistItem.id == item.id).one()
    assert item.notes == "watchlist note"
