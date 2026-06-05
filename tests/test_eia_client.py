from __future__ import annotations


def test_eia_not_available_without_key(monkeypatch) -> None:
    from argus.core.settings import settings
    from argus.sources.eia_client import is_eia_available, fetch_eia_series

    monkeypatch.setattr(settings, "eia_api_key", "")
    assert is_eia_available() is False

    result = fetch_eia_series("electricity/retail-sales")
    assert result.empty


def test_eia_available_with_key(monkeypatch) -> None:
    from argus.core.settings import settings
    from argus.sources.eia_client import is_eia_available

    monkeypatch.setattr(settings, "eia_api_key", "test-key-123")
    assert is_eia_available() is True


def test_fetch_eia_series_success(monkeypatch) -> None:
    import httpx
    from argus.core.settings import settings
    from argus.sources.eia_client import fetch_eia_series

    monkeypatch.setattr(settings, "eia_api_key", "test-key-123")

    mock_response_data = {
        "response": {
            "data": [
                {"period": "2025-01-01", "price": 12.5},
                {"period": "2025-02-01", "price": 13.0},
            ]
        }
    }

    recorded_params = []

    def mock_get(self, url, *, params=None, **kwargs):
        recorded_params.append(params)
        return httpx.Response(200, json=mock_response_data, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    result = fetch_eia_series(
        "electricity/retail-sales",
        facets={"sectorid": ["ALL"], "stateid": ["US"]},
        data_column="price",
    )

    assert not result.empty
    assert len(result) == 2
    assert result.iloc[0]["value"] == 12.5
    assert result.iloc[1]["value"] == 13.0
    assert recorded_params[0]["facets[sectorid][]"] == ["ALL"]
    assert recorded_params[0]["facets[stateid][]"] == ["US"]
    assert recorded_params[0]["data[]"] == "price"


def test_fetch_eia_series_retries_and_raises(monkeypatch) -> None:
    import httpx
    from argus.core.settings import settings
    from argus.sources.eia_client import fetch_eia_series

    monkeypatch.setattr(settings, "eia_api_key", "test-key-123")

    attempts = 0

    def mock_get(self, url, *, params=None, **kwargs):
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    
    import time
    monkeypatch.setattr(time, "sleep", lambda x: None)

    import pytest
    with pytest.raises(httpx.HTTPError):
        fetch_eia_series("electricity/retail-sales")

    assert attempts == 3

