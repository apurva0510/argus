from __future__ import annotations

from argus.core.models import JobRun
from argus.pipelines.job_runs import create_job_run, finish_job_run, job_run_context


def test_create_and_finish_job_run(sqlite_engine) -> None:
    job_id = create_job_run("unit_test_job")

    finish_job_run(
        job_id,
        "unit_test_job",
        status="success",
        rows_read=3,
        rows_written=2,
    )

    with sqlite_engine.connect() as conn:
        row = conn.execute(JobRun.__table__.select().where(JobRun.id == job_id)).mappings().one()

    assert row["job_name"] == "unit_test_job"
    assert row["status"] == "success"
    assert row["rows_read"] == 3
    assert row["rows_written"] == 2
    assert row["finished_at"] is not None
    assert row["error_text"] is None


def test_finish_job_run_recreates_missing_row(sqlite_engine) -> None:
    finish_job_run(
        12345,
        "missing_job",
        status="failed",
        rows_read=0,
        rows_written=0,
        error_text="boom",
    )

    with sqlite_engine.connect() as conn:
        row = conn.execute(JobRun.__table__.select().where(JobRun.id == 12345)).mappings().one()

    assert row["job_name"] == "missing_job"
    assert row["status"] == "failed"
    assert row["started_at"] is not None
    assert row["finished_at"] is not None
    assert row["error_text"] == "boom"


def test_job_run_context_records_and_suppresses_exception(sqlite_engine) -> None:
    with job_run_context("context_failure_job") as state:
        state.rows_read = 7
        state.rows_written = 3
        raise RuntimeError("context boom")

    assert state.status == "failed"
    assert state.error_text == "context boom"

    with sqlite_engine.connect() as conn:
        row = (
            conn.execute(
                JobRun.__table__.select().where(JobRun.job_name == "context_failure_job")
            )
            .mappings()
            .one()
        )

    assert row["status"] == "failed"
    assert row["rows_read"] == 7
    assert row["rows_written"] == 3
    assert row["finished_at"] is not None
    assert row["error_text"] == "context boom"
