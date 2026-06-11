from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import logging

from argus.core.db import session_scope
from argus.core.models import JobRun

logger = logging.getLogger(__name__)


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


class JobRunState:
    def __init__(self, job_id: int):
        self.job_id = job_id
        self.rows_read = 0
        self.rows_written = 0
        self.status = "success"
        self.error_text = None


@contextmanager
def job_run_context(job_name: str):
    job_id = create_job_run(job_name)
    state = JobRunState(job_id)
    try:
        yield state
    except Exception as exc:
        state.status = "failed"
        state.error_text = str(exc)
        logger.exception("Job %s failed", job_name)
    finally:
        finish_job_run(
            state.job_id,
            job_name,
            status=state.status,
            rows_read=state.rows_read,
            rows_written=state.rows_written,
            error_text=state.error_text,
        )

