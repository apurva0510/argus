from __future__ import annotations

from argus.core.sql import date_cast, distinct_string_agg


def test_date_cast_uses_postgres_cast() -> None:
    assert date_cast("postgresql", "ni.published_at") == "CAST(ni.published_at AS DATE)"


def test_date_cast_uses_sqlite_date_function_by_default() -> None:
    assert date_cast("sqlite", "ni.published_at") == "date(ni.published_at)"


def test_distinct_string_agg_uses_postgres_string_agg() -> None:
    assert distinct_string_agg("postgresql", "nm.ticker") == "string_agg(DISTINCT nm.ticker, ',')"


def test_distinct_string_agg_uses_sqlite_group_concat_by_default() -> None:
    assert distinct_string_agg("sqlite", "nm.ticker") == "group_concat(DISTINCT nm.ticker)"
