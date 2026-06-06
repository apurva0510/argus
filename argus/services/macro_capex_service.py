from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

HYPERSCALER_CAPEX_SYMBOLS = ("MSFT", "AMZN", "GOOGL", "META")


def load_macro_capex_context_from_engine(engine: Engine) -> dict[str, object]:
    with engine.connect() as conn:
        macro = pd.read_sql_query(
            text(
                """
                SELECT series_code, observation_date, value
                FROM macro_observations
                WHERE series_code IN (
                    'DGS10', 'DGS30', 'DGS2', 'FEDFUNDS', 'CPIAUCSL', 'CPILFESL', 'PPIACO',
                    'EIA_ELEC_PRICE', 'EIA_ELEC_DEMAND'
                )
                ORDER BY observation_date ASC
                """
            ),
            conn,
        )
        capex = pd.read_sql_query(
            text(
                """
                SELECT c.symbol, co.fiscal_period_end, co.capex_amount, co.currency
                FROM capex_observations co
                JOIN companies c ON c.id = co.company_id
                WHERE c.symbol IN ('MSFT', 'AMZN', 'GOOGL', 'META')
                ORDER BY co.fiscal_period_end ASC, c.symbol ASC
                """
            ),
            conn,
        )

    return build_macro_capex_context(macro, capex)


def build_macro_capex_context(
    macro: pd.DataFrame,
    capex: pd.DataFrame,
) -> dict[str, object]:
    macro = _normalize_macro_frame(macro)
    capex = _normalize_capex_frame(capex)

    ten_year = _latest_observation(macro, "DGS10")
    thirty_year = _latest_observation(macro, "DGS30")
    two_year = _latest_observation(macro, "DGS2")
    fed_funds = _latest_observation(macro, "FEDFUNDS")
    dgs10_1m_bps = _bps_change(macro, "DGS10", days=30)
    dgs10_3m_bps = _bps_change(macro, "DGS10", days=90)

    cpi_yoy = _yoy_change(macro, "CPIAUCSL")
    core_cpi_yoy = _yoy_change(macro, "CPILFESL")
    ppi_yoy = _yoy_change(macro, "PPIACO")

    elec_price = _latest_observation(macro, "EIA_ELEC_PRICE")
    elec_demand = _latest_observation(macro, "EIA_ELEC_DEMAND")

    latest_capex = _latest_capex_total(capex)
    pressure = _capex_pressure_label(
        dgs10_3m_bps=dgs10_3m_bps,
        core_cpi_yoy=core_cpi_yoy,
        capex_yoy=latest_capex["capex_yoy"],
    )

    return {
        "latest_yields": {
            "dgs10": ten_year,
            "dgs30": thirty_year,
            "dgs2": two_year,
            "fed_funds": fed_funds,
            "dgs10_1m_bps": dgs10_1m_bps,
            "dgs10_3m_bps": dgs10_3m_bps,
        },
        "inflation": {
            "cpi_yoy": cpi_yoy,
            "core_cpi_yoy": core_cpi_yoy,
            "ppi_yoy": ppi_yoy,
        },
        "electricity": {
            "price": elec_price,
            "demand": elec_demand,
        },
        "capex": latest_capex,
        "pressure_label": pressure["label"],
        "pressure_level": pressure["level"],
        "explanation": pressure["explanation"],
    }


def _normalize_macro_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["series_code", "observation_date", "value"])
    normalized = frame.copy()
    normalized["observation_date"] = pd.to_datetime(normalized["observation_date"]).dt.date
    normalized["value"] = pd.to_numeric(normalized["value"], errors="coerce")
    return normalized.dropna(subset=["series_code", "observation_date", "value"])


def _normalize_capex_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "fiscal_period_end", "capex_amount", "currency"])
    normalized = frame.copy()
    normalized["fiscal_period_end"] = pd.to_datetime(normalized["fiscal_period_end"]).dt.date
    normalized["capex_amount"] = pd.to_numeric(normalized["capex_amount"], errors="coerce")
    return normalized.dropna(subset=["symbol", "fiscal_period_end", "capex_amount"])


def _latest_observation(frame: pd.DataFrame, series_code: str) -> dict[str, Any] | None:
    series = frame[frame["series_code"] == series_code].sort_values("observation_date")
    if series.empty:
        return None
    row = series.iloc[-1]
    return {"date": row["observation_date"], "value": float(row["value"])}


