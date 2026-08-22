from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from argus.core import models  # noqa: F401
from argus.core.db import Base
from argus.core.models import AppSetting, IndexDefinition, IndexValue


CURRENT_SCHEMA_VERSION = "12"
SCHEMA_VERSION_KEY = "schema_version"


def run_migrations(database_engine: Engine) -> None:
    """Apply the current lightweight schema baseline.

    The app is still small enough to avoid a full migration framework, but hosted
    Postgres needs an explicit version marker so future schema changes have a
    safe upgrade path instead of relying on create_all alone.
    """
    _migrate_macro_tables_for_foreign_key(database_engine)
    _migrate_capex_observations_source_column(database_engine)
    _migrate_news_items_sentiment_explanation(database_engine)
    _migrate_catalyst_events_source_key(database_engine)
    Base.metadata.create_all(bind=database_engine)
    _backfill_news_items_sentiment_explanations(database_engine)
    _migrate_price_bars_bar_time(database_engine)
    _migrate_index_values_for_definitions(database_engine)
    _ensure_default_index_definition(database_engine)
    with Session(database_engine) as session:
        schema_version = (
            session.query(AppSetting).filter(AppSetting.key == SCHEMA_VERSION_KEY).one_or_none()
        )
        if schema_version is None:
            schema_version = AppSetting(key=SCHEMA_VERSION_KEY, value=CURRENT_SCHEMA_VERSION)
            session.add(schema_version)
        else:
            schema_version.value = CURRENT_SCHEMA_VERSION
        session.commit()


