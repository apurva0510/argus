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
