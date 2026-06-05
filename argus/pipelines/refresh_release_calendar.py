from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import logging

import httpx

from argus.core.db import get_insert_statement_producer, session_scope
from argus.core.models import JobRun, MacroReleaseEvent, MacroSeries
from argus.core.settings import settings

logger = logging.getLogger(__name__)

# FRED Release IDs mapped to the macro series they cover
FRED_RELEASE_SERIES_MAP: dict[int, list[str]] = {
    18: ["DGS10", "DGS30", "DGS2", "FEDFUNDS"],  # H.15 Selected Interest Rates
    10: ["CPIAUCSL", "CPILFESL"],                  # Consumer Price Index
    51: ["PPIACO"],                                  # Producer Price Index
}

FRED_RELEASE_NAMES: dict[int, str] = {
    18: "H.15 Selected Interest Rates",
    10: "Consumer Price Index",
    51: "Producer Price Index",
}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _create_job_run() -> int:
    with session_scope() as session:
        job = JobRun(job_name="refresh_release_calendar", started_at=_utc_now(), status="running")
        session.add(job)
        session.flush()
        return job.id


def _finish_job_run(
    job_id: int,
    *,
    status: str,
    rows_read: int,
    rows_written: int,
    error_text: str | None = None,
) -> None:
    with session_scope() as session:
        job = session.get(JobRun, job_id)
        if job is None:
            job = JobRun(id=job_id, job_name="refresh_release_calendar", started_at=_utc_now(), status=status)
            session.add(job)
        job.finished_at = _utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        job.error_text = error_text


def fetch_fred_release_dates(
    release_id: int,
    *,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Fetch upcoming release dates for a FRED release."""
    api_key = settings.fred_api_key.strip()
    if not api_key:
        return []

    url = "https://api.stlouisfed.org/fred/release/dates"
    today = date.today()
    params = {
        "release_id": release_id,
        "api_key": api_key,
        "file_type": "json",
        "include_release_dates_with_no_data": "true",
        "realtime_start": (today - timedelta(days=30)).isoformat(),
        "realtime_end": (today + timedelta(days=90)).isoformat(),
    }

    owns_client = client is None
    active_client = client or httpx.Client(timeout=20.0)
    try:
        response = active_client.get(url, params=params)
        response.raise_for_status()
        return response.json().get("release_dates", [])
    finally:
        if owns_client:
            active_client.close()


def refresh_release_calendar(
    *,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Refresh macro release calendar from FRED release-date endpoints."""
    if not settings.fred_api_key or not settings.fred_api_key.strip():
        return {
            "status": "skipped",
            "rows_read": 0,
            "rows_written": 0,
            "error_text": "FRED_API_KEY not configured",
        }

    job_id = _create_job_run()
    rows_read = 0
    rows_written = 0
    status = "success"
    error_text: str | None = None
    failed_releases: list[int] = []

    try:
        with session_scope() as session:
            # Ensure macro_series exist for all tracked codes
            existing_codes = {
                row.code
                for row in session.query(MacroSeries.code).all()
            }

            for release_id, series_codes in FRED_RELEASE_SERIES_MAP.items():
                try:
                    dates = fetch_fred_release_dates(release_id, client=client)
                    rows_read += len(dates)

                    release_name = FRED_RELEASE_NAMES.get(release_id, f"Release {release_id}")

                    for date_entry in dates:
                        release_date_str = date_entry.get("date") or date_entry.get("release_date")
                        if not release_date_str:
                            continue
                        try:
                            release_date = date.fromisoformat(release_date_str)
                        except (ValueError, TypeError):
                            continue

                        for series_code in series_codes:
                            if series_code not in existing_codes:
                                continue
                            insert_fn = get_insert_statement_producer(session)
                            stmt = insert_fn(MacroReleaseEvent).values(
                                {
                                    "series_code": series_code,
                                    "release_date": release_date,
                                    "event_name": release_name,
                                    "status": "scheduled",
                                }
                            )
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["series_code", "release_date"],
                                set_={
                                    "event_name": stmt.excluded.event_name,
                                    "status": stmt.excluded.status,
                                },
                            )
                            session.execute(stmt)
                            rows_written += 1

                except Exception as exc:
                    logger.warning("Failed to refresh release dates for release %d: %s", release_id, exc)
                    failed_releases.append(release_id)

        if failed_releases:
            status = "partial_success" if rows_written else "failed"
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Release calendar refresh failed")
    finally:
        _finish_job_run(
            job_id,
            status=status,
            rows_read=rows_read,
            rows_written=rows_written,
            error_text=error_text,
        )

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "error_text": error_text,
    }
