from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from argus.analytics.index_builder import create_index_definition
from argus.core.models import Company
from argus.services.index_view_service import (
    daily_close_levels_from_session_returns,
    load_index_options_from_engine,
)


def test_daily_close_levels_from_session_returns_maps_daily_return_to_session_open() -> None:
    intraday = pd.DataFrame(
        [
            {"date": "2026-01-05 14:30:00", "index_level": 100.0},
            {"date": "2026-01-05 14:45:00", "index_level": 101.0},
            {"date": "2026-01-06 14:30:00", "index_level": 105.0},
        ]
    )
    daily = pd.DataFrame(
        [
            {"date": date(2026, 1, 4), "index_value": 100.0},
            {"date": date(2026, 1, 5), "index_value": 110.0},
            {"date": date(2026, 1, 6), "index_value": 115.5},
        ]
    )

    result = daily_close_levels_from_session_returns(
        intraday,
        daily,
        daily_value_column="index_value",
        output_column="index_level",
    )

    assert result["date"].tolist() == [date(2026, 1, 5), date(2026, 1, 6)]
    assert result["index_level"].tolist() == pytest.approx([110.0, 110.25])


def test_daily_close_levels_returns_empty_frame_for_missing_columns() -> None:
    result = daily_close_levels_from_session_returns(
        pd.DataFrame({"date": ["2026-01-05"]}),
        pd.DataFrame({"date": ["2026-01-05"]}),
        daily_value_column="index_value",
        output_column="index_level",
    )

    assert result.empty
    assert list(result.columns) == ["date", "index_level"]


def test_load_index_options_from_engine_returns_id_name_and_mode(sqlite_engine, db_session) -> None:
    db_session.add(Company(symbol="A", name="A", is_active=True))
    db_session.flush()
    create_index_definition(
        db_session,
        name="Custom Equal",
        mode="equal",
        company_weights={"A": 1.0},
    )
    db_session.commit()

    options = load_index_options_from_engine(sqlite_engine)

    assert any(
        option["name"] == "Custom Equal" and option["mode"] == "equal" and option["id"]
        for option in options
    )
