from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import CapexObservation, Company
from argus.sources.sec_client import parse_capex_facts


SAMPLE_COMPANY_FACTS = {
    "facts": {
        "us-gaap": {
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {
                    "USD": [
                        {
                            "form": "10-Q",
                            "fp": "Q1",
                            "end": "2025-03-31",
                            "val": 8500000000,
                            "accn": "0001234567-25-000001",
                        },
                        {
                            "form": "10-Q",
                            "fp": "Q2",
                            "end": "2025-06-30",
                            "val": 9200000000,
                            "accn": "0001234567-25-000002",
                        },
                        {
                            "form": "10-Q",
                            "fp": "Q3",
                            "end": "2025-09-30",
                            "val": -10000000000,
                            "accn": "0001234567-25-000003",
                        },
                        {
                            "form": "10-K",
                            "fp": "FY",
                            "end": "2025-12-31",
                            "val": 38000000000,
                            "accn": "0001234567-26-000001",
                        },
                    ]
                }
            }
        }
    }
}

FALLBACK_FACTS = {
    "facts": {
        "us-gaap": {
            "PropertyPlantAndEquipmentAdditions": {
                "units": {
                    "USD": [
                        {
                            "form": "10-Q",
                            "fp": "Q1",
                            "end": "2025-03-31",
                            "val": 5000000000,
                            "accn": "0009876543-25-000001",
                        },
                    ]
                }
            }
        }
    }
}


def test_parse_capex_facts_extracts_quarterly_and_annual() -> None:
    results = parse_capex_facts(SAMPLE_COMPANY_FACTS)
    assert len(results) == 4
    assert results[0]["fiscal_period_end"] == date(2025, 3, 31)
    assert results[0]["capex_amount"] == 8500000000.0
    assert results[0]["form"] == "10-Q"
    # Negative values should be converted to positive (absolute)
    assert results[2]["capex_amount"] == 10000000000.0
    # Annual value
    assert results[3]["form"] == "10-K"
    assert results[3]["capex_amount"] == 38000000000.0


def test_parse_capex_facts_uses_fallback_concept() -> None:
    results = parse_capex_facts(FALLBACK_FACTS)
    assert len(results) == 1
    assert results[0]["capex_amount"] == 5000000000.0


def test_parse_capex_facts_empty_input() -> None:
    assert parse_capex_facts({}) == []
    assert parse_capex_facts({"facts": {}}) == []
    assert parse_capex_facts({"facts": {"us-gaap": {}}}) == []


def test_parse_capex_facts_deduplicates_by_period() -> None:
    facts = {
        "facts": {
            "us-gaap": {
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-Q",
                                "fp": "Q1",
                                "end": "2025-03-31",
                                "val": 100,
                                "accn": "a",
                            },
                            {
                                "form": "10-Q",
                                "fp": "Q1",
                                "end": "2025-03-31",
                                "val": 200,
                                "accn": "b",
                            },
                        ]
                    }
                }
            }
        }
    }
    results = parse_capex_facts(facts)
    assert len(results) == 1


def test_refresh_capex_preserves_manual_observations(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.pipelines.refresh_capex import refresh_capex

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    # Seed a company with CIK
    with db_module.session_scope() as session:
        company = Company(
            symbol="MSFT", name="Microsoft", is_active=True, cik="0000789019", is_hyperscaler=True
        )
        session.add(company)
        session.flush()
        # Add a manual capex observation
        session.add(
            CapexObservation(
                company_id=company.id,
                fiscal_period_end=date(2025, 3, 31),
                capex_amount=99999.0,
                source="manual",
                source_label="Manual entry",
            )
        )

    # Mock the SEC fetch to return data for the same period
    def mock_fetch_company_facts(cik, **kwargs):
        return SAMPLE_COMPANY_FACTS

    monkeypatch.setattr(
        "argus.pipelines.refresh_capex.fetch_company_facts",
        mock_fetch_company_facts,
    )
    # Mock execute_provider_request to just call the function directly
    monkeypatch.setattr(
        "argus.pipelines.refresh_capex.execute_provider_request",
        lambda session, provider, func, *args, **kwargs: func(*args, **kwargs),
    )

    result = refresh_capex()
    assert result["status"] == "success"

    with db_module.session_scope() as session:
        company = session.query(Company).filter_by(symbol="MSFT").one()
        manual_obs = (
            session.query(CapexObservation)
            .filter_by(company_id=company.id, fiscal_period_end=date(2025, 3, 31))
            .one()
        )
        # Manual observation should NOT be overwritten
        assert manual_obs.capex_amount == 99999.0
        assert manual_obs.source == "manual"


def test_refresh_capex_skips_company_without_cik(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.pipelines.refresh_capex import refresh_capex

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(
            Company(symbol="MSFT", name="Microsoft", is_active=True, cik=None, is_hyperscaler=True)
        )

    result = refresh_capex()
    # Should still succeed but with a warning about missing CIK
    assert result["rows_written"] == 0


def test_upsert_capex_observation_overwrites_automated_observation(
    sqlite_engine, monkeypatch
) -> None:
    from argus.core import db as db_module
    from argus.pipelines.capex_observations import upsert_capex_observation

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        company = Company(
            symbol="MSFT", name="Microsoft", is_active=True, cik="0000789019", is_hyperscaler=True
        )
        session.add(company)
        session.flush()
        # Seed an automated capex observation
        session.add(
            CapexObservation(
                company_id=company.id,
                fiscal_period_end=date(2025, 3, 31),
                capex_amount=50000.0,
                source="sec_companyfacts",
                source_label="SEC",
            )
        )

    # Now upsert manual observation for the same period
    upsert_capex_observation(
        ticker="MSFT",
        fiscal_period_end=date(2025, 3, 31),
        capex_amount=60000.0,
        source_label="Manual Entry",
    )

    with db_module.session_scope() as session:
        company = session.query(Company).filter_by(symbol="MSFT").one()
        obs = (
            session.query(CapexObservation)
            .filter_by(company_id=company.id, fiscal_period_end=date(2025, 3, 31))
            .one()
        )
        assert obs.capex_amount == 60000.0
        assert obs.source == "manual"
