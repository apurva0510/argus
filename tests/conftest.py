from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from argus.core import models  # noqa: F401
from argus.core.db import Base, create_database_engine


@pytest.fixture(autouse=True)
def force_test_settings(monkeypatch) -> None:
    """Force settings to standard test defaults so local .env config doesn't pollute/break tests."""
    from argus.core.settings import settings
    monkeypatch.setattr(settings, "market_data_provider", "yfinance")
    monkeypatch.setattr(settings, "finnhub_api_key", "")
    monkeypatch.setattr(settings, "twelve_data_api_key", "")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", "")
    monkeypatch.setattr(settings, "app_password", "")


@pytest.fixture
def sqlite_engine(tmp_path, monkeypatch) -> Iterator[Engine]:
    db_path = tmp_path / "argus_test.db"
    engine = create_database_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)

    from argus.core import db as db_module
    factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        class_=Session,
    )
    monkeypatch.setattr(db_module, "SessionLocal", factory)

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
