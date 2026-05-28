import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_infra_watcher.core.db import session_scope
from ai_infra_watcher.core.models import Company, WatchlistItem

st.title("Watchlists")

with session_scope() as session:
    rows = (
        session.query(
            Company.symbol,
            Company.name,
            Company.sector,
            WatchlistItem.watch_status,
            WatchlistItem.notes,
        )
        .join(WatchlistItem, WatchlistItem.company_id == Company.id)
        .order_by(Company.sector, Company.symbol)
        .all()
    )

df = pd.DataFrame(rows, columns=["Ticker", "Company", "Sector", "Watch Status", "Notes"])
st.dataframe(df, width="stretch", hide_index=True)
st.caption("Editable watchlist controls will be added in a later phase.")
