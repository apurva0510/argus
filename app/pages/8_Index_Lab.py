from __future__ import annotations


import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy.orm import sessionmaker

from app.auth_links import company_detail_url
from app.components.sidebar import render_sidebar_navigation
from app.components.tables import style_positive_green_negative_red
from argus.analytics.index_builder import (
    INDEX_MODE_EQUAL,
    INDEX_MODE_EXPOSURE,
    INDEX_MODE_MANUAL,
)
from argus.services.index_service import (
    get_index_options,
    get_index_preview_data,
    get_candidate_weights_data,
    save_index_definition_from_editor,
)
from argus.core.app_engine import create_migrated_database_engine
from argus.core.settings import settings
from argus.core.timezones import format_et_datetime


@st.cache_resource
def get_index_lab_engine():
    return create_migrated_database_engine(settings.database_url)


@st.cache_data(ttl=300)
def load_index_options() -> list[dict[str, object]]:
    engine = get_index_lab_engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        return get_index_options(session)


@st.cache_data(ttl=300)
def load_index_preview(index_definition_id: int, timeframe: str) -> dict[str, object]:
    engine = get_index_lab_engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        return get_index_preview_data(session, index_definition_id, timeframe)


@st.cache_data(ttl=300)
def load_candidate_weights() -> pd.DataFrame:
    engine = get_index_lab_engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        return get_candidate_weights_data(session)


def _mode_label(mode: str) -> str:
    return {
        INDEX_MODE_EQUAL: "Equal weight",
        INDEX_MODE_EXPOSURE: "Theme exposure weight",
        INDEX_MODE_MANUAL: "Manual weight",
    }.get(mode, mode)


def _ticker_link_column_config() -> dict[str, object]:
    return {"Ticker": st.column_config.LinkColumn("Ticker", display_text=r"ticker=([^&]+)")}


def _link_ticker_series(series: pd.Series) -> pd.Series:
    return series.apply(lambda ticker: company_detail_url(ticker) if ticker else "")


