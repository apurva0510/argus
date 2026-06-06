import importlib
import pandas as pd
import pytest


def test_watchlist_renders_tickers_as_links_with_config(monkeypatch) -> None:
    import streamlit as st
    import app.components.sidebar
    import argus.services.watchlist_service

    captured_args = {}

    class MockSt:
        class column_config:
            @staticmethod
            def NumberColumn(label, **kwargs):
                return {"type": "number", "label": label, **kwargs}

            @staticmethod
            def SelectboxColumn(label, **kwargs):
                return {"type": "selectbox", "label": label, **kwargs}

            @staticmethod
            def TextColumn(label, **kwargs):
                return {"type": "text", "label": label, **kwargs}

            @staticmethod
            def LinkColumn(label, **kwargs):
                return {"type": "link", "label": label, **kwargs}

        @staticmethod
        def columns(layout):
            class MockCol:
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
            return [MockCol(), MockCol(), MockCol()]

        @staticmethod
        def selectbox(label, *args, **kwargs):
            return "All"

        @staticmethod
        def multiselect(label, *args, **kwargs):
            return []

        @staticmethod
        def button(label, **kwargs):
            return False

        @staticmethod
        def info(msg):
            pass

        @staticmethod
        def title(msg):
            pass

        @staticmethod
        def data_editor(df, **kwargs):
            captured_args["df"] = df
            captured_args["column_config"] = kwargs.get("column_config")
            return df

    # Mock modules/functions BEFORE importing the page
    monkeypatch.setattr(st, "session_state", {"auth_token": "test-token-123"})
    monkeypatch.setattr(app.components.sidebar, "render_sidebar_navigation", lambda: None)
    monkeypatch.setattr(
        argus.services.watchlist_service,
        "load_watchlist_table",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "watchlist_item_id": 1,
                    "ticker": "AAPL",
                    "company": "Apple Inc.",
                    "theme": "Mobile",
                    "watch_status": "watch",
                    "price": 150.0,
                    "return_1d": 0.01,
                    "return_1w": 0.02,
                    "return_1m": 0.03,
                    "return_3m": 0.04,
                    "return_ytd": 0.05,
                    "drawdown_52w": -0.1,
                    "high_52w": 180.0,
                    "ma_50": 145.0,
                    "ma_200": 140.0,
                    "rsi_14": 55.0,
                    "notes": "Good stock",
                }
            ]
        ),
    )

    # Monkeypatch streamlit functions globally so import-time execution uses mock
    for attr in dir(MockSt):
        if not attr.startswith("__"):
            monkeypatch.setattr(st, attr, getattr(MockSt, attr))

    # Now import the module safely
    watchlist_module = importlib.import_module("app.pages.2_Watchlists")

    # Clear cached function
    watchlist_module.load_watchlist_data.clear()

    # Call render again under captured_args context
    captured_args.clear()
    watchlist_module.render_watchlists()

    # Verify captured args
    assert "df" in captured_args
    df_out = captured_args["df"]
    if hasattr(df_out, "data"):
        df_out = df_out.data
    assert df_out.iloc[0]["ticker"] == "/Company_Detail?ticker=AAPL&auth=test-token-123"

    assert "column_config" in captured_args
    cfg = captured_args["column_config"]
    assert cfg["ticker"]["type"] == "link"
    assert cfg["ticker"]["disabled"] is True
    assert cfg["ticker"]["display_text"] == r"ticker=([^&]+)"
