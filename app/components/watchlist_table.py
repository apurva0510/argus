from __future__ import annotations

from typing import Any

import pandas as pd

from app.auth_links import company_detail_url
from app.components.formatting import format_pct
from argus.core.seed import WATCH_STATUSES


RETURN_COLUMNS = ["1D %", "1W %", "1M %", "3M %", "YTD %", "drawdown from 52W high"]


def prepare_watchlist_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    editor_df = df.copy()
    editor_df["ticker"] = editor_df["ticker"].apply(lambda t: company_detail_url(t) if t else "")
    editor_df["price"] = editor_df["price"].round(2)
    editor_df["1D %"] = editor_df["return_1d"].apply(format_pct)
    editor_df["1W %"] = editor_df["return_1w"].apply(format_pct)
    editor_df["1M %"] = editor_df["return_1m"].apply(format_pct)
    editor_df["3M %"] = editor_df["return_3m"].apply(format_pct)
    editor_df["YTD %"] = editor_df["return_ytd"].apply(format_pct)
    editor_df["drawdown from 52W high"] = editor_df["drawdown_52w"].apply(format_pct)
    editor_df["52W high"] = editor_df["high_52w"].round(2)
    editor_df["50DMA"] = editor_df["ma_50"].round(2)
    editor_df["200DMA"] = editor_df["ma_200"].round(2)
    editor_df["RSI 14"] = editor_df["rsi_14"].round(1)

    return editor_df[
        [
            "watchlist_item_id",
            "ticker",
            "company",
            "theme",
            "watch_status",
            "price",
            "1D %",
            "1W %",
            "1M %",
            "3M %",
            "YTD %",
            "52W high",
            "drawdown from 52W high",
            "50DMA",
            "200DMA",
            "RSI 14",
            "notes",
        ]
    ]


def watchlist_column_config(st_module: Any) -> dict[str, Any]:
    return {
        "watchlist_item_id": st_module.column_config.NumberColumn("id", disabled=True),
        "watch_status": st_module.column_config.SelectboxColumn(
            "watch_status",
            options=sorted(WATCH_STATUSES),
            required=True,
        ),
        "notes": st_module.column_config.TextColumn("notes"),
        "ticker": st_module.column_config.LinkColumn(
            "ticker", disabled=True, display_text=r"ticker=([^&]+)"
        ),
        "company": st_module.column_config.TextColumn("company", disabled=True),
        "theme": st_module.column_config.TextColumn("theme", disabled=True),
        "price": st_module.column_config.NumberColumn("price", disabled=True, format="$%.2f"),
        "1D %": st_module.column_config.TextColumn("1D %", disabled=True),
        "1W %": st_module.column_config.TextColumn("1W %", disabled=True),
        "1M %": st_module.column_config.TextColumn("1M %", disabled=True),
        "3M %": st_module.column_config.TextColumn("3M %", disabled=True),
        "YTD %": st_module.column_config.TextColumn("YTD %", disabled=True),
        "52W high": st_module.column_config.NumberColumn(
            "52W high", disabled=True, format="$%.2f"
        ),
        "drawdown from 52W high": st_module.column_config.TextColumn(
            "drawdown from 52W high", disabled=True
        ),
        "50DMA": st_module.column_config.NumberColumn("50DMA", disabled=True, format="$%.2f"),
        "200DMA": st_module.column_config.NumberColumn("200DMA", disabled=True, format="$%.2f"),
        "RSI 14": st_module.column_config.NumberColumn("RSI 14", disabled=True, format="%.1f"),
    }
