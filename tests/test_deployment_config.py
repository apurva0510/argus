from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from argus.core import models  # noqa: F401
from argus.core.db import Base, create_database_engine, get_insert_statement_producer
from argus.core.models import Company, PriceBar
from scripts.enable_rls import _quote_identifier


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_intraday_workflow_runs_every_30_minutes_during_market_hours_et() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "intraday-prices.yml").read_text(
        encoding="utf-8"
    )

    assert "GitHub cron is UTC-only" in workflow
    assert "These off-hour half-hour marks cover the requested" in workflow
    assert 'cron: "7,37 13-21 * * 1-5"' in workflow
    assert 'ZoneInfo("America/New_York")' in workflow
    assert "start = time(9, 30)" in workflow
    assert "end = time(16, 0)" in workflow
    assert 'os.environ["GITHUB_OUTPUT"]' in workflow
    assert 'open("$GITHUB_OUTPUT"' not in workflow
    assert "python scripts/backfill_prices.py --period 5d --interval 15m" in workflow
    assert "python scripts/compute_metrics.py" in workflow
    assert "python scripts/refresh_index.py" in workflow
    assert workflow.index("python scripts/compute_metrics.py") < workflow.index(
        "python scripts/refresh_index.py"
    )
    assert workflow.index("python scripts/refresh_index.py") < workflow.index(
        "python scripts/run_alerts.py"
    )


def test_daily_close_workflow_runs_until_7pm_et_with_manual_override() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "daily-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "GitHub cron is UTC-only" in workflow
    assert "requested 4:00-7:00 PM ET" in workflow
    assert 'cron: "17,47 20-23 * * 1-5"' in workflow
    assert 'ZoneInfo("America/New_York")' in workflow
    assert 'os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"' in workflow
    assert "start = time(16, 0)" in workflow
    assert "end = time(19, 0)" in workflow
    assert "is_manual or in_window" in workflow
    assert "steps.daily_close_window.outputs.run_job == 'true'" in workflow
    assert "python scripts/run_daily_refresh.py --period 2y --skip-news --skip-filings" in workflow


def test_daily_refresh_orchestrator_includes_refresh_index() -> None:
    source = (PROJECT_ROOT / "argus" / "pipelines" / "run_daily_refresh.py").read_text(
        encoding="utf-8"
    )

    assert "from argus.pipelines.refresh_index import refresh_index" in source
    assert '("refresh_index", refresh_index)' in source
    assert "from argus.pipelines.run_alerts import run_alerts" in source
    assert '("run_alerts", run_alerts)' in source


def test_filings_workflow_syncs_ciks_before_refreshing_filings() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "filings-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "Every 3 hours, every day" in workflow
    assert 'cron: "0 */3 * * *"' in workflow
    assert "python scripts/refresh_ciks.py" in workflow
    assert "python scripts/refresh_filings.py" in workflow
    assert workflow.index("python scripts/refresh_ciks.py") < workflow.index(
        "python scripts/refresh_filings.py"
    )
    assert workflow.index("python scripts/refresh_filings.py") < workflow.index(
        "python scripts/run_alerts.py"
    )


def test_filings_cli_allows_partial_success_but_fails_complete_failure() -> None:
    from scripts.refresh_filings import exit_code_for_status

    assert exit_code_for_status("success") == 0
    assert exit_code_for_status("partial_success") == 0
    assert exit_code_for_status("failed") == 1


def test_cik_cli_allows_partial_success_but_fails_complete_failure() -> None:
    from scripts.refresh_ciks import exit_code_for_status

    assert exit_code_for_status("success") == 0
    assert exit_code_for_status("partial_success") == 0
    assert exit_code_for_status("failed") == 1


def test_news_workflow_has_no_github_actions_skip_gate() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "news-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "Every 2 hours, every day" in workflow
    assert 'cron: "0 */2 * * *"' in workflow
    assert "Determine if news refresh window" not in workflow
    assert "steps.news_refresh_window.outputs.run_job" not in workflow
    assert "python scripts/refresh_news.py --bypass-refresh-throttle" in workflow
    assert "python scripts/compute_signals.py" in workflow
    assert workflow.index("python scripts/refresh_news.py") < workflow.index(
        "python scripts/compute_signals.py"
    )
    assert workflow.index("python scripts/compute_signals.py") < workflow.index(
        "python scripts/run_alerts.py"
    )
    assert "--force" not in workflow


