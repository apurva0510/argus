from __future__ import annotations

import streamlit as st

from argus.core.auth import append_auth_token_to_url


def company_detail_url(ticker: str) -> str:
    token = st.session_state.get("auth_token")
    return append_auth_token_to_url(f"/Company_Detail?ticker={ticker}", token)
