"""Dated, next-open outcomes for a narrowly defined pullback setup."""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ("drawdown_52w", "rsi_14", "distance_from_200dma",
            "relative_return_vs_qqq_3m", "volatility_20d")


def build_pullback_events(
    bars: pd.DataFrame, metrics: pd.DataFrame, *, horizon: int = 60, spacing: int = 60,
    pullback_only: bool = True, breakdown_threshold: float = -0.15,
) -> pd.DataFrame:
    """Sample pullbacks and label the next-open to future-close path.

    A healthy recovery beats QQQ by 5 percentage points at the horizon without
    closing 15% below the adjusted entry price on an intervening session.
    """
    if horizon < 1 or spacing < 1 or not -1 < breakdown_threshold < 0:
        raise ValueError("horizon/spacing must be positive and breakdown_threshold between -1 and 0")
    prices = bars.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["company_id", "date"]).drop_duplicates(
        ["company_id", "date"]
    )
    prices["session_index"] = prices.groupby("company_id").cumcount()
    prices["adjusted_open"] = prices["open"] * prices["adj_close"] / prices["close"]
    group = prices.groupby("company_id", sort=False)
    prices["entry_open"] = group["adjusted_open"].shift(-1)
    prices["entry_date"] = group["date"].shift(-1)
    prices["exit_close"] = group["adj_close"].shift(-horizon)
    prices["exit_date"] = group["date"].shift(-horizon)
    prices["future_min_close"] = group["adj_close"].transform(
        lambda series: series.shift(-1).iloc[::-1].rolling(horizon, min_periods=horizon)
        .min().iloc[::-1]
    )
    benchmark = prices.loc[prices["symbol"] == "QQQ", [
        "date", "entry_date", "entry_open", "exit_date", "exit_close"
    ]].rename(columns={"entry_date": "qqq_entry_date", "entry_open": "qqq_entry_open",
                       "exit_date": "qqq_exit_date", "exit_close": "qqq_exit_close"})
    if benchmark.empty:
        raise ValueError("QQQ price history is required")
    prices = prices.merge(benchmark, on="date", how="inner", validate="many_to_one")
    metric_frame = metrics.copy()
    metric_frame["date"] = pd.to_datetime(metric_frame["date"])
    events = prices.merge(metric_frame, on=["company_id", "date"], how="inner",
                          validate="one_to_one")
    events = events.loc[
        (~events["is_benchmark"])
        & ((events["drawdown_52w"].between(-0.25, -0.10)
            & (events["distance_from_200dma"] >= 0)) if pullback_only else True)
        & events["rsi_14"].notna()
        & (events["entry_date"] == events["qqq_entry_date"])
        & (events["exit_date"] == events["qqq_exit_date"])
        & (events["entry_open"] > 0)
        & (events["qqq_entry_open"] > 0)
    ].copy()
    events = events.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["exit_close", "future_min_close", "qqq_exit_close", *FEATURES]
    )
    # Select episodes using only event dates, never their subsequent outcomes.
    selected = []
    for _, company in events.groupby("company_id"):
        last_index = -spacing
        for row in company.sort_values("session_index").itertuples():
            if row.session_index - last_index >= spacing:
                selected.append(row.Index)
                last_index = row.session_index
    events = events.loc[selected].copy()
    events["company_return"] = events["exit_close"] / events["entry_open"] - 1
    events["qqq_return"] = events["qqq_exit_close"] / events["qqq_entry_open"] - 1
    events["excess_return"] = events["company_return"] - events["qqq_return"]
    events["worst_close_return"] = events["future_min_close"] / events["entry_open"] - 1
    events["breakdown"] = (events["worst_close_return"] <= breakdown_threshold).astype(int)
    events["healthy_recovery"] = (
        (events["excess_return"] >= 0.05) & (events["breakdown"] == 0)
    ).astype(int)
    return events.sort_values(["date", "symbol"]).reset_index(drop=True)
