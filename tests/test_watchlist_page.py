import pandas as pd

from app.components.watchlist_table import prepare_watchlist_editor_df, watchlist_column_config


def test_watchlist_editor_data_renders_tickers_as_links(monkeypatch) -> None:
    import streamlit as st

    monkeypatch.setattr(st, "session_state", {"auth_token": "test-token-123"})

    df_out = prepare_watchlist_editor_df(_sample_watchlist_df())

    assert df_out.iloc[0]["ticker"] == "/Company_Detail?ticker=AAPL&auth=test-token-123"
    assert df_out.iloc[0]["1D %"] == "+1.00%"
    assert df_out.iloc[0]["drawdown from 52W high"] == "-10.00%"


def test_watchlist_column_config_uses_link_column() -> None:
    cfg = watchlist_column_config(MockSt)

    assert cfg["ticker"]["type"] == "link"
    assert cfg["ticker"]["disabled"] is True
    assert cfg["ticker"]["display_text"] == r"ticker=([^&]+)"


def _sample_watchlist_df() -> pd.DataFrame:
    return pd.DataFrame(
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
    )


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
