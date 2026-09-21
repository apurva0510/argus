"""Offline, point-in-time technical dataset for predictive-signal experiments."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.core.models import Company, DailyMetric, PriceBar
from argus.core.settings import settings

HORIZON = 20
FEATURES = (
    "return_1w",
    "return_1m",
    "return_3m",
    "rsi_14",
    "drawdown_52w",
    "distance_from_50dma",
    "distance_from_200dma",
    "relative_return_vs_qqq_1m",
    "relative_return_vs_qqq_3m",
    "volatility_20d",
)


def load_history(session: Session) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read historical bars and metrics without mutating the configured database."""
    companies = pd.DataFrame(session.execute(select(Company.id, Company.symbol, Company.is_benchmark)).all(),
                             columns=["company_id", "symbol", "is_benchmark"])
    if companies.empty or "QQQ" not in set(companies["symbol"]):
        raise ValueError("QQQ benchmark is required")
    bars = pd.DataFrame(
        session.execute(
            select(PriceBar.company_id, PriceBar.date, PriceBar.open,
                   PriceBar.close, PriceBar.adj_close)
            .where(PriceBar.interval == "1d", PriceBar.provider == settings.market_data_provider)
        ).all(), columns=["company_id", "date", "open", "close", "adj_close"]
    )
    metric_columns = [DailyMetric.company_id, DailyMetric.date, *[getattr(DailyMetric, x) for x in FEATURES]]
    metrics = pd.DataFrame(session.execute(select(*metric_columns)).all(),
                           columns=["company_id", "date", *FEATURES])
    return bars.merge(companies, on="company_id"), metrics


def build_dataset(bars: pd.DataFrame, metrics: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    """Label company closes against QQQ over the next `horizon` benchmark sessions.

    Features are dated at the signal close. The outcome begins at that close and is
    for research evaluation, not an executable next-session return estimate.
    """
    if horizon < 1:
        raise ValueError("horizon must be positive")
    prices = bars.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["company_id", "date"])
    prices = prices.drop_duplicates(["company_id", "date"])
    qqq = prices.loc[prices["symbol"] == "QQQ", ["date", "adj_close"]].copy()
    if qqq.empty:
        raise ValueError("QQQ price history is required")
    qqq = qqq.rename(columns={"adj_close": "qqq_close"}).sort_values("date")
    qqq["qqq_return_1m"] = qqq["qqq_close"].pct_change(21)
    qqq["qqq_return_3m"] = qqq["qqq_close"].pct_change(63)
    qqq["qqq_volatility_20d"] = qqq["qqq_close"].pct_change().rolling(20).std()
    qqq["qqq_future"] = qqq["qqq_close"].shift(-horizon)
    qqq["label_end"] = qqq["date"].shift(-horizon)
    prices = prices.merge(qqq, on="date", how="inner", validate="many_to_one")
    prices["future_close"] = prices.groupby("company_id")["adj_close"].shift(-horizon)
    prices["company_end"] = prices.groupby("company_id")["date"].shift(-horizon)
    # A company missing sessions would otherwise be compared against a shorter QQQ window.
    prices = prices.loc[prices["company_end"] == prices["label_end"]].copy()
    prices = prices.loc[(prices["adj_close"] > 0) & (prices["qqq_close"] > 0)]
    prices["excess_return_20d"] = (
        prices["future_close"] / prices["adj_close"]
        - prices["qqq_future"] / prices["qqq_close"]
    )
    prices["outperformed_qqq"] = (prices["excess_return_20d"] > 0).astype(int)
    feature_frame = metrics.copy()
    feature_frame["date"] = pd.to_datetime(feature_frame["date"])
    result = prices.merge(feature_frame, on=["company_id", "date"], how="inner",
                          validate="one_to_one")
    result = result.loc[~result["is_benchmark"] & (result["symbol"] != "QQQ")]
    result = result.replace([np.inf, -np.inf], np.nan)
    result = result.dropna(subset=["excess_return_20d", "rsi_14", "drawdown_52w",
                                   "relative_return_vs_qqq_3m"])
    for feature in ("drawdown_52w", "relative_return_vs_qqq_3m", "rsi_14"):
        result[f"{feature}_daily_rank"] = result.groupby("date")[feature].rank(pct=True)
    return result.sort_values(["date", "symbol"]).reset_index(drop=True)


def chronological_split(data: pd.DataFrame, test_fraction: float = 0.25) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out the newest dates; train labels must mature before test begins."""
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between zero and one")
    dates = sorted(data["date"].unique())
    if len(dates) < 80:
        raise ValueError("At least 80 signal dates are required")
    first_test = dates[int(len(dates) * (1 - test_fraction))]
    train = data.loc[data["label_end"] < first_test].copy()
    test = data.loc[data["date"] >= first_test].copy()
    if train.empty or test.empty:
        raise ValueError("Insufficient rows after outcome embargo")
    return train, test
