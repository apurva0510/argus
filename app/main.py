import streamlit as st
from app.components.sidebar import render_sidebar_navigation

st.set_page_config(page_title="Argus", page_icon="📊", layout="wide")
render_sidebar_navigation()

st.title("Argus")
st.caption("Local-first AI infrastructure stock research app for two users.")

st.info(
    "Use the sidebar to open Dashboard, Watchlists, Company Detail, Pullback Finder, "
    "and News/Filings/Alerts."
)
