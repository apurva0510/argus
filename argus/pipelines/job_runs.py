from __future__ import annotations

from datetime import UTC, datetime

from argus.core.db import session_scope
from argus.core.models import JobRun


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def create_job_run(job_name: str) -> int:
    with session_scope() as session:
        job = JobRun(job_name=job_name, started_at=utc_now(), status="running")
        session.add(job)
        session.flush()
        return job.id


def finish_job_run(
    job_id: int,
    job_name: str,
    *,
    status: str,
    rows_read: int,
    rows_written: int,
    error_text: str | None = None,
) -> None:
    with session_scope() as session:
        job = session.get(JobRun, job_id)
        if job is None:
            job = JobRun(id=job_id, job_name=job_name, started_at=utc_now(), status=status)
            session.add(job)

        job.finished_at = utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        job.error_text = error_text
