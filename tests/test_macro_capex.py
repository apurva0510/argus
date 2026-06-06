from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from argus.core.models import CapexObservation, Company
from argus.pipelines.capex_observations import upsert_capex_observation
from argus.services.macro_capex_service import build_macro_capex_context


def test_upsert_capex_observation_success_and_idempotency(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        session.add(Company(symbol="MSFT", name="Microsoft", is_active=True))

    first = upsert_capex_observation(
        ticker="msft",
        fiscal_period_end=date(2026, 3, 31),
        capex_amount=10_000_000_000.0,
        source_label="Q1 earnings",
    )
    second = upsert_capex_observation(
        ticker="MSFT",
        fiscal_period_end=date(2026, 3, 31),
        capex_amount=11_000_000_000.0,
        source_label="Updated Q1 earnings",
    )

    assert first["status"] == "success"
    assert second["status"] == "success"
    with db_module.session_scope() as session:
        rows = session.query(CapexObservation).all()
        assert len(rows) == 1
        assert rows[0].capex_amount == 11_000_000_000.0
        assert rows[0].source_label == "Updated Q1 earnings"


def test_upsert_capex_observation_rejects_unknown_ticker(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with pytest.raises(ValueError, match="Unknown ticker"):
        upsert_capex_observation(
            ticker="NOPE",
            fiscal_period_end=date(2026, 3, 31),
            capex_amount=1.0,
        )


def test_build_macro_capex_context_calculates_pressure_and_capex_yoy() -> None:
    macro = pd.DataFrame(
        [
            {"series_code": "DGS10", "observation_date": date(2026, 1, 1), "value": 4.0},
            {"series_code": "DGS10", "observation_date": date(2026, 4, 1), "value": 4.6},
            {"series_code": "DGS30", "observation_date": date(2026, 4, 1), "value": 4.8},
            {"series_code": "CPILFESL", "observation_date": date(2025, 4, 1), "value": 300.0},
            {"series_code": "CPILFESL", "observation_date": date(2026, 4, 1), "value": 312.0},
            {"series_code": "CPIAUCSL", "observation_date": date(2025, 4, 1), "value": 310.0},
            {"series_code": "CPIAUCSL", "observation_date": date(2026, 4, 1), "value": 319.3},
            {"series_code": "PPIACO", "observation_date": date(2025, 4, 1), "value": 250.0},
            {"series_code": "PPIACO", "observation_date": date(2026, 4, 1), "value": 260.0},
            {"series_code": "EIA_ELEC_PRICE", "observation_date": date(2026, 4, 1), "value": 16.2},
            {"series_code": "EIA_ELEC_DEMAND", "observation_date": date(2026, 4, 1), "value": 380000.0},
        ]
    )
    capex = pd.DataFrame(
        [
            {"symbol": "MSFT", "fiscal_period_end": date(2025, 3, 31), "capex_amount": 10.0},
            {"symbol": "AMZN", "fiscal_period_end": date(2025, 3, 31), "capex_amount": 20.0},
            {"symbol": "MSFT", "fiscal_period_end": date(2026, 3, 31), "capex_amount": 12.0},
            {"symbol": "AMZN", "fiscal_period_end": date(2026, 3, 31), "capex_amount": 24.0},
        ]
    )

    context = build_macro_capex_context(macro, capex)

    assert context["latest_yields"]["dgs10_3m_bps"] == pytest.approx(60.0)
    assert context["inflation"]["core_cpi_yoy"] == pytest.approx(0.04)
    assert context["capex"]["latest_total"] == pytest.approx(36.0)
    assert context["capex"]["capex_yoy"] == pytest.approx(0.20)
    assert context["pressure_label"] == "High"
    assert context["electricity"]["price"]["value"] == 16.2
    assert context["electricity"]["demand"]["value"] == 380000.0


def test_build_macro_capex_context_handles_empty_data() -> None:
    context = build_macro_capex_context(pd.DataFrame(), pd.DataFrame())

    assert context["latest_yields"]["dgs10"] is None
    assert context["inflation"]["core_cpi_yoy"] is None
    assert context["capex"]["latest_total"] is None
    assert context["pressure_label"] == "Low"
    assert context["electricity"]["price"] is None
    assert context["electricity"]["demand"] is None


def test_load_macro_capex_context_from_engine(sqlite_engine, monkeypatch) -> None:
    from argus.core import db as db_module
    from argus.core.models import MacroSeries, MacroObservation, CapexObservation, Company
    from argus.services.macro_capex_service import load_macro_capex_context_from_engine
    from sqlalchemy.orm import sessionmaker, Session

    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )

    with db_module.session_scope() as session:
        msft = Company(symbol="MSFT", name="Microsoft", is_active=True)
        amzn = Company(symbol="AMZN", name="Amazon", is_active=True)
        session.add_all([msft, amzn])
        session.flush()

        session.add(MacroSeries(code="DGS10", name="10Y"))
        session.add(MacroSeries(code="CPILFESL", name="Core CPI"))
        session.flush()

        session.add_all([
            MacroObservation(series_code="DGS10", observation_date=date(2026, 1, 1), value=4.0),
            MacroObservation(series_code="DGS10", observation_date=date(2026, 4, 1), value=4.6),
            MacroObservation(series_code="CPILFESL", observation_date=date(2025, 4, 1), value=300.0),
            MacroObservation(series_code="CPILFESL", observation_date=date(2026, 4, 1), value=312.0),
        ])

        session.add_all([
            CapexObservation(company_id=msft.id, fiscal_period_end=date(2025, 3, 31), capex_amount=10.0),
            CapexObservation(company_id=amzn.id, fiscal_period_end=date(2025, 3, 31), capex_amount=20.0),
            CapexObservation(company_id=msft.id, fiscal_period_end=date(2026, 3, 31), capex_amount=12.0),
            CapexObservation(company_id=amzn.id, fiscal_period_end=date(2026, 3, 31), capex_amount=24.0),
        ])

    context = load_macro_capex_context_from_engine(sqlite_engine)

    assert context["latest_yields"]["dgs10_3m_bps"] == pytest.approx(60.0)
    assert context["inflation"]["core_cpi_yoy"] == pytest.approx(0.04)
    assert context["capex"]["latest_total"] == pytest.approx(36.0)
    assert context["capex"]["capex_yoy"] == pytest.approx(0.20)
    assert context["pressure_label"] == "High"


def test_build_macro_capex_context_groups_by_calendar_quarter() -> None:
    macro = pd.DataFrame(
        [
            {"series_code": "DGS10", "observation_date": date(2026, 4, 1), "value": 4.0},
            {"series_code": "CPILFESL", "observation_date": date(2026, 4, 1), "value": 300.0},
        ]
    )
    capex = pd.DataFrame(
        [
            {"symbol": "MSFT", "fiscal_period_end": date(2025, 3, 28), "capex_amount": 10.0, "currency": "USD"},
            {"symbol": "AMZN", "fiscal_period_end": date(2025, 3, 31), "capex_amount": 20.0, "currency": "USD"},
            {"symbol": "MSFT", "fiscal_period_end": date(2026, 3, 29), "capex_amount": 12.0, "currency": "USD"},
            {"symbol": "AMZN", "fiscal_period_end": date(2026, 3, 31), "capex_amount": 24.0, "currency": "USD"},
        ]
    )

    context = build_macro_capex_context(macro, capex)

    assert context["capex"]["latest_total"] == pytest.approx(36.0)
    assert context["capex"]["capex_yoy"] == pytest.approx(0.20)
    assert context["capex"]["latest_period_end"] == date(2026, 3, 31)


def test_build_macro_capex_context_logs_currency_warning(caplog) -> None:
    import logging
    macro = pd.DataFrame()
    capex = pd.DataFrame(
        [
            {"symbol": "MSFT", "fiscal_period_end": date(2026, 3, 31), "capex_amount": 12.0, "currency": "USD"},
            {"symbol": "AMZN", "fiscal_period_end": date(2026, 3, 31), "capex_amount": 24.0, "currency": "EUR"},
        ]
    )

    with caplog.at_level(logging.WARNING):
        context = build_macro_capex_context(macro, capex)

    assert context["capex"]["latest_total"] == pytest.approx(36.0)
    warnings = [rec.message for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("Multiple currencies found" in w for w in warnings)
