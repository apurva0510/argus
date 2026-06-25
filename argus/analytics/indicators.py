from __future__ import annotations

from datetime import timedelta
import numpy as np
import pandas as pd


def compute_return(series: pd.Series, periods: int) -> pd.Series:
    return series.pct_change(periods=periods)


def compute_ytd_return(series: pd.Series) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError("Series index must be a DatetimeIndex for YTD computation.")

    result = pd.Series(index=series.index, dtype="float64")
    years = pd.Index(series.index.year).unique()
    for year in years:
        current_year_mask = series.index.year == year
        prior_prices = series[series.index.year < year]
        if prior_prices.empty:
            base_price = series[current_year_mask].iloc[0]
        else:
            base_price = prior_prices.iloc[-1]
        result.loc[current_year_mask] = (series[current_year_mask] / base_price) - 1.0
    return result


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)

    avg_gain = gains.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = losses.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # When no losses exist in the window, RSI should be 100.
    rsi = rsi.where(~((avg_loss == 0.0) & (avg_gain > 0.0)), 100.0)
    # When no gains exist in the window, RSI should be 0. A flat window is neutral.
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss > 0.0)), 0.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    return rsi


def rolling_high(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).max()


def rolling_low(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).min()


def drawdown_from_rolling_high(series: pd.Series, window: int) -> pd.Series:
    high = rolling_high(series, window=window)
    return (series / high) - 1.0


def distance_from_ma(series: pd.Series, ma_series: pd.Series) -> pd.Series:
    return (series / ma_series) - 1.0


def annualized_volatility(
    series: pd.Series, window: int = 20, periods_per_year: int = 252
) -> pd.Series:
    returns = series.pct_change()
    return returns.rolling(window=window, min_periods=window).std() * np.sqrt(periods_per_year)


def calculate_power_signal(price_df: pd.DataFrame, demand_df: pd.DataFrame) -> float | None:
    """Compute power signal from EIA electricity price and demand data.

    Returns the average YoY change of monthly retail price and 7-day average demand.
    Returns None if sufficient EIA data is unavailable.
    """
    if price_df.empty or demand_df.empty:
        return None

    # Compute price YoY
    latest_price_row = price_df.iloc[-1]
    latest_price_date = latest_price_row["observation_date"]
    latest_price_val = latest_price_row["value"]

    prior_price_df = price_df[
        (price_df["observation_date"] >= latest_price_date - timedelta(days=380))
        & (price_df["observation_date"] <= latest_price_date - timedelta(days=340))
    ]
    if prior_price_df.empty:
        return None

    prior_price_df = prior_price_df.copy()
    prior_price_df["diff"] = (
        prior_price_df["observation_date"] - (latest_price_date - timedelta(days=365))
    ).abs()
    prior_price_val = prior_price_df.sort_values("diff").iloc[0]["value"]
    if prior_price_val == 0:
        return None
    price_yoy = (latest_price_val / prior_price_val) - 1.0

    # Compute demand YoY using 7-day average to smooth day-of-week fluctuations
    latest_demand_row = demand_df.iloc[-1]
    latest_demand_date = latest_demand_row["observation_date"]

    latest_demand_7d = demand_df[
        (demand_df["observation_date"] >= latest_demand_date - timedelta(days=6))
        & (demand_df["observation_date"] <= latest_demand_date)
    ]
    if len(latest_demand_7d) < 5:
        return None
    latest_demand_val = latest_demand_7d["value"].mean()

    prior_demand_date = latest_demand_date - timedelta(days=365)
    prior_demand_7d = demand_df[
        (demand_df["observation_date"] >= prior_demand_date - timedelta(days=6))
        & (demand_df["observation_date"] <= prior_demand_date)
    ]
    if len(prior_demand_7d) < 5:
        return None
    prior_demand_val = prior_demand_7d["value"].mean()
    if prior_demand_val == 0:
        return None
    demand_yoy = (latest_demand_val / prior_demand_val) - 1.0

    return float((price_yoy + demand_yoy) / 2.0)
