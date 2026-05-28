from sqlalchemy import create_engine, inspect

from ai_infra_watcher.core.db import Base
from ai_infra_watcher.core import models  # noqa: F401


def test_phase1_required_tables_create() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    table_names = set(inspect(engine).get_table_names())
    required_tables = {
        "companies",
        "themes",
        "company_theme_exposure",
        "watchlists",
        "watchlist_items",
        "price_bars",
        "daily_metrics",
        "fundamentals_snapshot",
        "news_items",
        "news_mentions",
        "sec_filings",
        "earnings_events",
        "alerts",
        "alert_events",
        "user_notes",
        "job_runs",
        "app_settings",
    }
    assert required_tables.issubset(table_names)