def _render_performance_chart(rel_df: pd.DataFrame, title: str) -> None:
    if rel_df.empty:
        st.info("No index performance history available yet. Run `python scripts/refresh_index.py`.")
        return

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=rel_df["date"],
            y=rel_df["index_level"],
            name=title,
            line=dict(color="#1f77b4", width=3),
        )
    )
    if "qqq_level" in rel_df:
        fig.add_trace(
            go.Scatter(
                x=rel_df["date"],
                y=rel_df["qqq_level"],
                name="QQQ (Benchmark)",
                line=dict(color="#2ca02c", width=1.5, dash="dot"),
            )
        )
    if "nvda_level" in rel_df:
        fig.add_trace(
            go.Scatter(
                x=rel_df["date"],
                y=rel_df["nvda_level"],
                name="NVDA (Benchmark)",
                line=dict(color="#9467bd", width=1.5, dash="dot"),
            )
        )
    fig.update_layout(
        title=f"{title} vs Benchmarks",
        xaxis_title="Date",
        yaxis_title="Normalized Level",
        template="plotly_white",
        margin=dict(l=40, r=40, t=40, b=40),
        height=380,
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")


def _render_weights(weights: pd.DataFrame) -> None:
    if weights.empty:
        st.info("No constituents are included in this index definition.")
        return
    view = weights.rename(
        columns={
            "symbol": "Ticker",
            "name": "Company",
            "sector": "Sector",
            "effective_weight": "Weight",
        }
    ).copy()
    view["Ticker"] = _link_ticker_series(view["Ticker"])
    view["Weight"] = view["Weight"].apply(lambda value: f"{value * 100:.2f}%")
    st.dataframe(
        view[["Ticker", "Company", "Sector", "Weight"]],
        hide_index=True,
        width="stretch",
        column_config=_ticker_link_column_config(),
    )


def _render_contributors(contributors: pd.DataFrame) -> None:
    if contributors.empty:
        st.info("No contribution data available for the selected period.")
        return
    view = contributors.rename(
        columns={"symbol": "Ticker", "name": "Company", "return": "Return", "contribution": "Contribution"}
    ).copy()
    view["Ticker"] = _link_ticker_series(view["Ticker"])
    view["Return"] = view["Return"].apply(lambda value: f"{value * 100:+.2f}%")
    view["Contribution"] = view["Contribution"].apply(lambda value: f"{value * 100:+.2f}%")
    styled = view[["Ticker", "Company", "Return", "Contribution"]].style.map(
        style_positive_green_negative_red,
        subset=["Return", "Contribution"],
    )
    st.dataframe(styled, hide_index=True, width="stretch", column_config=_ticker_link_column_config())


def _render_theme_concentration(themes: pd.DataFrame) -> None:
    if themes.empty:
        st.info("No theme exposure data is available for this definition.")
        return
    view = themes.rename(columns={"theme": "Theme", "weight": "Weight"}).copy()
    view["Weight"] = view["Weight"].apply(lambda value: f"{value * 100:.2f}%")
    st.dataframe(view[["Theme", "Weight"]], hide_index=True, width="stretch")


def _save_definition(name: str, mode: str, editor_df: pd.DataFrame) -> None:
    from sqlalchemy.exc import SQLAlchemyError
    try:
        engine = get_index_lab_engine()
        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as session:
            save_index_definition_from_editor(session, name=name, mode=mode, editor_df=editor_df)
            session.commit()
    except SQLAlchemyError as exc:
        raise ValueError(f"Database error while saving index definition: {exc}") from exc

    load_index_options.clear()
    load_index_preview.clear()


def render_index_lab() -> None:
    st.set_page_config(page_title="Argus - Index Lab", layout="wide")
    render_sidebar_navigation()
    st.title("Index Lab")

    options = load_index_options()
    if not options:
        st.warning("No index definitions found.")
        return

    selected_label = st.selectbox(
        "Index Definition",
        [f"{option['name']} ({_mode_label(str(option['mode']))})" for option in options],
        index=0,
    )
    selected_idx = [
        f"{option['name']} ({_mode_label(str(option['mode']))})" for option in options
    ].index(selected_label)
    selected = options[selected_idx]

    created_at = selected["created_at"]
    created_label = format_et_datetime(created_at, fmt="%Y-%m-%d %I:%M %p ET") if created_at else "n/a"

    def _index_card(label: str, primary: str, secondary: str = "") -> str:
        secondary_html = (
            f'<span class="ix-card-sub">{secondary}</span>' if secondary else ""
        )
        return f"""
        <div class="ix-card">
            <div class="ix-card-label">{label}</div>
            <div class="ix-card-value">
                <span class="ix-card-primary">{primary}</span>
                {secondary_html}
            </div>
        </div>
        """

    st.markdown(
        """
        <style>
        .ix-card-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin: 12px 0 20px 0;
        }
        .ix-card {
            background: linear-gradient(135deg, rgba(22,27,34,0.4) 0%, rgba(17,22,29,0.5) 100%);
            border: 1px solid rgba(240,246,252,0.1);
            border-radius: 10px;
            padding: 14px 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            transition: all 0.2s cubic-bezier(0.4,0,0.2,1);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .ix-card:hover {
            border-color: rgba(56,139,253,0.4);
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(56,139,253,0.1);
        }
        .ix-card-label {
            font-size: 11px;
            color: #8b949e;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin-bottom: 10px;
        }
        .ix-card-value {
            display: flex;
            align-items: baseline;
            flex-wrap: wrap;
            gap: 4px;
        }
        .ix-card-primary {
            font-size: 15px;
            font-weight: 600;
            color: #f0f6fc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        }
        .ix-card-sub {
            font-size: 12px;
            color: #8b949e;
            font-weight: 400;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        }
        @media (max-width: 768px) {
            .ix-card-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Split Created timestamp into date + time parts for the secondary sub-label
    if created_label and created_label != "n/a":
        created_parts = created_label.split(" ", 1)
        created_primary = created_parts[0]
        created_secondary = created_parts[1] if len(created_parts) > 1 else ""
    else:
        created_primary = "n/a"
        created_secondary = ""

    st.markdown(
        f"""
        <div class="ix-card-grid">
            {_index_card("Mode", _mode_label(str(selected["mode"])))}
            {_index_card("Base Value", f"{float(selected['base_value']):.1f}")}
            {_index_card("Created", created_primary, created_secondary)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    timeframe = st.radio(
        "Preview Timeframe",
        ["1M", "3M", "6M", "1Y", "All"],
        index=3,
        horizontal=True,
    )
    preview = load_index_preview(int(selected["id"]), timeframe)
    _render_performance_chart(preview["rel_df"], str(selected["name"]))

    weights_tab, contributors_tab, themes_tab, create_tab = st.tabs(
        ["Weights", "Contributors", "Theme Concentration", "Create Definition"]
    )
    with weights_tab:
        _render_weights(preview["weights"])
    with contributors_tab:
        _render_contributors(preview["contributors"])
    with themes_tab:
        _render_theme_concentration(preview["themes"])
    with create_tab:
        st.caption("Saved definitions are immutable. Changes create a new definition.")
        candidates = load_candidate_weights()
        if candidates.empty:
            st.info("No default AI Infra Core candidates found.")
            return

        mode_label = st.selectbox(
            "Mode",
            ["Equal weight", "Theme exposure weight", "Manual weight"],
            index=0,
            key="create_index_mode_selectbox",
        )
        mode = {
            "Equal weight": INDEX_MODE_EQUAL,
            "Theme exposure weight": INDEX_MODE_EXPOSURE,
            "Manual weight": INDEX_MODE_MANUAL,
        }[mode_label]

        if mode == INDEX_MODE_EQUAL:
            st.info(
                "Equal weight uses every included ticker at the same effective weight. "
                "The Weight % column is ignored."
            )
        elif mode == INDEX_MODE_EXPOSURE:
            st.info(
                "Theme exposure weight normalizes each included ticker's existing theme exposure scores. "
                "The Weight % column is ignored."
            )
        else:
            st.info("Manual weight uses the Weight % column and requires included weights to total 100%.")

        manual_mode = mode == INDEX_MODE_MANUAL
        disabled_columns = ["Ticker", "Company"] if manual_mode else ["Ticker", "Company", "Weight %"]

        with st.form("create_index_definition_form"):
            name = st.text_input("Definition Name", value="")
            editor_df = st.data_editor(
                candidates,
                hide_index=True,
                width="stretch",
                disabled=disabled_columns,
                column_config={
                    "Include": st.column_config.CheckboxColumn("Include"),
                    "Weight %": st.column_config.NumberColumn(
                        "Weight %",
                        min_value=0.0,
                        help="Only used for Manual weight definitions.",
                    ),
                },
            )
            if manual_mode:
                included_total = float(editor_df.loc[editor_df["Include"], "Weight %"].sum())
                st.caption(f"Included manual weight total: {included_total:.2f}%")
            submitted = st.form_submit_button("Save Definition")
            if submitted:
                try:
                    _save_definition(name, mode, editor_df)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success("Index definition saved.")
                    st.rerun()


if __name__ == "__main__":
    render_index_lab()
