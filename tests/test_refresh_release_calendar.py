from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import MacroReleaseEvent, MacroSeries


def test_refresh_release_calendar_skips_without_api_key(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    from argus.pipelines.refresh_release_calendar import refresh_release_calendar

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(settings, "fred_api_key", "")

    result = refresh_release_calendar()
    assert result["status"] == "skipped"


def test_refresh_release_calendar_upserts_events(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    from argus.pipelines.refresh_release_calendar import (
        refresh_release_calendar,
    )

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(settings, "fred_api_key", "test-key")

    # Seed required macro series
    with db_module.session_scope() as session:
        session.add(MacroSeries(code="DGS10", name="10Y", source="fred"))
        session.add(MacroSeries(code="CPILFESL", name="Core CPI", source="fred"))

    # Mock the FRED release dates fetch
    def mock_fetch_dates(release_id, *, client=None):
        if release_id == 18:  # H.15
            return [{"date": "2026-07-01"}, {"date": "2026-07-15"}]
        if release_id == 10:  # CPI
            return [{"date": "2026-07-10"}]
        return []

    monkeypatch.setattr(
        "argus.pipelines.refresh_release_calendar.fetch_fred_release_dates",
        mock_fetch_dates,
    )

    result = refresh_release_calendar()
    assert result["status"] == "success"
    assert result["rows_written"] > 0

    with db_module.session_scope() as session:
        events = session.query(MacroReleaseEvent).all()
        assert len(events) > 0
        dgs10_events = [e for e in events if e.series_code == "DGS10"]
        assert len(dgs10_events) == 2


def test_refresh_release_calendar_idempotent(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    from argus.pipelines.refresh_release_calendar import refresh_release_calendar

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(settings, "fred_api_key", "test-key")

    with db_module.session_scope() as session:
        session.add(MacroSeries(code="DGS10", name="10Y", source="fred"))

    def mock_fetch_dates(release_id, *, client=None):
        if release_id == 18:
            return [{"date": "2026-07-01"}]
        return []

    monkeypatch.setattr(
        "argus.pipelines.refresh_release_calendar.fetch_fred_release_dates",
        mock_fetch_dates,
    )

    refresh_release_calendar()
    refresh_release_calendar()  # Run again — should not duplicate

    with db_module.session_scope() as session:
        events = session.query(MacroReleaseEvent).filter_by(series_code="DGS10").all()
        assert len(events) == 1


def test_refresh_release_calendar_handles_fetch_errors(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.settings import settings
    from argus.pipelines.refresh_release_calendar import refresh_release_calendar

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(settings, "fred_api_key", "test-key")

    with db_module.session_scope() as session:
        session.add(MacroSeries(code="DGS10", name="10Y", source="fred"))

    # Mock the FRED release dates fetch to raise an error
    def mock_fetch_dates_fail(release_id, *, client=None):
        raise RuntimeError("FRED API connection error")

    monkeypatch.setattr(
        "argus.pipelines.refresh_release_calendar.fetch_fred_release_dates",
        mock_fetch_dates_fail,
    )

    result = refresh_release_calendar()
    # It should set status to failed since no rows were written
    assert result["status"] == "failed"
