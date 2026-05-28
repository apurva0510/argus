import pytest
from sqlalchemy.orm import Session, sessionmaker

from argus.core import db as db_module
from argus.core.models import Company


@pytest.fixture
def patched_session_scope(sqlite_engine, monkeypatch) -> None:
    factory = sessionmaker(
        bind=sqlite_engine,
        autocommit=False,
        autoflush=False,
        class_=Session,
    )
    monkeypatch.setattr(db_module, "SessionLocal", factory)


def test_session_scope_commits_successful_work(sqlite_engine, patched_session_scope) -> None:
    with db_module.session_scope() as session:
        session.add(Company(symbol="OK", name="Committed Co"))

    with Session(sqlite_engine) as session:
        assert session.query(Company).filter_by(symbol="OK").one().name == "Committed Co"


def test_session_scope_rolls_back_failed_work(sqlite_engine, patched_session_scope) -> None:
    with pytest.raises(RuntimeError, match="force rollback"):
        with db_module.session_scope() as session:
            session.add(Company(symbol="NOPE", name="Rolled Back Co"))
            session.flush()
            raise RuntimeError("force rollback")

    with Session(sqlite_engine) as session:
        assert session.query(Company).filter_by(symbol="NOPE").one_or_none() is None