def _value_on_or_before(frame: pd.DataFrame, series_code: str, target_date: date) -> float | None:
    series = frame[
        (frame["series_code"] == series_code)
        & (frame["observation_date"] <= target_date)
    ].sort_values("observation_date")
    if series.empty:
        return None
    return float(series.iloc[-1]["value"])


def _bps_change(frame: pd.DataFrame, series_code: str, *, days: int) -> float | None:
    latest = _latest_observation(frame, series_code)
    if latest is None:
        return None
    prior_date = pd.Timestamp(latest["date"]) - pd.Timedelta(days=days)
    prior = _value_on_or_before(frame, series_code, prior_date.date())
    if prior is None:
        return None
    return (latest["value"] - prior) * 100.0


def _yoy_change(frame: pd.DataFrame, series_code: str) -> float | None:
    latest = _latest_observation(frame, series_code)
    if latest is None:
        return None
    prior_date = pd.Timestamp(latest["date"]) - pd.DateOffset(years=1)
    prior = _value_on_or_before(frame, series_code, prior_date.date())
    if prior is None or prior == 0:
        return None
    return (latest["value"] / prior) - 1.0


def _latest_capex_total(frame: pd.DataFrame) -> dict[str, Any]:
    empty_result = {
        "latest_period_end": None,
        "latest_total": None,
        "capex_yoy": None,
        "company_count": 0,
    }
    if frame.empty:
        return empty_result

    if "currency" in frame.columns:
        unique_currencies = frame["currency"].dropna().unique()
        if len(unique_currencies) > 1:
            import logging
            logging.getLogger(__name__).warning(
                "Multiple currencies found in capex observations: %s. Summing without conversion.",
                unique_currencies,
            )

    df = frame.copy()
    df["period_q"] = pd.to_datetime(df["fiscal_period_end"]).dt.to_period("Q")

    grouped = (
        df.groupby("period_q", as_index=False)
        .agg(
            latest_period_end=("fiscal_period_end", "max"),
            latest_total=("capex_amount", "sum"),
            company_count=("symbol", "nunique"),
        )
        .sort_values("period_q")
    )
    latest = grouped.iloc[-1]
    latest_period_q = latest["period_q"]
    prior_period_q = latest_period_q - 4
    prior = grouped[grouped["period_q"] == prior_period_q]
    capex_yoy = None
    if not prior.empty and float(prior.iloc[0]["latest_total"]) != 0:
        capex_yoy = (float(latest["latest_total"]) / float(prior.iloc[0]["latest_total"])) - 1.0

    # Convert latest_period_end to date to avoid returning Timestamp to callers
    latest_date = latest["latest_period_end"]
    if hasattr(latest_date, "date"):
        latest_date = latest_date.date()

    return {
        "latest_period_end": latest_date,
        "latest_total": float(latest["latest_total"]),
        "capex_yoy": capex_yoy,
        "company_count": int(latest["company_count"]),
    }


def _capex_pressure_label(
    *,
    dgs10_3m_bps: float | None,
    core_cpi_yoy: float | None,
    capex_yoy: float | None,
) -> dict[str, object]:
    rates_rising = dgs10_3m_bps is not None and dgs10_3m_bps >= 25.0
    rates_surging = dgs10_3m_bps is not None and dgs10_3m_bps >= 75.0
    inflation_elevated = core_cpi_yoy is not None and core_cpi_yoy >= 0.03
    capex_declining = capex_yoy is not None and capex_yoy < 0.0

    if rates_surging and inflation_elevated and capex_declining:
        return {
            "label": "Severe",
            "level": 3,
            "explanation": "Rates are rising sharply, core inflation is elevated, and reported hyperscaler capex is declining year over year.",
        }
    if rates_rising and inflation_elevated:
        return {
            "label": "High",
            "level": 2,
            "explanation": "Rates are rising and core inflation remains elevated, which can pressure AI infrastructure financing and input costs.",
        }
    if rates_rising or inflation_elevated:
        return {
            "label": "Medium",
            "level": 1,
            "explanation": "One macro pressure signal is elevated; monitor whether hyperscaler capex continues to grow.",
        }
    return {
        "label": "Low",
        "level": 0,
        "explanation": "Rates and core inflation are not currently flashing major pressure signals.",
    }
