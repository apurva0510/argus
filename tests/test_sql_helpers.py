from __future__ import annotations

from datetime import date

from argus.core.db import safe_execute_query
from argus.core.sql import date_cast, distinct_string_agg


def test_date_cast_uses_postgres_cast() -> None:
    assert date_cast("postgresql", "ni.published_at") == "CAST(ni.published_at AS DATE)"


def test_date_cast_uses_sqlite_date_function_by_default() -> None:
    assert date_cast("sqlite", "ni.published_at") == "date(ni.published_at)"


def test_distinct_string_agg_uses_postgres_string_agg() -> None:
    assert distinct_string_agg("postgresql", "nm.ticker") == "string_agg(DISTINCT nm.ticker, ',')"


def test_distinct_string_agg_uses_sqlite_group_concat_by_default() -> None:
    assert distinct_string_agg("sqlite", "nm.ticker") == "group_concat(DISTINCT nm.ticker)"


def test_safe_execute_query_only_coerces_explicit_type_map(db_session) -> None:
    rows = safe_execute_query(
        db_session,
        "SELECT '2026-01-02' AS source_date_label, '2026-01-03' AS actual_date",
        type_map={"actual_date": "date"},
    )

    assert rows == [
        {
            "source_date_label": "2026-01-02",
            "actual_date": date(2026, 1, 3),
        }
    ]
