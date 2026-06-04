from __future__ import annotations

import logging
from datetime import UTC, datetime
from sqlalchemy import delete

from argus.core.db import session_scope
from argus.core.models import JobRun, IndexValue
from argus.analytics.index_builder import calculate_equal_weight_index

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def refresh_index() -> dict[str, object]:
    """Calculate the AI Infra Core Index values and persist them to the database."""
    with session_scope() as session:
        job = JobRun(job_name="refresh_index", started_at=_utc_now(), status="running")
        session.add(job)
        session.flush()
        job_id = job.id

    rows_read = 0
    rows_written = 0
    status = "success"
    error_text = None

    try:
        with session_scope() as session:
            # 1. Calculate equal-weight index using historical price bars
            df = calculate_equal_weight_index(session, use_precomputed=False)
            if not df.empty:
                rows_read = len(df)

                # 2. Clear existing pre-calculated index values to support historical updates/splits
                session.execute(delete(IndexValue))

                # 3. Batch insert the new calculated time series
                values = [
                    {
                        "date": row["date"],
                        "index_value": float(row["index_value"]),
                    }
                    for _, row in df.iterrows()
                ]

                if values:
                    session.execute(IndexValue.__table__.insert(), values)
                    rows_written = len(values)

            logger.info("Successfully refreshed %d index value rows", rows_written)

    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Core Index calculation and refresh pipeline failed")
    finally:
        with session_scope() as session:
            job = session.get(JobRun, job_id)
            if job is not None:
                job.finished_at = _utc_now()
                job.status = status
                job.rows_read = rows_read
                job.rows_written = rows_written
                job.error_text = error_text

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "error_text": error_text,
    }