def _migrate_macro_tables_for_foreign_key(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    table_names = inspector.get_table_names()
    if "app_settings" not in table_names:
        return

    version = None
    with Session(database_engine) as session:
        schema_version = (
            session.query(AppSetting).filter(AppSetting.key == SCHEMA_VERSION_KEY).one_or_none()
        )
        if schema_version:
            version = schema_version.value

    if version is not None:
        try:
            v_num = int(version)
        except ValueError:
            v_num = 0

        if v_num < 5:
            with database_engine.begin() as conn:
                if "macro_observations" in table_names:
                    conn.execute(text("DROP TABLE macro_observations"))
                if "macro_series" in table_names:
                    conn.execute(text("DROP TABLE macro_series"))


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
            row[1] for row in conn.execute(text("PRAGMA table_info(price_bars)")).fetchall()
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
        conn.execute(
            text("UPDATE price_bars SET bar_time = date::timestamp WHERE bar_time IS NULL")
        )
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


def _migrate_index_values_for_definitions(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    if "index_values" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("index_values")}
    if "index_definition_id" in columns:
        return

    if database_engine.dialect.name == "sqlite":
        _migrate_sqlite_index_values(database_engine)
    elif database_engine.dialect.name == "postgresql":
        _migrate_postgres_index_values(database_engine)


def _migrate_sqlite_index_values(database_engine: Engine) -> None:
    with database_engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("ALTER TABLE index_values RENAME TO index_values_old"))
        Base.metadata.tables["index_values"].create(bind=conn)
        conn.execute(
            text(
                """
                INSERT INTO index_values (
                    id, index_definition_id, date, index_value, created_at
                )
                SELECT
                    id, NULL, date, index_value, created_at
                FROM index_values_old
                """
            )
        )
        conn.execute(text("DROP TABLE index_values_old"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _migrate_postgres_index_values(database_engine: Engine) -> None:
    with database_engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE index_values ADD COLUMN IF NOT EXISTS index_definition_id INTEGER")
        )
        conn.execute(
            text(
                "ALTER TABLE index_values ADD CONSTRAINT fk_index_values_definition_id FOREIGN KEY (index_definition_id) REFERENCES index_definitions (id) ON DELETE CASCADE"
            )
        )
        conn.execute(
            text("ALTER TABLE index_values DROP CONSTRAINT IF EXISTS uq_index_values_date")
        )
        conn.execute(text("ALTER TABLE index_values DROP CONSTRAINT IF EXISTS uq_index_values"))
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_index_values
                ON index_values (index_definition_id, date)
                """
            )
        )


def _ensure_default_index_definition(database_engine: Engine) -> None:
    from argus.analytics.index_builder import (
        DEFAULT_INDEX_NAME,
        INDEX_MODE_EQUAL,
        LEGACY_DEFAULT_INDEX_NAME,
    )

    with Session(database_engine) as session:
        definition = (
            session.query(IndexDefinition)
            .filter(IndexDefinition.name == DEFAULT_INDEX_NAME)
            .one_or_none()
        )
        if definition is None:
            definition = (
                session.query(IndexDefinition)
                .filter(IndexDefinition.name == LEGACY_DEFAULT_INDEX_NAME)
                .one_or_none()
            )
            if definition is not None:
                definition.name = DEFAULT_INDEX_NAME
        if definition is None:
            definition = IndexDefinition(
                name=DEFAULT_INDEX_NAME,
                mode=INDEX_MODE_EQUAL,
                base_value=100.0,
                is_active=True,
            )
            session.add(definition)
            session.flush()
        session.query(IndexValue).filter(IndexValue.index_definition_id.is_(None)).update(
            {IndexValue.index_definition_id: definition.id},
            synchronize_session=False,
        )
        session.commit()


def _migrate_capex_observations_source_column(database_engine: Engine) -> None:
    """Add source column to capex_observations for schema version 7."""
    inspector = inspect(database_engine)
    if "capex_observations" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("capex_observations")}
    if "source" in columns:
        return

    with database_engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE capex_observations ADD COLUMN source VARCHAR(64) NOT NULL DEFAULT 'manual'"
            )
        )


def _migrate_news_items_sentiment_explanation(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    if "news_items" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("news_items")}
    if "sentiment_explanation" in columns:
        return

    with database_engine.begin() as conn:
        conn.execute(text("ALTER TABLE news_items ADD COLUMN sentiment_explanation TEXT"))


def _migrate_catalyst_events_source_key(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    if "catalyst_events" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("catalyst_events")}
    if "source_key" not in columns and database_engine.dialect.name == "sqlite":
        has_snapshots = "catalyst_impact_snapshots" in inspector.get_table_names()
        with database_engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            if has_snapshots:
                conn.execute(
                    text("ALTER TABLE catalyst_impact_snapshots RENAME TO catalyst_impact_snapshots_old")
                )
            conn.execute(text("ALTER TABLE catalyst_events RENAME TO catalyst_events_old"))
            conn.execute(text("DROP INDEX IF EXISTS ix_catalyst_events_company_id"))
            conn.execute(text("DROP INDEX IF EXISTS ix_catalyst_events_date"))
            if has_snapshots:
                conn.execute(text("DROP INDEX IF EXISTS ix_catalyst_impact_snapshots_catalyst_event_id"))
            Base.metadata.tables["catalyst_events"].create(bind=conn)
            conn.execute(
                text(
                    """
                    INSERT INTO catalyst_events (
                        id, company_id, event_type, date, details, created_at, source_key
                    )
                    SELECT
                        id,
                        company_id,
                        event_type,
                        date,
                        details,
                        created_at,
                        event_type || ':' || CAST(date AS VARCHAR)
                    FROM catalyst_events_old
                    """
                )
            )
            if has_snapshots:
                Base.metadata.tables["catalyst_impact_snapshots"].create(bind=conn)
                conn.execute(
                    text(
                        """
                        INSERT INTO catalyst_impact_snapshots (
                            id,
                            catalyst_event_id,
                            return_m1_to_event,
                            return_event_to_p1,
                            return_p1_to_p5,
                            return_p1_to_p20,
                            max_drawdown_p20,
                            created_at
                        )
                        SELECT
                            id,
                            catalyst_event_id,
                            return_m1_to_event,
                            return_event_to_p1,
                            return_p1_to_p5,
                            return_p1_to_p20,
                            max_drawdown_p20,
                            created_at
                        FROM catalyst_impact_snapshots_old
                        """
                    )
                )
                conn.execute(text("DROP TABLE catalyst_impact_snapshots_old"))
            conn.execute(text("DROP TABLE catalyst_events_old"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
    elif "source_key" not in columns:
        with database_engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE catalyst_events ADD COLUMN source_key VARCHAR(128) NOT NULL DEFAULT ''")
            )
            conn.execute(
                text(
                    """
                    UPDATE catalyst_events
                    SET source_key = event_type || ':' || CAST(date AS VARCHAR)
                    WHERE source_key = ''
                    """
                )
            )

    if database_engine.dialect.name == "postgresql":
        inspector = inspect(database_engine)
        has_target_unique_key = _has_catalyst_unique_key(inspector)

        # This migration used to drop/recreate the index on every script startup.
        # Only change the schema when the required unique key is actually absent.
        if not has_target_unique_key:
            with database_engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE catalyst_events DROP CONSTRAINT IF EXISTS uq_catalyst_events")
                )
                conn.execute(
                    text(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS uq_catalyst_events
                        ON catalyst_events (company_id, event_type, source_key)
                        """
                    )
                )


def _has_catalyst_unique_key(inspector) -> bool:
    """Return whether catalyst identity is already enforced by a unique key."""
    target_columns = {"company_id", "event_type", "source_key"}
    return any(
        set(constraint.get("column_names") or []) == target_columns
        for constraint in inspector.get_unique_constraints("catalyst_events")
    ) or any(
        index.get("unique")
        and set(index.get("column_names") or []) == target_columns
        for index in inspector.get_indexes("catalyst_events")
    )


def _backfill_news_items_sentiment_explanations(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    if "news_items" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("news_items")}
    if "sentiment_explanation" not in columns:
        return

    from argus.pipelines.news_items import backfill_news_sentiment_explanations

    with Session(database_engine) as session:
        backfill_news_sentiment_explanations(session)
        session.commit()
