from __future__ import annotations

from sqlalchemy.engine import Engine

from argus.core.db import create_database_engine
from argus.core.migrations import run_migrations


def create_migrated_database_engine(database_url: str) -> Engine:
    engine = create_database_engine(database_url)
    run_migrations(engine)
    return engine
