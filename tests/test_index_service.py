from __future__ import annotations

import pandas as pd
from datetime import date, timedelta
from sqlalchemy.orm import Session

from argus.core.models import (
    Company,
    CompanyThemeExposure,
    IndexDefinition,
    IndexConstituent,
    PriceBar,
    Theme,
)
from argus.services.index_service import (
    get_index_options,
    get_index_preview_data,
    get_candidate_weights_data,
    save_index_definition_from_editor,
)
from argus.analytics.index_builder import (
    INDEX_MODE_EQUAL,
    INDEX_MODE_MANUAL,
    create_index_definition,
)


def test_get_index_options(db_session: Session) -> None:
    # Seed active company
    company = Company(symbol="AAPL", name="Apple", is_active=True, is_benchmark=False)
    db_session.add(company)
    db_session.flush()

    # Seed definitions
    create_index_definition(
        db_session,
        name="Index A",
        mode=INDEX_MODE_EQUAL,
        company_weights={"AAPL": 1.0},
    )
    db_session.flush()

    options = get_index_options(db_session)
    assert len(options) >= 1
    names = [opt["name"] for opt in options]
    assert "Index A" in names

    # Check options details for our created index
    opt = next(o for o in options if o["name"] == "Index A")
    assert opt["mode"] == INDEX_MODE_EQUAL


def test_get_candidate_weights_data(db_session: Session) -> None:
    # Seed active, inactive, benchmark, and hyperscaler companies.
    c1 = Company(symbol="ETN", name="Eaton", is_active=True, is_benchmark=False)
    c2 = Company(symbol="VRT", name="Vertiv", is_active=False, is_benchmark=False)
    c3 = Company(symbol="NVDA", name="NVIDIA", is_active=True, is_benchmark=True)
    c4 = Company(symbol="MSFT", name="Microsoft", is_active=True, is_hyperscaler=True)
    c5 = Company(symbol="CRWD", name="CrowdStrike", is_active=True, is_benchmark=False)
    theme = Theme(code="power_grid", name="Power and Grid")
    db_session.add_all([c1, c2, c3, c4, c5, theme])
    db_session.flush()
    db_session.add(CompanyThemeExposure(company_id=c1.id, theme_id=theme.id, exposure_score=1.0))
    db_session.flush()

    df = get_candidate_weights_data(db_session)
    assert set(df["Ticker"]) == {"CRWD", "ETN"}
    assert set(df["Weight %"]) == {50.0}
    assert df.loc[df["Ticker"] == "ETN", "Theme"].iloc[0] == "Power and Grid"
    assert df.loc[df["Ticker"] == "CRWD", "Theme"].iloc[0] == "n/a"


def test_save_index_definition_from_editor(db_session: Session) -> None:
    # Seed companies
    c1 = Company(symbol="AAPL", name="Apple", is_active=True, is_benchmark=False)
    c2 = Company(symbol="MSFT", name="Microsoft", is_active=True, is_benchmark=False)
    db_session.add_all([c1, c2])
    db_session.flush()

    # Create manual editor df
    editor_df = pd.DataFrame(
        [
            {"Include": True, "Ticker": "AAPL", "Weight %": 60.0},
            {"Include": True, "Ticker": "MSFT", "Weight %": 40.0},
        ]
    )

    save_index_definition_from_editor(db_session, "My Manual Index", INDEX_MODE_MANUAL, editor_df)
    db_session.flush()

    # Query db to verify it was created
    defn = db_session.query(IndexDefinition).filter_by(name="My Manual Index").first()
    assert defn is not None
    assert defn.mode == INDEX_MODE_MANUAL

    constituents = db_session.query(IndexConstituent).filter_by(index_definition_id=defn.id).all()
    assert len(constituents) == 2


def test_get_index_preview_data_empty(db_session: Session) -> None:
    company = Company(symbol="AAPL", name="Apple", is_active=True, is_benchmark=False)
    db_session.add(company)
    db_session.flush()

    create_index_definition(
        db_session,
        name="Empty Index",
        mode=INDEX_MODE_EQUAL,
        company_weights={"AAPL": 1.0},
    )
    db_session.flush()
    defn = db_session.query(IndexDefinition).filter_by(name="Empty Index").one()

    preview = get_index_preview_data(db_session, defn.id, "1M")
    assert preview["index_df"].empty
    assert preview["rel_df"].empty
    assert preview["contributors"].empty


def test_get_index_preview_data_calculates_when_values_not_persisted(db_session: Session) -> None:
    company = Company(symbol="AAPL", name="Apple", is_active=True, is_benchmark=False)
    db_session.add(company)
    db_session.flush()
    start = date(2026, 1, 2)
    for offset, price in enumerate([100.0, 105.0]):
        db_session.add(
            PriceBar(
                company_id=company.id,
                date=start + timedelta(days=offset),
                adj_close=price,
                provider="yfinance",
                interval="1d",
            )
        )

    definition = create_index_definition(
        db_session,
        name="Dynamic Preview",
        mode=INDEX_MODE_EQUAL,
        company_weights={"AAPL": 1.0},
    )
    db_session.flush()

    preview = get_index_preview_data(db_session, definition.id, "All")

    assert not preview["index_df"].empty
    assert preview["index_df"].iloc[-1]["index_value"] == 105.0
