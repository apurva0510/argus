import sys
from pathlib import Path

# Add project root to sys.path to allow absolute imports of 'app' and 'argus'
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import streamlit as st

st.set_page_config(page_title="Argus", page_icon="📊", layout="wide")

navigation = st.navigation(
    [
        st.Page("pages/1_Dashboard.py", title="Dashboard"),
        st.Page("pages/2_Watchlists.py", title="Watchlists"),
        st.Page("pages/3_Company_Detail.py", title="Company Detail"),
        st.Page("pages/4_Pullback_Finder.py", title="Pullback Finder"),
        st.Page("pages/5_News_Filings_Alerts.py", title="News Filings Alerts"),
    ]
)

navigation.run()

