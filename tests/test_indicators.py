from datetime import datetime

import pandas as pd
import pytest

from argus.analytics.indicators import (
    annualized_volatility,
    compute_return,
    compute_rsi,
    compute_ytd_return,
    distance_from_ma,
    drawdown_from_rolling_high,
    moving_average,
)
from argus.analytics.relative_strength import relative_return


def test_compute_return() -> None:
    series = pd.Series([100.0, 105.0, 110.25])
    returns = compute_return(series, periods=1)
    assert returns.iloc[1] == pytest.approx(0.05)
    assert returns.iloc[2] == pytest.approx(0.05)


def test_moving_average() -> None:
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    ma = moving_average(series, window=3)
    assert pd.isna(ma.iloc[1])
    assert ma.iloc[2] == 2.0
    assert ma.iloc[4] == 4.0


def test_rsi_range() -> None:
    prices = pd.Series(
        [100, 101, 100, 102, 103, 102, 104, 105, 104, 106, 107, 106, 108, 109, 110, 111]
    )
    rsi = compute_rsi(prices, window=14)
    latest = rsi.dropna().iloc[-1]
    assert 0 <= latest <= 100


def test_rsi_edge_cases() -> None:
    gains = pd.Series(range(1, 20), dtype="float64")
    losses = pd.Series(range(20, 1, -1), dtype="float64")
    flat = pd.Series([100.0] * 20)

    assert compute_rsi(gains, window=14).dropna().iloc[-1] == 100.0
    assert compute_rsi(losses, window=14).dropna().iloc[-1] == 0.0
    assert compute_rsi(flat, window=14).dropna().iloc[-1] == 50.0


def test_drawdown_from_rolling_high() -> None:
    series = pd.Series([100.0, 110.0, 105.0, 120.0, 90.0])
    drawdown = drawdown_from_rolling_high(series, window=3)
    assert drawdown.iloc[-1] == pytest.approx(-0.25)


def test_annualized_volatility_positive() -> None:
    prices = pd.Series([100 + i for i in range(40)])
    vol = annualized_volatility(prices, window=20)
    assert vol.dropna().iloc[-1] >= 0


def test_relative_return() -> None:
    idx = pd.date_range(datetime(2025, 1, 1), periods=3, freq="D")
    asset = pd.Series([100.0, 110.0, 121.0], index=idx)
    benchmark = pd.Series([100.0, 105.0, 110.25], index=idx)
    rel = relative_return(asset, benchmark, periods=2)
    assert rel.iloc[-1] == pytest.approx(0.1075)


def test_relative_return_uses_shared_dates_before_lookback() -> None:
    asset_idx = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"])
    benchmark_idx = pd.to_datetime(["2025-01-01", "2025-01-03", "2025-01-04"])
    asset = pd.Series([100.0, 999.0, 110.0, 121.0], index=asset_idx)
    benchmark = pd.Series([100.0, 110.0, 121.0], index=benchmark_idx)

    rel = relative_return(asset, benchmark, periods=2)

    assert pd.isna(rel.loc[pd.Timestamp("2025-01-02")])
    assert rel.loc[pd.Timestamp("2025-01-04")] == pytest.approx(0.0)


def test_compute_ytd_return() -> None:
    idx = pd.to_datetime(["2025-01-02", "2025-01-03", "2026-01-02"])
    series = pd.Series([100.0, 110.0, 200.0], index=idx)
    ytd = compute_ytd_return(series)
    assert ytd.iloc[1] == pytest.approx(0.10)
    assert ytd.iloc[2] == pytest.approx((200.0 / 110.0) - 1.0)


def test_compute_ytd_return_uses_prior_year_close() -> None:
    idx = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05"])
    series = pd.Series([100.0, 110.0, 121.0], index=idx)
    ytd = compute_ytd_return(series)
    assert ytd.iloc[1] == pytest.approx(0.10)
    assert ytd.iloc[2] == pytest.approx(0.21)


def test_distance_from_ma() -> None:
    price = pd.Series([100.0, 110.0])
    ma = pd.Series([100.0, 100.0])
    distance = distance_from_ma(price, ma)
    assert distance.iloc[1] == pytest.approx(0.10)
