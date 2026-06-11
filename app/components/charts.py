from __future__ import annotations

import pandas as pd


def apply_intraday_xaxis(fig, df_or_interval, tf: str | None = None) -> None:
    """Apply stable category-axis ticks for intraday 1D/5D charts."""
    # Support old signature: apply_intraday_xaxis(fig, interval)
    if tf is None:
        if df_or_interval == "15m":
            fig.update_xaxes(type="category")
        return

    if tf not in ("1D", "5D"):
        return

    df = df_or_interval
    if df.empty:
        return

    dates_ny = pd.to_datetime(df["date"])
    tick_value_column = "date_label" if "date_label" in df.columns else "date"

    tickvals = []
    ticktext = []

    if tf == "1D":
        one_day_ticks = {"09:30", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"}
        for i, dt in enumerate(dates_ny):
            if dt.strftime("%H:%M") in one_day_ticks:
                tickvals.append(df.iloc[i][tick_value_column])
                ticktext.append(dt.strftime("%I:%M %p").lstrip("0"))
    elif tf == "5D":
        last_date = None
        for i, dt in enumerate(dates_ny):
            day_str = dt.strftime("%b %d")
            if last_date != day_str:
                tickvals.append(df.iloc[i][tick_value_column])
                ticktext.append(day_str)
                last_date = day_str

    if tickvals:
        fig.update_xaxes(
            type="category",
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            tickangle=0,
        )
