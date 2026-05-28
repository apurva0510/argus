import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

st.set_page_config(page_title="AI Infra Watcher", page_icon="📊", layout="wide")

st.title("AI Infra Watcher")
st.caption("Local-first AI infrastructure stock research dashboard")

st.info("Use the sidebar to open Dashboard, Watchlists, Company Detail, Pullback Finder, and News/Filings/Alerts.")
