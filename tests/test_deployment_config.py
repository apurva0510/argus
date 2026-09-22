from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from argus.core import models  # noqa: F401
from argus.core.db import Base, create_database_engine, get_insert_statement_producer
from argus.core.models import Company, PriceBar


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_intraday_workflow_refreshes_prices_without_recomputing_daily_metrics() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "intraday-prices.yml").read_text(
        encoding="utf-8"
    )

    assert 'cron: "7,37 13-21 * * 1-5"' in workflow
    assert 'ZoneInfo("America/New_York")' in workflow
    assert "start = time(9, 30)" in workflow
    assert "end = time(16, 0)" in workflow
    assert 'os.environ["GITHUB_OUTPUT"]' in workflow
    assert 'open("$GITHUB_OUTPUT"' not in workflow
    assert "python scripts/backfill_prices.py --period 5d --interval 15m" in workflow
    assert "python scripts/compute_metrics.py" not in workflow
    assert "python scripts/refresh_index.py" in workflow
    assert workflow.index("python scripts/refresh_index.py") < workflow.index(
        "python scripts/run_alerts.py"
    )


def test_daily_close_workflow_runs_after_close_even_when_actions_starts_late() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "daily-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert 'cron: "47 22 * * 1-5"' in workflow
    assert "daily_close_window" not in workflow
    assert "if:" not in workflow
    assert "python scripts/run_daily_refresh.py --period 2y --skip-news --skip-filings" in workflow


def test_daily_refresh_orchestrator_includes_refresh_index() -> None:
    from argus.pipelines.run_daily_refresh import build_daily_refresh_steps

    names = [name for name, _ in build_daily_refresh_steps()]
    assert names.index("compute_opportunity_scores") < names.index("refresh_index")
    assert names.index("refresh_index") < names.index("run_alerts")


def test_filings_workflow_syncs_ciks_before_refreshing_filings() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "filings-refresh.yml").read_text(
        encoding="utf-8"
    )

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

    assert 'cron: "0 */2 * * *"' in workflow
    assert "Determine if news refresh window" not in workflow
    assert "steps.news_refresh_window.outputs.run_job" not in workflow
    assert "python scripts/refresh_news.py --bypass-refresh-throttle" in workflow
    assert "python scripts/compute_signals.py" in workflow
    assert "python scripts/generate_theses.py" in workflow
    assert workflow.index("python scripts/refresh_news.py") < workflow.index(
        "python scripts/compute_signals.py"
    )
    assert workflow.index("python scripts/compute_signals.py") < workflow.index(
        "python scripts/generate_theses.py"
    )
    assert workflow.index("python scripts/generate_theses.py") < workflow.index(
        "python scripts/run_alerts.py"
    )
    assert "--force" not in workflow


def test_ir_feeds_workflow_runs_every_6_hours() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ir-feeds-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert 'cron: "22 */6 * * *"' in workflow
    assert "Determine if IR refresh window" not in workflow
    assert "steps.ir_refresh_window.outputs.run_job" not in workflow
    assert "python scripts/refresh_ir_feeds.py" in workflow
    assert "python scripts/refresh_capex.py" not in workflow
    assert "python scripts/compute_signals.py" in workflow
    assert "python scripts/generate_theses.py" in workflow
    assert workflow.index("python scripts/refresh_ir_feeds.py") < workflow.index(
        "python scripts/compute_signals.py"
    )
    assert workflow.index("python scripts/compute_signals.py") < workflow.index(
        "python scripts/generate_theses.py"
    )
    assert workflow.index("python scripts/generate_theses.py") < workflow.index(
        "python scripts/run_alerts.py"
    )
    assert "--force" not in workflow


@pytest.mark.parametrize("status, exits", [("partial_success", False), ("failed", True)])
def test_daily_refresh_cli_exit_status(monkeypatch, capsys, status, exits) -> None:
    from argparse import Namespace
    from scripts import run_daily_refresh as cli

    monkeypatch.setattr(cli, "parse_args", lambda: Namespace(period="2y", skip_news=False, skip_filings=False, skip_alerts=False, skip_macro=False))
    monkeypatch.setattr(cli, "get_engine", lambda: object())
    monkeypatch.setattr(cli, "run_migrations", lambda _engine: None)
    monkeypatch.setattr(cli, "run_daily_refresh", lambda **_kwargs: {
        "status": status, "rows_read": 0, "rows_written": 0,
        "results": {}, "error_text": "provider unavailable",
    })

    if exits:
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
    else:
        cli.main()
    assert "Warning: provider unavailable" in capsys.readouterr().out


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
        assert "DATABASE_URL secret is required" in workflow
        assert "APP_AUTH_SECRET: ${{ secrets.APP_AUTH_SECRET }}" in workflow


def test_readme_does_not_reference_manual_rls_script() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "scripts/enable_rls.py" not in readme


def test_catalyst_workflows_regenerate_theses_before_alerts() -> None:
    for workflow_name, refresh_command in (
        ("news-refresh.yml", "python scripts/refresh_news.py --bypass-refresh-throttle"),
        ("filings-refresh.yml", "python scripts/refresh_filings.py"),
        ("ir-feeds-refresh.yml", "python scripts/refresh_ir_feeds.py"),
    ):
        workflow = (PROJECT_ROOT / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )

        assert "python scripts/generate_theses.py" in workflow
        assert workflow.index(refresh_command) < workflow.index("python scripts/generate_theses.py")
        assert workflow.index("python scripts/generate_theses.py") < workflow.index(
            "python scripts/run_alerts.py"
        )


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
