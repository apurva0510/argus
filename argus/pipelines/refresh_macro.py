from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import logging

import httpx
import pandas as pd

from argus.core.db import get_insert_statement_producer, session_scope
from argus.core.models import MacroObservation, MacroSeries
from argus.pipelines.job_runs import job_run_context
from argus.pipelines.provider_health import execute_provider_request
from argus.sources.eia_client import fetch_eia_series, is_eia_available

logger = logging.getLogger(__name__)

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@dataclass(frozen=True)
class MacroSeriesDefinition:
    code: str
    name: str
    frequency: str
    units: str
    description: str
    source: str = "fred"


MACRO_SERIES: tuple[MacroSeriesDefinition, ...] = (
    MacroSeriesDefinition(
        "DGS10",
        "10-Year Treasury Yield",
        "daily",
        "percent",
        "10-year Treasury constant maturity rate",
    ),
    MacroSeriesDefinition(
        "DGS30",
        "30-Year Treasury Yield",
        "daily",
        "percent",
        "30-year Treasury constant maturity rate",
    ),
    MacroSeriesDefinition(
        "DGS2",
        "2-Year Treasury Yield",
        "daily",
        "percent",
        "2-year Treasury constant maturity rate",
    ),
    MacroSeriesDefinition(
        "FEDFUNDS",
        "Effective Federal Funds Rate",
        "monthly",
        "percent",
        "Effective federal funds rate",
    ),
    MacroSeriesDefinition(
        "CPIAUCSL", "CPI", "monthly", "index", "Consumer Price Index for All Urban Consumers"
    ),
    MacroSeriesDefinition(
        "CPILFESL", "Core CPI", "monthly", "index", "Consumer Price Index less food and energy"
    ),
    MacroSeriesDefinition(
        "PPIACO",
        "Producer Price Index",
        "monthly",
        "index",
        "Producer Price Index by commodity, all commodities",
    ),
    MacroSeriesDefinition(
        "EIA_ELEC_PRICE",
        "US Average Retail Electricity Price",
        "monthly",
        "cents per kilowatthour",
        "Average retail price of electricity to ultimate customers, monthly",
        source="eia",
    ),
    MacroSeriesDefinition(
        "EIA_ELEC_DEMAND",
        "US Hourly Demand",
        "daily",
        "megawatthours",
        "Electricity hourly demand for Lower 48 balancing authorities, daily",
        source="eia",
    ),
)


def _upsert_macro_series(session, definition: MacroSeriesDefinition) -> None:
    insert_fn = get_insert_statement_producer(session)
    statement = insert_fn(MacroSeries).values(
        {
            "code": definition.code,
            "name": definition.name,
            "source": definition.source,
            "frequency": definition.frequency,
            "units": definition.units,
            "description": definition.description,
        }
    )
    statement = statement.on_conflict_do_update(
        index_elements=["code"],
        set_={
            "name": statement.excluded.name,
            "source": statement.excluded.source,
            "frequency": statement.excluded.frequency,
            "units": statement.excluded.units,
            "description": statement.excluded.description,
        },
    )
    session.execute(statement)


def _upsert_observations(
    session, series_code: str, observations: pd.DataFrame, provider: str = "fred"
) -> int:
    if observations.empty:
        return 0

    observations = (
        observations[["observation_date", "value"]]
        .dropna(subset=["observation_date", "value"])
        .groupby("observation_date", as_index=False, sort=True)["value"]
        .mean()
    )
    if observations.empty:
        return 0

    values = [
        {
            "series_code": series_code,
            "observation_date": row["observation_date"],
            "value": row["value"],
            "provider": provider,
        }
        for row in observations.to_dict(orient="records")
    ]
    insert_fn = get_insert_statement_producer(session)
    statement = insert_fn(MacroObservation).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["series_code", "observation_date"],
        set_={
            "value": statement.excluded.value,
            "provider": statement.excluded.provider,
        },
    )
    session.execute(statement)
    return len(values)


def parse_fred_csv(series_code: str, csv_text: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(csv_text))
    if "observation_date" in frame.columns:
        date_column = "observation_date"
    elif "DATE" in frame.columns:
        date_column = "DATE"
    else:
        date_column = frame.columns[0]

    if series_code not in frame.columns:
        raise ValueError(f"FRED CSV missing expected series column {series_code}")

    parsed = frame[[date_column, series_code]].rename(
        columns={date_column: "observation_date", series_code: "value"}
    )
    parsed["value"] = pd.to_numeric(parsed["value"].replace(".", pd.NA), errors="coerce")
    parsed["observation_date"] = pd.to_datetime(parsed["observation_date"], errors="coerce").dt.date
    parsed = parsed.dropna(subset=["observation_date", "value"])
    return parsed


