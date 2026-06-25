from contextlib import contextmanager
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from argus.core.settings import settings


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str):
    # Normalize postgres URLs to use the modern psycopg driver with SQLAlchemy
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    # Supabase uses PgBouncer in transaction-pooling mode which does not
    # support prepared statements or SQLAlchemy connection pooling. Use
    # NullPool for Postgres to avoid persistent pooled DB connections.
    connect_args: dict = {}
    engine_kwargs: dict = {"future": True}
    if database_url.startswith("postgresql"):
        connect_args["prepare_threshold"] = None
        # disable pooling when using a transaction pooler like PgBouncer
        engine_kwargs["poolclass"] = NullPool
    elif database_url.startswith("sqlite"):
        connect_args["timeout"] = 30.0

    database_engine = create_engine(database_url, connect_args=connect_args, **engine_kwargs)
    event.listen(database_engine, "connect", _enable_sqlite_foreign_keys)
    return database_engine


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


class _EngineProxy:
    """Lazy proxy for SQLAlchemy Engine that defers creation until first use.

    This avoids creating an Engine at import time (which may capture a default
    SQLite URL) before Streamlit secrets or environment variables are applied.
    """

    def __init__(self):
        self._engine = None
        self._database_url = None

    def _ensure(self):
        if self._engine is None or self._database_url != settings.database_url:
            if self._engine is not None:
                self._engine.dispose()
            self._engine = create_database_engine(settings.database_url)
            self._database_url = settings.database_url
        return self._engine

    def __getattr__(self, item):
        return getattr(self._ensure(), item)

    def dispose(self):
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._database_url = None


# Module-level proxy to preserve the public `engine` symbol while deferring
# actual Engine creation until first use.
engine = _EngineProxy()

_default_session_factory = sessionmaker(autocommit=False, autoflush=False, class_=Session)
SessionLocal = _default_session_factory


def get_engine():
    """Return the concrete SQLAlchemy Engine behind the module-level proxy."""
    return engine._ensure()


@contextmanager
def session_scope():
    if SessionLocal is _default_session_factory:
        session = SessionLocal(bind=get_engine())
    else:
        session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_insert_statement_producer(session):
    """Dynamically resolve the SQLAlchemy insert function depending on database dialect.

    Supports both SQLite and PostgreSQL bulk/idempotent upserts.
    """
    try:
        dialect_name = session.bind.dialect.name
    except Exception:
        try:
            dialect_name = get_engine().dialect.name
        except Exception:
            dialect_name = "sqlite"

    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        return insert
    else:
        from sqlalchemy.dialects.sqlite import insert

        return insert


def safe_execute_query(session_or_conn, query: str, params: dict | None = None) -> list[dict]:
    """Execute a raw SQL query, convert rows to dicts, and coerce SQLite date strings to native objects.

    Compatible with both Session objects and Connection objects.
    """
    from sqlalchemy import text
    from datetime import date, datetime

    result = session_or_conn.execute(text(query), params or {})
    rows = result.mappings().all()

    coerced_rows = []
    for row in rows:
        row_dict = dict(row)
        for k, v in row_dict.items():
            if isinstance(v, str):
                k_lower = k.lower()
                if any(x in k_lower for x in ("date", "time", "_at", "as_of")):
                    if " " in v or "T" in v:
                        try:
                            row_dict[k] = datetime.fromisoformat(v)
                            continue
                        except ValueError:
                            pass
                    try:
                        clean_date = v.split(" ")[0].split("T")[0]
                        row_dict[k] = date.fromisoformat(clean_date)
                    except ValueError:
                        pass
        coerced_rows.append(row_dict)
    return coerced_rows
