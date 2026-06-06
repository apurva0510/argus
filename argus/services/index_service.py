from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from argus.core.models import Company, CompanyThemeExposure, Theme
from argus.analytics.index_builder import (
    INDEX_MODE_MANUAL,
    list_index_definitions,
    calculate_weighted_index,
    calculate_relative_performance,
    calculate_theme_concentration,
    calculate_top_contributors_for_definition,
    get_index_constituent_table,
    create_index_definition,
    validate_manual_weights,
)


def get_index_options(session: Session) -> list[dict[str, object]]:
    """Fetch all available index definitions and return them as basic dictionaries."""
    return [
        {
            "id": definition.id,
            "name": definition.name,
            "mode": definition.mode,
            "base_value": definition.base_value,
            "created_at": definition.created_at,
        }
        for definition in list_index_definitions(session)
    ]


def get_index_preview_data(
    session: Session, index_definition_id: int, timeframe: str
) -> dict[str, object]:
    """Retrieve weights, performance relative to benchmarks, theme concentrations, and contributors for preview."""
    index_df = calculate_weighted_index(
        session,
        definition_id=index_definition_id,
        use_precomputed=True,
    )
    if index_df.empty:
        index_df = calculate_weighted_index(
            session,
            definition_id=index_definition_id,
            use_precomputed=False,
        )
    if index_df.empty:
        return {
            "index_df": pd.DataFrame(),
            "rel_df": pd.DataFrame(),
            "weights": get_index_constituent_table(session, index_definition_id),
            "themes": calculate_theme_concentration(session, index_definition_id),
            "contributors": pd.DataFrame(),
        }

    latest_point = pd.to_datetime(index_df["date"]).max()
    if timeframe == "1M":
        start_date = (latest_point - pd.Timedelta(days=30)).date()
    elif timeframe == "3M":
        start_date = (latest_point - pd.Timedelta(days=90)).date()
    elif timeframe == "6M":
        start_date = (latest_point - pd.Timedelta(days=180)).date()
    elif timeframe == "1Y":
        start_date = (latest_point - pd.Timedelta(days=365)).date()
    else:
        start_date = pd.to_datetime(index_df["date"]).min().date()

    rel_df = calculate_relative_performance(session, index_df, start_date)
    if not rel_df.empty:
        rel_df["index_level"] = 100.0 + rel_df["index_ret"]
        if "qqq_ret" in rel_df and not rel_df["qqq_ret"].isna().all():
            rel_df["qqq_level"] = 100.0 + rel_df["qqq_ret"]
        if "nvda_ret" in rel_df and not rel_df["nvda_ret"].isna().all():
            rel_df["nvda_level"] = 100.0 + rel_df["nvda_ret"]

    latest_date = latest_point.date()
    contributor_start = latest_date - pd.Timedelta(days=90)
    return {
        "index_df": index_df,
        "rel_df": rel_df,
        "weights": get_index_constituent_table(session, index_definition_id),
        "themes": calculate_theme_concentration(session, index_definition_id),
        "contributors": calculate_top_contributors_for_definition(
            session,
            index_definition_id,
            contributor_start,
            latest_date,
        ),
    }


def get_candidate_weights_data(session: Session) -> pd.DataFrame:
    """Fetch active non-hyperscaler, non-benchmark companies for index creation."""
    rows = (
        session.query(
            Company.id,
            Company.symbol,
            Company.name,
            Theme.name.label("theme_name"),
        )
        .outerjoin(CompanyThemeExposure, CompanyThemeExposure.company_id == Company.id)
        .outerjoin(Theme, Theme.id == CompanyThemeExposure.theme_id)
        .filter(
            Company.is_active.is_(True),
            Company.is_benchmark.is_(False),
            Company.is_hyperscaler.is_(False),
        )
        .order_by(Company.symbol.asc(), Theme.name.asc())
        .all()
    )
    companies: dict[int, dict[str, object]] = {}
    for row in rows:
        company = companies.setdefault(
            row.id,
            {
                "symbol": row.symbol,
                "name": row.name,
                "themes": set(),
            },
        )
        if row.theme_name:
            company["themes"].add(row.theme_name)

    weight = 100.0 / len(companies) if companies else 0.0
    return pd.DataFrame(
        [
            {
                "Include": True,
                "Ticker": company["symbol"],
                "Company": company["name"],
                "Theme": ", ".join(sorted(company["themes"])) if company["themes"] else "n/a",
                "Weight %": weight,
            }
            for company in companies.values()
        ]
    )


def save_index_definition_from_editor(
    session: Session, name: str, mode: str, editor_df: pd.DataFrame
) -> None:
    """Validate and insert a new index definition along with its constituents based on table input."""
    included = editor_df[editor_df["Include"]].copy()
    if mode == INDEX_MODE_MANUAL:
        weights = {
            row["Ticker"]: float(row["Weight %"]) / 100.0
            for _, row in included.iterrows()
        }
        validate_manual_weights(weights)
    else:
        weights = {row["Ticker"]: 1.0 for _, row in included.iterrows()}

    create_index_definition(session, name=name, mode=mode, company_weights=weights)
