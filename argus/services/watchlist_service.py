from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from argus.core.db import session_scope
from argus.core.models import UserNote, WatchlistItem
from argus.core.seed import WATCH_STATUSES


def load_watchlist_table(
    engine: Engine,
    *,
    theme: str | None = None,
    ticker_query: str | None = None,
    watch_statuses: list[str] | None = None,
) -> pd.DataFrame:
    ticker_query = (ticker_query or "").strip()
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(
                """
                SELECT
                    wi.id AS watchlist_item_id,
                    c.symbol AS ticker,
                    c.name AS company,
                    w.name AS theme,
                    wi.watch_status AS watch_status,
                    pb.adj_close AS price,
                    dm.return_1d AS return_1d,
                    dm.return_1w AS return_1w,
                    dm.return_1m AS return_1m,
                    dm.return_3m AS return_3m,
                    dm.return_ytd AS return_ytd,
                    dm.high_52w AS high_52w,
                    dm.drawdown_52w AS drawdown_52w,
                    dm.ma_50 AS ma_50,
                    dm.ma_200 AS ma_200,
                    dm.rsi_14 AS rsi_14,
                    wi.notes AS notes
                FROM watchlist_items wi
                JOIN watchlists w ON w.id = wi.watchlist_id
                JOIN companies c ON c.id = wi.company_id
                LEFT JOIN price_bars pb ON pb.id = (
                    SELECT pb2.id
                    FROM price_bars pb2
                    WHERE pb2.company_id = c.id
                        AND pb2.provider = 'yfinance'
                        AND pb2.interval = '1d'
                    ORDER BY pb2.date DESC
                    LIMIT 1
                )
                LEFT JOIN daily_metrics dm ON dm.id = (
                    SELECT dm2.id
                    FROM daily_metrics dm2
                    WHERE dm2.company_id = c.id
                    ORDER BY dm2.date DESC
                    LIMIT 1
                )
                WHERE (:theme IS NULL OR w.name = :theme)
                    AND (:ticker_query = '' OR UPPER(c.symbol) LIKE '%' || UPPER(:ticker_query) || '%')
                ORDER BY w.name, c.symbol
                """
            ),
            conn,
            params={"theme": theme, "ticker_query": ticker_query},
        )

    if watch_statuses:
        df = df[df["watch_status"].isin(watch_statuses)]

    return df.reset_index(drop=True)


def update_watchlist_items(edits: list[dict[str, Any]]) -> tuple[int, list[str]]:
    if not edits:
        return 0, []

    parsed_edits: list[tuple[int, str, str]] = []
    errors = _validate_watchlist_edits(edits, parsed_edits)
    if errors:
        return 0, errors

    with session_scope() as session:
        items_by_id: dict[int, WatchlistItem] = {}
        for item_id, _, _ in parsed_edits:
            item = session.query(WatchlistItem).filter(WatchlistItem.id == item_id).one_or_none()
            if item is None:
                errors.append(f"Watchlist item {item_id} not found")
            else:
                items_by_id[item_id] = item

        if errors:
            return 0, errors

        updated = 0
        for item_id, new_status, new_notes in parsed_edits:
            item = items_by_id[item_id]
            changed = False
            if item.watch_status != new_status:
                # Synchronize watch status globally for this company
                company_items = (
                    session.query(WatchlistItem)
                    .filter(WatchlistItem.company_id == item.company_id)
                    .all()
                )
                for c_item in company_items:
                    c_item.watch_status = new_status
                changed = True
            if (item.notes or "") != new_notes:
                item.notes = new_notes

                # Append to user_notes table to preserve history
                if new_notes.strip():
                    user_note = UserNote(
                        company_id=item.company_id,
                        note_text=new_notes.strip(),
                        note_type="watchlist_update",
                        created_by="User"
                    )
                    session.add(user_note)
                changed = True

            if changed:
                updated += 1

    return updated, errors


def normalize_note_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _validate_watchlist_edits(
    edits: list[dict[str, Any]],
    parsed_edits: list[tuple[int, str, str]],
) -> list[str]:
    errors: list[str] = []
    seen_item_ids: set[int] = set()

    for edit in edits:
        try:
            item_id = int(edit["watchlist_item_id"])
        except (KeyError, TypeError, ValueError):
            errors.append("Invalid watchlist item id")
            continue

        if item_id in seen_item_ids:
            errors.append(f"Duplicate edit for watchlist item {item_id}")
            continue
        seen_item_ids.add(item_id)

        new_status = str(edit.get("watch_status", "")).strip()
        new_notes = normalize_note_value(edit.get("notes"))

        if new_status not in WATCH_STATUSES:
            errors.append(f"Invalid watch_status '{new_status}' for item {item_id}")
            continue

        parsed_edits.append((item_id, new_status, new_notes))

    return errors
