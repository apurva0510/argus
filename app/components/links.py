from __future__ import annotations

import pandas as pd
import streamlit as st

from app.auth_links import company_detail_url


def ticker_link_column_config(column_name: str = "Ticker") -> dict[str, object]:
    return {
        column_name: st.column_config.LinkColumn(
            column_name, display_text=r"ticker=([^&]+)"
        )
    }


def link_ticker_series(series: pd.Series) -> pd.Series:
    return series.apply(lambda ticker: company_detail_url(ticker) if ticker else "")


def ticker_markdown(ticker: str) -> str:
    return f"[{ticker}]({company_detail_url(ticker)})"