def test_ir_feeds_workflow_runs_every_6_hours() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ir-feeds-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "GitHub cron is UTC-only" in workflow
    assert "Run every 6 hours at an off-peak minute" in workflow
    assert 'cron: "22 */6 * * *"' in workflow
    assert "Determine if IR refresh window" not in workflow
    assert "steps.ir_refresh_window.outputs.run_job" not in workflow
    assert "python scripts/refresh_ir_feeds.py" in workflow
    assert "python scripts/compute_signals.py" in workflow
    assert workflow.index("python scripts/refresh_ir_feeds.py") < workflow.index(
        "python scripts/compute_signals.py"
    )
    assert workflow.index("python scripts/compute_signals.py") < workflow.index(
        "python scripts/run_alerts.py"
    )
    assert "--force" not in workflow


def test_daily_refresh_cli_allows_partial_success_without_failing_workflow() -> None:
    script = (PROJECT_ROOT / "scripts" / "run_daily_refresh.py").read_text(encoding="utf-8")

    assert "Warning: {result['error_text']}" in script
    assert 'result.get("status") == "failed"' in script
    assert "sys.exit(1)" in script


def test_scheduled_workflows_validate_database_url_secret() -> None:
    for workflow_name in (
        "daily-refresh.yml",
        "filings-refresh.yml",
        "ir-feeds-refresh.yml",
        "intraday-prices.yml",
        "news-refresh.yml",
    ):
        workflow = (PROJECT_ROOT / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )
        assert "Validate required secrets" in workflow
        assert "DATABASE_URL secret is required" in workflow
        assert "APP_AUTH_SECRET: ${{ secrets.APP_AUTH_SECRET }}" in workflow


def test_readme_documents_supabase_rls_step() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "scripts/enable_rls.py" in readme
    assert "Row Level Security" in readme


def test_rls_identifier_quoting_handles_pooler_roles() -> None:
    assert _quote_identifier("postgres.project-ref") == '"postgres.project-ref"'
    assert _quote_identifier('postgres"role') == '"postgres""role"'


def test_ci_workflow_runs_lint_tests_and_postgres_service() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "  push:" in workflow
    assert "branches: [main]" in workflow
    assert "ruff check ." in workflow
    assert "python -m pytest" in workflow
    assert "postgres:16" in workflow


@pytest.mark.postgres
def test_postgres_schema_and_price_upsert_smoke(monkeypatch) -> None:
    import os

    database_url = os.environ.get("TEST_DATABASE_URL")
    allow_drops = os.environ.get("ARGUS_ALLOW_POSTGRES_TEST_DROPS") == "1"
    if not database_url or not allow_drops:
        pytest.skip("Set TEST_DATABASE_URL and ARGUS_ALLOW_POSTGRES_TEST_DROPS=1 to run")

    base_engine = create_database_engine(database_url)
    schema_name = f"argus_test_{uuid4().hex}"
    engine = base_engine.execution_options(schema_translate_map={None: schema_name})
    try:
        with base_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        with Session(engine) as session:
            company = Company(symbol="TST", name="Test Corp")
            session.add(company)
            session.flush()

            insert = get_insert_statement_producer(session)
            statement = insert(PriceBar).values(
                [
                    {
                        "company_id": company.id,
                        "date": "2026-01-02",
                        "bar_time": "2026-01-02 00:00:00",
                        "close": 10.0,
                        "adj_close": 10.0,
                        "provider": "yfinance",
                        "interval": "1d",
                    }
                ]
            )
            statement = statement.on_conflict_do_update(
                index_elements=["company_id", "bar_time", "provider", "interval"],
                set_={"close": statement.excluded.close, "adj_close": statement.excluded.adj_close},
            )
            session.execute(statement)
            session.execute(statement)
            session.commit()

            assert session.query(func.count(PriceBar.id)).scalar() == 1
    finally:
        try:
            Base.metadata.drop_all(bind=engine)
        finally:
            with base_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            base_engine.dispose()
