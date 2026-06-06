from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx
import pandas as pd

from argus.core.settings import settings

logger = logging.getLogger(__name__)

EIA_API_V2_BASE = "https://api.eia.gov/v2"


def is_eia_available() -> bool:
    """Return True when the EIA API key is configured."""
    return bool(settings.eia_api_key and settings.eia_api_key.strip())


def fetch_eia_series(
    route: str,
    *,
    frequency: str = "monthly",
    facets: dict | None = None,
    start_date: date | None = None,
    client: httpx.Client | None = None,
    data_column: str = "value",
) -> pd.DataFrame:
    """Fetch a time-series from the EIA API v2.

    Args:
        route: API route after base, e.g. "electricity/retail-sales".
        frequency: One of "monthly", "daily", "annual".
        facets: Optional facet filters, e.g. {"sectorid": ["ALL"], "stateid": ["US"]}.
        start_date: Earliest observation date to return.
        client: Optional shared httpx.Client.
        data_column: The data column to request, e.g. "value" or "price".

    Returns:
        DataFrame with columns [observation_date, value].
    """
    if not is_eia_available():
        return pd.DataFrame(columns=["observation_date", "value"])

    api_key = settings.eia_api_key.strip()
    url = f"{EIA_API_V2_BASE}/{route}/data/"
    if start_date is None:
        start_date = date.today() - timedelta(days=3 * 365)

    params: dict = {
        "api_key": api_key,
        "frequency": frequency,
        "start": start_date.isoformat(),
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
        "data[]": data_column,
    }
    if facets:
        for key, values in facets.items():
            params[f"facets[{key}][]"] = list(values)

    import os

    verify_ssl = os.getenv("ARGUS_SKIP_SSL_VERIFY", "").lower() not in ("true", "1", "yes")
    owns_client = client is None
    active_client = client or httpx.Client(timeout=30.0, verify=verify_ssl)
    try:
        import time

        max_retries = 3
        backoff_factor = 2.0
        for attempt in range(max_retries):
            try:
                response = active_client.get(url, params=params)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if 400 <= status_code < 500 and status_code != 429:
                    logger.error(
                        "EIA rejected request for %s with non-retryable status %s: %s",
                        route,
                        status_code,
                        exc,
                    )
                    raise
                if attempt == max_retries - 1:
                    logger.error(
                        "Failed to fetch EIA series %s after %d attempts: %s",
                        route,
                        max_retries,
                        exc,
                    )
                    raise
                wait_time = backoff_factor**attempt
                logger.warning(
                    "Error fetching EIA series %s (attempt %d/%d): %s. Retrying in %.1fs...",
                    route,
                    attempt + 1,
                    max_retries,
                    exc,
                    wait_time,
                )
                time.sleep(wait_time)
            except httpx.HTTPError as exc:
                if attempt == max_retries - 1:
                    logger.error(
                        "Failed to fetch EIA series %s after %d attempts: %s",
                        route,
                        max_retries,
                        exc,
                    )
                    raise
                wait_time = backoff_factor**attempt
                logger.warning(
                    "Error fetching EIA series %s (attempt %d/%d): %s. Retrying in %.1fs...",
                    route,
                    attempt + 1,
                    max_retries,
                    exc,
                    wait_time,
                )
                time.sleep(wait_time)

        data = response.json()
        rows = data.get("response", {}).get("data", [])
        if not rows:
            return pd.DataFrame(columns=["observation_date", "value"])

        frame = pd.DataFrame(rows)
        if "period" not in frame.columns or data_column not in frame.columns:
            logger.warning("EIA response missing expected columns for %s", route)
            return pd.DataFrame(columns=["observation_date", "value"])

        result = frame[["period", data_column]].rename(
            columns={"period": "observation_date", data_column: "value"}
        )
        result["value"] = pd.to_numeric(result["value"], errors="coerce")
        result["observation_date"] = pd.to_datetime(
            result["observation_date"], errors="coerce"
        ).dt.date
        return result.dropna(subset=["observation_date", "value"])
    finally:
        if owns_client:
            active_client.close()
