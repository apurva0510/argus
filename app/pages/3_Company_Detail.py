import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_infra_watcher.services.company_service import get_company_options

st.title("Company Detail")

options = get_company_options()
if not options:
    st.warning("No companies found. Run database initialization and seed scripts.")
    st.stop()

selected = st.selectbox("Ticker", options)
st.subheader(selected)
st.info("Detailed charts, relative performance, fundamentals, filings, and notes will be added in later phases.")
