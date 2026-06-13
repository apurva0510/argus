from __future__ import annotations


def date_cast(dialect_name: str, expression: str) -> str:
    if dialect_name == "postgresql":
        return f"CAST({expression} AS DATE)"
    return f"date({expression})"


def distinct_string_agg(dialect_name: str, expression: str) -> str:
    if dialect_name == "postgresql":
        return f"string_agg(DISTINCT {expression}, ',')"
    return f"group_concat(DISTINCT {expression})"