def fetch_fred_series(series_code: str, *, client: httpx.Client | None = None) -> pd.DataFrame:
    import os
    from argus.core.settings import settings

    owns_client = client is None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    verify_ssl = os.getenv("ARGUS_SKIP_SSL_VERIFY", "").lower() not in ("true", "1", "yes")
    active_client = client or httpx.Client(timeout=20.0, headers=headers, verify=verify_ssl)
    try:
        from datetime import date, timedelta
        import time

        start_date = (date.today() - timedelta(days=3 * 365)).isoformat()

        kwargs = {}
        if not owns_client:
            kwargs["headers"] = headers

        max_retries = 3
        backoff_factor = 2.0
        for attempt in range(max_retries):
            try:
                if settings.fred_api_key:
                    api_url = "https://api.stlouisfed.org/fred/series/observations"
                    response = active_client.get(
                        api_url,
                        params={
                            "series_id": series_code,
                            "api_key": settings.fred_api_key,
                            "file_type": "json",
                            "observation_start": start_date,
                        },
                        **kwargs,
                    )
                    response.raise_for_status()
                    data = response.json()
                    obs = data.get("observations", [])
                    if not obs:
                        return pd.DataFrame(columns=["observation_date", "value"])
                    parsed = pd.DataFrame(obs)[["date", "value"]].rename(
                        columns={"date": "observation_date"}
                    )
                    parsed["value"] = pd.to_numeric(
                        parsed["value"].replace(".", pd.NA), errors="coerce"
                    )
                    parsed["observation_date"] = pd.to_datetime(
                        parsed["observation_date"], errors="coerce"
                    ).dt.date
                    return parsed.dropna(subset=["observation_date", "value"])
                else:
                    response = active_client.get(
                        FRED_CSV_URL,
                        params={"id": series_code, "cosd": start_date},
                        **kwargs,
                    )
                    response.raise_for_status()
                    return parse_fred_csv(series_code, response.text)
            except httpx.HTTPError as exc:
                if attempt == max_retries - 1:
                    logger.error(
                        "Failed to fetch FRED series %s after %d attempts: %s",
                        series_code,
                        max_retries,
                        exc,
                    )
                    raise
                wait_time = backoff_factor**attempt
                logger.warning(
                    "Error fetching FRED series %s (attempt %d/%d): %s. Retrying in %.1fs...",
                    series_code,
                    attempt + 1,
                    max_retries,
                    exc,
                    wait_time,
                )
                time.sleep(wait_time)
        raise httpx.HTTPError("Max retries exceeded")
    finally:
        if owns_client:
            active_client.close()


def refresh_macro(
    *,
    series_codes: list[str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    failed_series: list[str] = []
    definitions = {definition.code: definition for definition in MACRO_SERIES}
    selected_codes = series_codes or [definition.code for definition in MACRO_SERIES]

    with job_run_context("refresh_macro") as state:
        with session_scope() as session:
            for code in selected_codes:
                definition = definitions.get(code)
                if definition is None:
                    failed_series.append(code)
                    logger.warning("Unknown macro series code: %s", code)
                    continue

                try:
                    _upsert_macro_series(session, definition)
                    if definition.source == "eia":
                        if not is_eia_available():
                            logger.info("Skipping EIA series %s: EIA key not configured", code)
                            continue
                        if code == "EIA_ELEC_PRICE":
                            route = "electricity/retail-sales"
                            frequency = "monthly"
                            facets = {"sectorid": ["ALL"], "stateid": ["US"]}
                            data_column = "price"
                        elif code == "EIA_ELEC_DEMAND":
                            route = "electricity/rto/daily-region-data"
                            frequency = "daily"
                            facets = {"respondent": ["US48"], "type": ["D"]}
                            data_column = "value"
                        else:
                            raise ValueError(f"Unknown EIA series code: {code}")

                        observations = execute_provider_request(
                            session,
                            "eia",
                            fetch_eia_series,
                            route,
                            frequency=frequency,
                            facets=facets,
                            client=client,
                            data_column=data_column,
                        )
                        state.rows_read += len(observations)
                        state.rows_written += _upsert_observations(
                            session, code, observations, provider="eia"
                        )
                    else:
                        observations = execute_provider_request(
                            session,
                            "fred",
                            fetch_fred_series,
                            code,
                            client=client,
                        )
                        state.rows_read += len(observations)
                        state.rows_written += _upsert_observations(
                            session, code, observations, provider="fred"
                        )
                except Exception as exc:
                    logger.warning("Failed to refresh macro series %s: %s", code, exc)
                    failed_series.append(code)

            if failed_series:
                state.status = "partial_success" if state.rows_written else "failed"

            state.error_text = state.error_text or (
                f"Failed series: {', '.join(sorted(failed_series))}"
                if failed_series
                else None
            )

    return {
        "status": state.status,
        "rows_read": state.rows_read,
        "rows_written": state.rows_written,
        "failed_series": failed_series,
        "error_text": state.error_text if state.status == "failed" else None,
    }
