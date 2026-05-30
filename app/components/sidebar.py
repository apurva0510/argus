import streamlit as st
from argus.services.company_service import get_company_options

def render_sidebar_navigation() -> None:
    symbols = get_company_options()
    if not symbols:
        return
    
    with st.sidebar:
        st.write("---")
        st.subheader("🔍 Quick Ticker Detail")
        options = ["Select..."] + symbols
        selected_ticker = st.selectbox(
            "Go to Company Detail:",
            options,
            index=0,
            key="sidebar_ticker_selectbox"
        )
        if selected_ticker != "Select...":
            st.session_state.selected_ticker = selected_ticker
            st.switch_page("pages/3_Company_Detail.py")
