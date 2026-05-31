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


def test_intraday_workflow_writes_to_github_output_env() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "intraday-prices.yml").read_text(
        encoding="utf-8"
    )

    assert 'os.environ["GITHUB_OUTPUT"]' in workflow
    assert 'open("$GITHUB_OUTPUT"' not in workflow
    assert "python scripts/backfill_prices.py --period 5d --interval 15m" in workflow


def test_scheduled_workflows_validate_database_url_secret() -> None:
    for workflow_name in (
        "daily-refresh.yml",
        "filings-refresh.yml",
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
