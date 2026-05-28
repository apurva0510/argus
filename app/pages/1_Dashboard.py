import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_infra_watcher.services.dashboard_service import get_dashboard_overview

st.title("Dashboard")

overview = get_dashboard_overview()

col1, col2, col3 = st.columns(3)
col1.metric("Tracked Companies", overview["tracked_companies"])
col2.metric("High Priority", overview["high_priority_count"])
col3.metric("Owned", overview["owned_count"])

st.subheader("Data Health")
st.write("Price bars:", overview["price_bar_count"])
st.write("Metrics rows:", overview["metrics_count"])
st.write("News items:", overview["news_count"])
st.write("SEC filings:", overview["filings_count"])

st.info("Live data pipelines will populate market and catalyst sections in later phases.")
