from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.database import get_configured_app_engine
from app.components.sidebar import render_sidebar_navigation
from app.components.watchlist_table import (
    RETURN_COLUMNS,
    prepare_watchlist_editor_df,
    watchlist_column_config,
)

from argus.core.seed import WATCH_STATUSES
from argus.services.watchlist_service import (
    load_watchlist_table,
    normalize_note_value,
    update_watchlist_items,
)
from app.components.tables import style_positive_green_negative_red


@st.cache_resource
def get_watchlist_engine():
    return get_configured_app_engine()


@st.cache_data(ttl=300)
def load_watchlist_data(
    theme: str | None,
    tickers: tuple[str, ...],
    watch_statuses: tuple[str, ...],
) -> pd.DataFrame:
    df = load_watchlist_table(
        get_watchlist_engine(),
        theme=theme,
        ticker_query=None,
        watch_statuses=list(watch_statuses) if watch_statuses else None,
    )
    if tickers:
        df = df[df["ticker"].isin(tickers)]
    return df


def render_watchlists() -> None:
    render_sidebar_navigation()
    st.title("Watchlists")

    all_options_df = load_watchlist_table(get_watchlist_engine())

    top1, top2, top3 = st.columns([2, 2, 3])
    with top2:
        selected_statuses = st.multiselect(
            "Watch Status",
            sorted(WATCH_STATUSES),
            default=sorted(WATCH_STATUSES),
            key="watchlist_status_filter",
        )

    selected_ticker_state = st.session_state.get("watchlist_ticker_filter", [])
    theme_options_df = all_options_df.copy()
    if selected_statuses:
        theme_options_df = theme_options_df[
            theme_options_df["watch_status"].isin(selected_statuses)
        ]
    if selected_ticker_state:
        theme_options_df = theme_options_df[theme_options_df["ticker"].isin(selected_ticker_state)]
    theme_options = (
        sorted(theme_options_df["theme"].dropna().unique().tolist())
        if not theme_options_df.empty
        else []
    )
    if st.session_state.get("watchlist_theme_filter") not in [None, "All", *theme_options]:
        st.session_state.watchlist_theme_filter = "All"

    with top1:
        selected_theme = st.selectbox(
            "Theme",
            ["All"] + theme_options,
            key="watchlist_theme_filter",
        )

    ticker_options_df = all_options_df.copy()
    if selected_theme != "All":
        ticker_options_df = ticker_options_df[ticker_options_df["theme"] == selected_theme]
    if selected_statuses:
        ticker_options_df = ticker_options_df[
            ticker_options_df["watch_status"].isin(selected_statuses)
        ]
    ticker_options = (
        sorted(ticker_options_df["ticker"].dropna().unique().tolist())
        if not ticker_options_df.empty
        else []
    )
    if selected_ticker_state:
        st.session_state.watchlist_ticker_filter = [
            ticker for ticker in selected_ticker_state if ticker in ticker_options
        ]
    with top3:
        selected_tickers = st.multiselect(
            "Ticker Filter",
            options=ticker_options,
            placeholder="Select tickers...",
            key="watchlist_ticker_filter",
        )

    if st.button("Refresh table"):
        load_watchlist_data.clear()
        st.rerun()

    df = load_watchlist_data(
        None if selected_theme == "All" else selected_theme,
        tuple(selected_tickers),
        tuple(selected_statuses),
    )
    if df.empty:
        st.info("No watchlist rows match the current filters.")
        return

    editor_df = prepare_watchlist_editor_df(df)

    styled_editor_df = editor_df.style.map(
        style_positive_green_negative_red,
        subset=RETURN_COLUMNS,
    )

    editable = st.data_editor(
        styled_editor_df,
        hide_index=True,
        width="stretch",
        column_config=watchlist_column_config(st),
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
            # Clear relevant Streamlit cache
            load_watchlist_data.clear()
            st.cache_data.clear()
            # Rerun the app
            st.rerun()


render_watchlists()
