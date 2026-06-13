from __future__ import annotations

from app.components import database


def test_get_app_engine_uses_database_url_as_cache_key(monkeypatch) -> None:
    calls = []

    def fake_create_engine(database_url: str):
        calls.append(database_url)
        return {"database_url": database_url}

    database.get_app_engine.clear()
    monkeypatch.setattr(database, "create_migrated_database_engine", fake_create_engine)

    first = database.get_app_engine("sqlite:///one.db")
    second = database.get_app_engine("sqlite:///one.db")
    third = database.get_app_engine("sqlite:///two.db")

    assert first is second
    assert third == {"database_url": "sqlite:///two.db"}
    assert calls == ["sqlite:///one.db", "sqlite:///two.db"]


def test_get_configured_app_engine_uses_current_settings_url(monkeypatch) -> None:
    calls = []

    def fake_get_app_engine(database_url: str):
        calls.append(database_url)
        return {"database_url": database_url}

    monkeypatch.setattr(database.settings, "database_url", "sqlite:///configured.db")
    monkeypatch.setattr(database, "get_app_engine", fake_get_app_engine)

    assert database.get_configured_app_engine() == {"database_url": "sqlite:///configured.db"}
    assert calls == ["sqlite:///configured.db"]
