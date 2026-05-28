import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

st.title("News, Filings, and Alerts")
st.info("News ingestion, SEC filings, and alert management UI will be implemented in later phases.")
