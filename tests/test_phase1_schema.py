import importlib
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from argus.core import models  # noqa: F401
from argus.core.db import Base, create_database_engine
from argus.core.settings import Settings
from argus.core.models import (
    Alert,
    AlertEvent,
    AppSetting,
    Company,
    DailyMetric,
    PriceBar,
    Watchlist,
    WatchlistItem,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_TABLES = {
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
    "provider_health",
    "app_settings",
}


def test_package_modules_import_without_side_effects() -> None:
    module_names = [
        "argus",
        "argus.core.db",
        "argus.core.init_db",
        "argus.core.models",
        "argus.core.settings",
        "argus.analytics.indicators",
        "argus.alerts.rules",
    ]

    for module_name in module_names:
        assert importlib.import_module(module_name)


def test_sqlalchemy_metadata_contains_phase1_tables() -> None:
    assert REQUIRED_TABLES.issubset(Base.metadata.tables)
    assert Base.metadata.tables["companies"].c.symbol.unique is True
    assert Base.metadata.tables["price_bars"].c.company_id.foreign_keys
    assert Base.metadata.tables["daily_metrics"].c.company_id.foreign_keys
    assert Base.metadata.tables["alert_events"].c.dedupe_key.nullable is False


def test_settings_load_defaults_without_secrets(monkeypatch) -> None:
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    test_settings = Settings(_env_file=None)

    assert test_settings.app_password == ""
    assert test_settings.sec_user_agent == ""
    assert test_settings.database_url.startswith("sqlite:///")
    assert test_settings.database_url.endswith("data/app.db")


def test_phase1_required_tables_create(sqlite_engine) -> None:
    engine = sqlite_engine
    table_names = set(inspect(engine).get_table_names())
    assert REQUIRED_TABLES.issubset(table_names)


def test_initialize_database_creates_directories_and_tables(tmp_path, monkeypatch) -> None:
    from argus.core import init_db

    db_path = tmp_path / "initialized.db"
    data_dir = tmp_path / "data"
    test_engine = create_database_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(init_db, "DATA_DIR", data_dir)
    monkeypatch.setattr(init_db, "engine", test_engine)

    init_db.initialize_database()
    init_db.initialize_database()

    assert (data_dir / "raw").is_dir()
    assert (data_dir / "lake").is_dir()
    assert (data_dir / "exports").is_dir()
    assert REQUIRED_TABLES.issubset(set(inspect(test_engine).get_table_names()))
    with Session(test_engine) as session:
        schema_version = (
            session.query(AppSetting)
            .filter(AppSetting.key == "schema_version")
            .one()
        )
        assert schema_version.value == "3"
    test_engine.dispose()


def test_migration_adds_bar_time_to_existing_sqlite_price_bars(tmp_path) -> None:
    from sqlalchemy import text
    from argus.core.migrations import run_migrations

    db_path = tmp_path / "old_schema.db"
    test_engine = create_database_engine(f"sqlite:///{db_path}")
    with test_engine.begin() as conn:
        conn.execute(text("CREATE TABLE companies (id INTEGER PRIMARY KEY, symbol VARCHAR(16) NOT NULL UNIQUE, name VARCHAR(255) NOT NULL, is_active BOOLEAN NOT NULL DEFAULT 1, is_benchmark BOOLEAN NOT NULL DEFAULT 0, is_hyperscaler BOOLEAN NOT NULL DEFAULT 0, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        conn.execute(text("CREATE TABLE price_bars (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, date DATE NOT NULL, close FLOAT, adj_close FLOAT, provider VARCHAR(32) NOT NULL, interval VARCHAR(16) NOT NULL, created_at DATETIME NOT NULL, CONSTRAINT uq_price_bars UNIQUE (company_id, date, provider, interval), FOREIGN KEY(company_id) REFERENCES companies (id))"))
        conn.execute(text("INSERT INTO companies (id, symbol, name, is_active, is_benchmark, is_hyperscaler, created_at, updated_at) VALUES (1, 'NVDA', 'NVIDIA', 1, 0, 0, '2026-01-01', '2026-01-01')"))
        conn.execute(text("INSERT INTO price_bars (id, company_id, date, close, adj_close, provider, interval, created_at) VALUES (1, 1, '2026-01-02', 100.0, 100.0, 'yfinance', '1d', '2026-01-02')"))

    run_migrations(test_engine)

    inspector = inspect(test_engine)
    assert "bar_time" in {column["name"] for column in inspector.get_columns("price_bars")}
    with test_engine.connect() as conn:
        bar_time = conn.execute(text("SELECT bar_time FROM price_bars WHERE id = 1")).scalar_one()
        assert str(bar_time).startswith("2026-01-02")
    test_engine.dispose()


def test_scripts_init_db_creates_test_sqlite_database(tmp_path) -> None:
    db_path = tmp_path / "script_created.db"
    env = os.environ.copy()
    env.update(
        {
            "APP_PASSWORD": "",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "PYTHONPATH": str(PROJECT_ROOT),
            "SEC_USER_AGENT": "",
        }
    )

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "init_db.py")],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "Database initialized." in result.stdout
    assert db_path.exists()
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    assert REQUIRED_TABLES.issubset({name for (name,) in rows})


def test_phase1_unique_constraints_exist() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)

    expected_constraints = {
        "company_theme_exposure": {"uq_company_theme_exposure"},
        "watchlist_items": {"uq_watchlist_items"},
        "price_bars": {"uq_price_bars"},
        "daily_metrics": {"uq_daily_metrics"},
        "fundamentals_snapshot": {"uq_fundamentals_snapshot"},
        "news_mentions": {"uq_news_mentions"},
        "earnings_events": {"uq_earnings_events"},
        "alert_events": {"uq_alert_events_dedupe_key"},
    }

    for table_name, expected_names in expected_constraints.items():
        constraint_names = {
            constraint["name"] for constraint in inspector.get_unique_constraints(table_name)
        }
        assert expected_names.issubset(constraint_names)


