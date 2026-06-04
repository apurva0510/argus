from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import Company, JobRun
from argus.pipelines.refresh_ciks import refresh_ciks
from argus.sources.sec_client import SecTickerIdentity, parse_sec_ticker_mapping


def test_parse_sec_ticker_exchange_mapping() -> None:
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [1045810, "NVIDIA CORP", "NVDA", "Nasdaq"],
            [789019, "MICROSOFT CORP", "MSFT", "Nasdaq"],
        ],
    }

    assert parse_sec_ticker_mapping(payload) == {
        "NVDA": "0001045810",
        "MSFT": "0000789019",
    }


def test_parse_sec_legacy_ticker_mapping() -> None:
    payload = {
        "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    }

    assert parse_sec_ticker_mapping(payload) == {
        "NVDA": "0001045810",
        "MSFT": "0000789019",
    }


def test_parse_sec_ticker_exchange_mapping_rejects_empty_data() -> None:
    payload = {"fields": ["cik", "name", "ticker", "exchange"], "data": []}

    try:
        parse_sec_ticker_mapping(payload)
    except ValueError as exc:
        assert "contained no ticker mappings" in str(exc)
    else:
        raise AssertionError("Expected empty SEC ticker mapping to be rejected")


def test_refresh_ciks_updates_matches_and_preserves_unmatched(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_ciks as module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(
        module,
        "fetch_ticker_identities",
        lambda: {
            "NVDA": SecTickerIdentity("NVDA", "0001045810", "NVIDIA CORP", "Nasdaq")
        },
    )

    with db_module.session_scope() as session:
        session.add_all(
            [
                Company(symbol="NVDA", name="NVIDIA", cik="0000000001", is_active=True),
                Company(symbol="NOPE", name="Unmatched", cik="0000000002", is_active=True),
            ]
        )

    result = refresh_ciks()

    assert result["status"] == "success"
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert result["updated_symbols"] == ["NVDA"]
    assert result["missing_symbols"] == ["NOPE"]

    with db_module.session_scope() as session:
        nvda = session.query(Company).filter(Company.symbol == "NVDA").one()
        unmatched = session.query(Company).filter(Company.symbol == "NOPE").one()
        job = session.query(JobRun).filter(JobRun.job_name == "refresh_ciks").one()

        assert nvda.cik == "0001045810"
        assert unmatched.cik == "0000000002"
        assert job.status == "success"
        assert "NOPE" in (job.error_text or "")


def test_refresh_ciks_refuses_conflicting_issuer_identity(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    import argus.pipelines.refresh_ciks as module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    monkeypatch.setattr(
        module,
        "fetch_ticker_identities",
        lambda: {
            "NVDA": SecTickerIdentity("NVDA", "0001045810", "UNRELATED ENERGY CORP", "NYSE")
        },
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="NVDA", name="NVIDIA Corporation", cik="0000000001"))

    result = refresh_ciks()

    assert result["status"] == "partial_success"
    assert result["identity_conflicts"] == ["NVDA"]
    assert result["rows_written"] == 0
    with db_module.session_scope() as session:
        assert session.query(Company).one().cik == "0000000001"
