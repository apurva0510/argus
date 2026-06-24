from __future__ import annotations

from argus.pipelines.job_runs import job_run_context
from argus.services.thesis_service import generate_all_company_theses


def generate_theses() -> dict[str, object]:
    with job_run_context("generate_theses") as state:
        result = generate_all_company_theses()
        state.rows_read = int(result.get("rows_read") or 0)
        state.rows_written = int(result.get("rows_written") or 0)
        state.status = str(result.get("status") or "success")
        state.error_text = result.get("error_text")
        return result