def test_phase1_lookup_indexes_exist(sqlite_engine) -> None:
    inspector = inspect(sqlite_engine)
    expected_indexes = {
        "companies": {("symbol",)},
        "company_theme_exposure": {("company_id",), ("theme_id",)},
        "watchlist_items": {("watchlist_id",), ("company_id",)},
        "price_bars": {("company_id",), ("date",)},
        "daily_metrics": {("company_id",), ("date",)},
        "news_items": {("published_at",)},
        "news_mentions": {("news_id",), ("company_id",)},
        "sec_filings": {("company_id",), ("form",)},
        "earnings_events": {("company_id",), ("event_date",)},
        "alerts": {("company_id",), ("watchlist_id",)},
        "alert_events": {("alert_id",), ("company_id",)},
        "user_notes": {("company_id",)},
        "job_runs": {("job_name",)},
    }

    for table_name, expected_columns in expected_indexes.items():
        indexed_columns = {
            tuple(index["column_names"]) for index in inspector.get_indexes(table_name)
        }
        assert expected_columns.issubset(indexed_columns)


def test_phase1_required_columns_are_not_nullable(sqlite_engine) -> None:
    inspector = inspect(sqlite_engine)
    expected_non_nullable_columns = {
        "companies": {"symbol", "name", "is_active", "is_benchmark", "is_hyperscaler"},
        "themes": {"code", "name"},
        "company_theme_exposure": {"company_id", "theme_id", "exposure_score"},
        "watchlists": {"name", "is_system"},
        "watchlist_items": {"watchlist_id", "company_id", "watch_status"},
        "price_bars": {"company_id", "date", "bar_time", "provider", "interval"},
        "daily_metrics": {"company_id", "date"},
        "fundamentals_snapshot": {"company_id", "as_of_date", "provider"},
        "news_items": {"title", "url"},
        "news_mentions": {"news_id", "company_id", "is_primary_match"},
        "sec_filings": {"company_id", "accession_no", "form", "is_new"},
        "earnings_events": {"company_id", "event_date", "source"},
        "alerts": {"name", "rule_type", "channel", "is_enabled"},
        "alert_events": {"alert_id", "event_type", "dedupe_key"},
        "user_notes": {"company_id", "note_text"},
        "job_runs": {"job_name", "status"},
        "app_settings": {"key"},
    }

    for table_name, expected_columns in expected_non_nullable_columns.items():
        columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        nullable_columns = {
            column_name
            for column_name in expected_columns
            if columns[column_name]["nullable"]
        }
        assert nullable_columns == set()


