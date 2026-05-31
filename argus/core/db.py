from contextlib import contextmanager
import sqlite3

from sqlalchemy import create_engine, event
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
    # support prepared statements.  Disable them for PostgreSQL connections.
    connect_args: dict = {}
    if database_url.startswith("postgresql"):
        connect_args["prepare_threshold"] = None

    database_engine = create_engine(database_url, future=True, connect_args=connect_args)
    event.listen(database_engine, "connect", _enable_sqlite_foreign_keys)
    return database_engine


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class _EngineProxy:
    """Lazy proxy for SQLAlchemy Engine that defers creation until first use.

    This avoids creating an Engine at import time (which may capture a default
    SQLite URL) before Streamlit secrets or environment variables are applied.
    """

    def __init__(self):
        self._engine = None

    def _ensure(self):
        if self._engine is None:
            self._engine = create_database_engine(settings.database_url)

    def __getattr__(self, item):
        self._ensure()
        return getattr(self._engine, item)

    def dispose(self):
        if self._engine is not None:
            return self._engine.dispose()


# Module-level proxy to preserve the public `engine` symbol while deferring
# actual Engine creation until first use.
engine = _EngineProxy()

# SessionLocal is created with the proxy engine; SQLAlchemy will call the
# necessary engine methods on the proxy which will cause the real engine to
# be instantiated if needed.
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


@contextmanager
def session_scope():
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
            dialect_name = engine.dialect.name
        except Exception:
            dialect_name = "sqlite"

    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        return insert
    else:
        from sqlalchemy.dialects.sqlite import insert
        return insert
