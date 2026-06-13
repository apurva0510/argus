from __future__ import annotations

import streamlit as st
from sqlalchemy.engine import Engine

from argus.core.app_engine import create_migrated_database_engine
from argus.core.settings import settings


@st.cache_resource
def get_app_engine(database_url: str) -> Engine:
    return create_migrated_database_engine(database_url)


def get_configured_app_engine() -> Engine:
    return get_app_engine(settings.database_url)
