from __future__ import annotations

from datetime import date
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from argus.core.models import Company, IndexDefinition, IndexConstituent
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
    # Seed active and inactive companies
    c1 = Company(symbol="ETN", name="Eaton", is_active=True, is_benchmark=False)
    c2 = Company(symbol="VRT", name="Vertiv", is_active=False, is_benchmark=False)
    db_session.add_all([c1, c2])
    db_session.flush()

    df = get_candidate_weights_data(db_session)
    assert len(df) == 1
    assert df.iloc[0]["Ticker"] == "ETN"
    assert df.iloc[0]["Weight %"] == 100.0


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

    save_index_definition_from_editor(
        db_session, "My Manual Index", INDEX_MODE_MANUAL, editor_df
    )
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