def test_phase1_schema_keeps_required_column_contract(sqlite_engine) -> None:
    inspector = inspect(sqlite_engine)
    expected_columns = {
        "companies": {
            "id",
            "symbol",
            "name",
            "exchange",
            "sector",
            "industry",
            "country",
            "cik",
            "is_active",
            "is_benchmark",
            "is_hyperscaler",
            "created_at",
            "updated_at",
        },
        "price_bars": {
            "id",
            "company_id",
            "date",
            "bar_time",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
            "provider",
            "interval",
            "created_at",
        },
        "daily_metrics": {
            "id",
            "company_id",
            "date",
            "return_1d",
            "return_1w",
            "return_1m",
            "return_3m",
            "return_6m",
            "return_ytd",
            "ma_50",
            "ma_200",
            "rsi_14",
            "high_52w",
            "low_52w",
            "drawdown_52w",
            "distance_from_50dma",
            "distance_from_200dma",
            "relative_return_vs_qqq_1m",
            "relative_return_vs_qqq_3m",
            "relative_return_vs_nvda_1m",
            "relative_return_vs_nvda_3m",
            "volatility_20d",
            "opportunity_score",
            "created_at",
        },
        "alerts": {
            "id",
            "name",
            "rule_type",
            "company_id",
            "watchlist_id",
            "config_json",
            "channel",
            "destination",
            "is_enabled",
            "last_triggered_at",
            "created_at",
            "updated_at",
        },
        "alert_events": {
            "id",
            "alert_id",
            "triggered_at",
            "company_id",
            "event_type",
            "payload_json",
            "delivery_status",
            "dedupe_key",
            "created_at",
        },
        "watchlist_items": {
            "id",
            "watchlist_id",
            "company_id",
            "watch_status",
            "sort_order",
            "notes",
            "created_at",
            "updated_at",
        },
    }

    for table_name, required_columns in expected_columns.items():
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        assert required_columns.issubset(actual_columns)


def test_sqlite_foreign_keys_are_enforced() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1

    with Session(engine) as session:
        session.add(
            PriceBar(
                company_id=999,
                date=date(2026, 1, 1),
                close=100.0,
                adj_close=100.0,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_watchlist_items_are_unique_per_watchlist_and_company() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        company = Company(symbol="TST", name="Test Co")
        watchlist = Watchlist(name="Test Watchlist")
        session.add_all([company, watchlist])
        session.flush()
        session.add_all(
            [
                WatchlistItem(watchlist_id=watchlist.id, company_id=company.id),
                WatchlistItem(watchlist_id=watchlist.id, company_id=company.id),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_daily_metrics_are_unique_per_company_and_date() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        company = Company(symbol="TST", name="Test Co")
        session.add(company)
        session.flush()
        metric_date = date(2026, 1, 1)
        session.add_all(
            [
                DailyMetric(company_id=company.id, date=metric_date, return_1d=0.01),
                DailyMetric(company_id=company.id, date=metric_date, return_1d=0.02),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_alert_events_require_unique_dedupe_keys() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        alert = Alert(name="Test alert", rule_type="price_below")
        session.add(alert)
        session.flush()
        session.add(AlertEvent(alert_id=alert.id, event_type="price_below"))

        with pytest.raises(IntegrityError):
            session.commit()

    with Session(engine) as session:
        alert = Alert(name="Second alert", rule_type="price_below")
        session.add(alert)
        session.flush()
        session.add_all(
            [
                AlertEvent(alert_id=alert.id, event_type="price_below", dedupe_key="same-key"),
                AlertEvent(alert_id=alert.id, event_type="price_below", dedupe_key="same-key"),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()
