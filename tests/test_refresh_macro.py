from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import JobRun, MacroObservation, MacroSeries
from argus.pipelines.refresh_macro import parse_fred_csv, refresh_macro


def test_parse_fred_csv_drops_missing_values() -> None:
    csv_text = "observation_date,DGS10\n2026-01-01,4.10\n2026-01-02,.\n2026-01-03,4.20\n"

    parsed = parse_fred_csv("DGS10", csv_text)

    assert parsed["observation_date"].tolist() == [date(2026, 1, 1), date(2026, 1, 3)]
    assert parsed["value"].tolist() == [4.10, 4.20]


def test_refresh_macro_success_and_idempotency(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    def fake_fetch(series_code: str, **_kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"observation_date": date(2026, 1, 1), "value": 4.10},
                {"observation_date": date(2026, 1, 2), "value": 4.20},
            ]
        )

    monkeypatch.setattr("argus.pipelines.refresh_macro.fetch_fred_series", fake_fetch)

    first = refresh_macro(series_codes=["DGS10"])
    second = refresh_macro(series_codes=["DGS10"])

    assert first["status"] == "success"
    assert first["rows_read"] == 2
    assert first["rows_written"] == 2
    assert second["status"] == "success"
    assert second["rows_written"] == 2

    with db_module.session_scope() as session:
        assert session.query(MacroSeries).filter(MacroSeries.code == "DGS10").count() == 1
        observations = session.query(MacroObservation).all()
        assert len(observations) == 2
        assert session.query(JobRun).filter(JobRun.job_name == "refresh_macro").count() == 2


def test_refresh_macro_records_partial_failure(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    def fake_fetch(series_code: str, **_kwargs) -> pd.DataFrame:
        if series_code == "DGS30":
            raise RuntimeError("FRED unavailable")
        return pd.DataFrame([{"observation_date": date(2026, 1, 1), "value": 4.10}])

    monkeypatch.setattr("argus.pipelines.refresh_macro.fetch_fred_series", fake_fetch)

    result = refresh_macro(series_codes=["DGS10", "DGS30"])

    assert result["status"] == "partial_success"
    assert result["failed_series"] == ["DGS30"]
    with db_module.session_scope() as session:
        job = session.query(JobRun).filter(JobRun.job_name == "refresh_macro").one()
        assert job.status == "partial_success"
        assert "DGS30" in (job.error_text or "")


def test_parse_fred_csv_requires_series_column() -> None:
    with pytest.raises(ValueError, match="missing expected series"):
        parse_fred_csv("DGS10", "observation_date,OTHER\n2026-01-01,4.1\n")
