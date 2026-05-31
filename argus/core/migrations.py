from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from argus.core import models  # noqa: F401
from argus.core.db import Base
from argus.core.models import AppSetting


CURRENT_SCHEMA_VERSION = "2"
SCHEMA_VERSION_KEY = "schema_version"


def run_migrations(database_engine: Engine) -> None:
    """Apply the current lightweight schema baseline.

    The app is still small enough to avoid a full migration framework, but hosted
    Postgres needs an explicit version marker so future schema changes have a
    safe upgrade path instead of relying on create_all alone.
    """
    Base.metadata.create_all(bind=database_engine)
    _migrate_price_bars_bar_time(database_engine)
    with Session(database_engine) as session:
        schema_version = (
            session.query(AppSetting)
            .filter(AppSetting.key == SCHEMA_VERSION_KEY)
            .one_or_none()
        )
        if schema_version is None:
            schema_version = AppSetting(key=SCHEMA_VERSION_KEY, value=CURRENT_SCHEMA_VERSION)
            session.add(schema_version)
        else:
            schema_version.value = CURRENT_SCHEMA_VERSION
        session.commit()


def _migrate_price_bars_bar_time(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    if "price_bars" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("price_bars")}
    if "bar_time" in columns:
        return

    if database_engine.dialect.name == "sqlite":
        _migrate_sqlite_price_bars(database_engine)
    elif database_engine.dialect.name == "postgresql":
        _migrate_postgres_price_bars(database_engine)


def _migrate_sqlite_price_bars(database_engine: Engine) -> None:
    with database_engine.begin() as conn:
        old_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(price_bars)")).fetchall()
        }
        optional_expression = {
            "open": "open" if "open" in old_columns else "NULL",
            "high": "high" if "high" in old_columns else "NULL",
            "low": "low" if "low" in old_columns else "NULL",
            "volume": "volume" if "volume" in old_columns else "NULL",
        }
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("ALTER TABLE price_bars RENAME TO price_bars_old"))
        Base.metadata.tables["price_bars"].create(bind=conn)
        conn.execute(
            text(
                f"""
                INSERT INTO price_bars (
                    id, company_id, date, bar_time, open, high, low, close, adj_close,
                    volume, provider, interval, created_at
                )
                SELECT
                    id, company_id, date, datetime(date || ' 00:00:00'),
                    {optional_expression["open"]},
                    {optional_expression["high"]},
                    {optional_expression["low"]},
                    close, adj_close,
                    {optional_expression["volume"]},
                    provider, interval, created_at
                FROM price_bars_old
                """
            )
        )
        conn.execute(text("DROP TABLE price_bars_old"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _migrate_postgres_price_bars(database_engine: Engine) -> None:
    with database_engine.begin() as conn:
        conn.execute(text("ALTER TABLE price_bars ADD COLUMN IF NOT EXISTS bar_time TIMESTAMP"))
        conn.execute(text("UPDATE price_bars SET bar_time = date::timestamp WHERE bar_time IS NULL"))
        conn.execute(text("ALTER TABLE price_bars ALTER COLUMN bar_time SET NOT NULL"))
        conn.execute(text("ALTER TABLE price_bars DROP CONSTRAINT IF EXISTS uq_price_bars"))
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_price_bars
                ON price_bars (company_id, bar_time, provider, interval)
                """
            )
        )
