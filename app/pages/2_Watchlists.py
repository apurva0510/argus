from __future__ import annotations

import pandas as pd
import streamlit as st

from argus.core.db import create_database_engine

from argus.core.seed import WATCH_STATUSES
from argus.core.settings import settings
from argus.services.watchlist_service import load_watchlist_table, normalize_note_value, update_watchlist_items


@st.cache_resource
def get_watchlist_engine():
    return create_database_engine(settings.database_url)


@st.cache_data(ttl=300)
def load_watchlist_data(
    theme: str | None,
    ticker_query: str,
    watch_statuses: tuple[str, ...],
) -> pd.DataFrame:
    return load_watchlist_table(
        get_watchlist_engine(),
        theme=theme,
        ticker_query=ticker_query,
        watch_statuses=list(watch_statuses) if watch_statuses else None,
    )


def _fmt_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:+.2f}%"


def render_watchlists() -> None:
    st.title("Watchlists")

    theme_options_df = load_watchlist_table(get_watchlist_engine())
    theme_options = sorted(theme_options_df["theme"].dropna().unique().tolist()) if not theme_options_df.empty else []

    top1, top2, top3 = st.columns([2, 2, 3])
    with top1:
        selected_theme = st.selectbox("Theme", ["All"] + theme_options)
    with top2:
        selected_statuses = st.multiselect(
            "Watch Status",
            sorted(WATCH_STATUSES),
            default=sorted(WATCH_STATUSES),
        )
    with top3:
        ticker_query = st.text_input("Ticker Filter", placeholder="e.g., NVDA")

    if st.button("Refresh table"):
        load_watchlist_data.clear()
        st.rerun()

    df = load_watchlist_data(
        None if selected_theme == "All" else selected_theme,
        ticker_query,
        tuple(selected_statuses),
    )
    if df.empty:
        st.info("No watchlist rows match the current filters.")
        return

    editor_df = df.copy()
    editor_df["price"] = editor_df["price"].round(2)
    editor_df["1D %"] = editor_df["return_1d"].apply(_fmt_pct)
    editor_df["1W %"] = editor_df["return_1w"].apply(_fmt_pct)
    editor_df["1M %"] = editor_df["return_1m"].apply(_fmt_pct)
    editor_df["3M %"] = editor_df["return_3m"].apply(_fmt_pct)
    editor_df["YTD %"] = editor_df["return_ytd"].apply(_fmt_pct)
    editor_df["drawdown from 52W high"] = editor_df["drawdown_52w"].apply(_fmt_pct)
    editor_df["52W high"] = editor_df["high_52w"].round(2)
    editor_df["50DMA"] = editor_df["ma_50"].round(2)
    editor_df["200DMA"] = editor_df["ma_200"].round(2)
    editor_df["RSI 14"] = editor_df["rsi_14"].round(1)

    editor_df = editor_df[
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

    editable = st.data_editor(
        editor_df,
        hide_index=True,
        width="stretch",
        column_config={
            "watchlist_item_id": st.column_config.NumberColumn("id", disabled=True),
            "watch_status": st.column_config.SelectboxColumn(
                "watch_status",
                options=sorted(WATCH_STATUSES),
                required=True,
            ),
            "notes": st.column_config.TextColumn("notes"),
            "ticker": st.column_config.TextColumn("ticker", disabled=True),
            "company": st.column_config.TextColumn("company", disabled=True),
            "theme": st.column_config.TextColumn("theme", disabled=True),
            "price": st.column_config.NumberColumn("price", disabled=True),
            "1D %": st.column_config.TextColumn("1D %", disabled=True),
            "1W %": st.column_config.TextColumn("1W %", disabled=True),
            "1M %": st.column_config.TextColumn("1M %", disabled=True),
            "3M %": st.column_config.TextColumn("3M %", disabled=True),
            "YTD %": st.column_config.TextColumn("YTD %", disabled=True),
            "52W high": st.column_config.NumberColumn("52W high", disabled=True),
            "drawdown from 52W high": st.column_config.TextColumn("drawdown from 52W high", disabled=True),
            "50DMA": st.column_config.NumberColumn("50DMA", disabled=True),
            "200DMA": st.column_config.NumberColumn("200DMA", disabled=True),
            "RSI 14": st.column_config.NumberColumn("RSI 14", disabled=True),
        },
        key="watchlists_editor",
    )

    if st.button("Save edits", type="primary"):
        updates = []
        original_by_id = {int(row["watchlist_item_id"]): row for _, row in editor_df.iterrows()}
        for _, row in editable.iterrows():
            item_id = int(row["watchlist_item_id"])
            new_status = str(row["watch_status"]).strip()
            new_notes = normalize_note_value(row["notes"])
            original = original_by_id[item_id]
            original_notes = normalize_note_value(original["notes"])
            if new_status != str(original["watch_status"]) or new_notes != original_notes:
                updates.append(
                    {
                        "watchlist_item_id": item_id,
                        "watch_status": new_status,
                        "notes": new_notes,
                    }
                )

        if not updates:
            st.info("No changes detected.")
            return

        updated_count, errors = update_watchlist_items(updates)
        if errors:
            for err in errors:
                st.error(err)
        if updated_count > 0:
            st.success(f"Saved {updated_count} row(s).")
            load_watchlist_data.clear()
            st.rerun()


render_watchlists()
