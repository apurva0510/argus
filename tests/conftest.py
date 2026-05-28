from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from argus.core import models  # noqa: F401
from argus.core.db import Base, create_database_engine


@pytest.fixture
def sqlite_engine(tmp_path) -> Iterator[Engine]:
    db_path = tmp_path / "argus_test.db"
    engine = create_database_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(sqlite_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(
        bind=sqlite_engine,
        autocommit=False,
        autoflush=False,
        class_=Session,
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
