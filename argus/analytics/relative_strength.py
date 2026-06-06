from __future__ import annotations

import pandas as pd


def relative_return(
    asset_prices: pd.Series, benchmark_prices: pd.Series, periods: int
) -> pd.Series:
    aligned_prices = pd.concat(
        [asset_prices.rename("asset"), benchmark_prices.rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()

    asset_return = aligned_prices["asset"].pct_change(periods=periods)
    benchmark_return = aligned_prices["benchmark"].pct_change(periods=periods)
    relative = asset_return - benchmark_return
    return relative.reindex(asset_prices.index)
