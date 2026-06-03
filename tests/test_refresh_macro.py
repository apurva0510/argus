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


def test_fetch_fred_series_retries_on_timeout(monkeypatch) -> None:
    import httpx
    from argus.core.settings import settings
    from argus.pipelines.refresh_macro import fetch_fred_series

    original_key = settings.fred_api_key
    settings.fred_api_key = ""

    try:
        attempts = 0

        class MockResponse:
            def __init__(self, text: str):
                self.text = text
            def raise_for_status(self):
                pass

        def mock_get(self, url, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise httpx.ReadTimeout("Timeout")
            return MockResponse("observation_date,DGS10\n2026-01-01,4.10\n")

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        # Monkeypatch time.sleep to avoid waiting in tests
        import time
        monkeypatch.setattr(time, "sleep", lambda x: None)

        df = fetch_fred_series("DGS10")
        assert attempts == 3
        assert len(df) == 1
        assert df.iloc[0]["value"] == 4.10
    finally:
        settings.fred_api_key = original_key


def test_fetch_fred_series_official_api_json(monkeypatch) -> None:
    import httpx
    from argus.core.settings import settings
    from argus.pipelines.refresh_macro import fetch_fred_series

    # Temporarily set the key
    original_key = settings.fred_api_key
    settings.fred_api_key = "test_fred_api_key_123"

    try:
        class MockResponse:
            def __init__(self, json_data: dict):
                self._json_data = json_data
            def raise_for_status(self):
                pass
            def json(self) -> dict:
                return self._json_data

        fetched_url = None
        fetched_params = None

        def mock_get(self, url, params=None, **kwargs):
            nonlocal fetched_url, fetched_params
            fetched_url = url
            fetched_params = params
            return MockResponse({
                "observations": [
                    {"date": "2026-06-01", "value": "4.15"},
                    {"date": "2026-06-02", "value": "."},
                    {"date": "2026-06-03", "value": "4.25"},
                ]
            })

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        df = fetch_fred_series("DGS10")

        assert fetched_url == "https://api.stlouisfed.org/fred/series/observations"
        assert fetched_params is not None
        assert fetched_params["api_key"] == "test_fred_api_key_123"
        assert fetched_params["series_id"] == "DGS10"
        assert fetched_params["file_type"] == "json"

        assert len(df) == 2
        assert df.iloc[0]["observation_date"] == date(2026, 6, 1)
        assert df.iloc[0]["value"] == 4.15
        assert df.iloc[1]["observation_date"] == date(2026, 6, 3)
        assert df.iloc[1]["value"] == 4.25

    finally:
        settings.fred_api_key = original_key


