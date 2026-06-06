from __future__ import annotations

from datetime import date
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from argus.analytics.market_hours import filter_regular_market_hours
from argus.core.models import Company, PriceBar, IndexValue
from argus.core.settings import settings


def get_default_index_symbols(session: Session) -> list[str]:
    """
    Get the default constituent symbols for the AI Infra Core Index.
    Excludes benchmark-only names, optional aggressive names, and Emerging
    Compute names by default so the index remains an AI Infrastructure index.
    """
    from argus.core.seed import AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS

    companies = session.query(Company).filter(Company.is_active.is_(True)).all()
    return [c.symbol for c in companies if c.symbol not in AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS]


def calculate_equal_weight_index(
    session: Session,
    symbols: list[str] | None = None,
    base_value: float = 100.0,
    use_precomputed: bool = True,
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Build an equal-weight index. If symbols is None and the pre-calculated
    index_values table has data, we load it directly from the database for speed.
    Otherwise, we calculate it dynamically from price_bars.
    """
    interval = interval.strip().lower()
    if interval not in {"1d", "15m"}:
        raise ValueError("calculate_equal_weight_index supports interval='1d' or interval='15m'")

    if interval == "15m":
        use_precomputed = False

    if symbols is None and use_precomputed:
        try:
            query = session.query(IndexValue.date, IndexValue.index_value).order_by(
                IndexValue.date.asc()
            )
            df_pre = pd.read_sql_query(query.statement, session.connection())
            if not df_pre.empty:
                df_pre.columns = ["date", "index_value"]
                df_pre["date"] = pd.to_datetime(df_pre["date"]).dt.date
                return df_pre
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Could not read pre-calculated index_values: %s", exc
            )

    if symbols is None:
        symbols = get_default_index_symbols(session)

    if not symbols:
        return pd.DataFrame(columns=["date", "index_value"])

    point_column = PriceBar.bar_time if interval == "15m" else PriceBar.date
    query = (
        session.query(point_column.label("date"), Company.symbol, PriceBar.adj_close)
        .join(Company, Company.id == PriceBar.company_id)
        .filter(
            Company.symbol.in_(symbols),
            PriceBar.provider == settings.market_data_provider,
            PriceBar.interval == interval,
        )
        .order_by(point_column.asc())
    )
    df = pd.read_sql_query(query.statement, session.connection())

    if df.empty:
        return pd.DataFrame(columns=["date", "index_value"])

    df["date"] = pd.to_datetime(df["date"])
    if interval == "15m":
        df = filter_regular_market_hours(df)
        if df.empty:
            return pd.DataFrame(columns=["date", "index_value"])

    # Pivot so each column represents a ticker, and the index represents dates
    pivot_df = df.pivot(index="date", columns="symbol", values="adj_close")
    pivot_df = pivot_df.sort_index().astype(float)
    if interval == "15m":
        pivot_df = pivot_df.ffill(limit=4)

    # Calculate daily percentage returns (pct_change naturally handles NaNs)
    returns_df = pivot_df.pct_change(fill_method=None)

    # Calculate the average return across all tickers that have valid returns on each day
    mean_returns = returns_df.mean(axis=1, skipna=True)

    # The first row (and any day with absolutely no returns) is filled with 0
    mean_returns = mean_returns.fillna(0.0)

    # Chain returns using cumulative product
    cumulative_returns = (1.0 + mean_returns).cumprod()

    # Apply base value
    index_values = base_value * cumulative_returns

    result = index_values.reset_index()
    result.columns = ["date", "index_value"]
    if interval == "1d":
        result["date"] = result["date"].dt.date
    return result


def calculate_relative_performance(
    session: Session,
    index_df: pd.DataFrame,
    start_date: date,
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Build cumulative returns starting at 0% (relative performance percentage) or 100 on start_date for:
    - AI Infra Core Index
    - QQQ (Benchmark)
    - NVDA (Benchmark)
    Returns a DataFrame with columns: ['date', 'index_ret', 'qqq_ret', 'nvda_ret']
    representing the percentage return since start_date.
    """
    if index_df.empty:
        return pd.DataFrame()

    interval = interval.strip().lower()
    if interval not in {"1d", "15m"}:
        raise ValueError("calculate_relative_performance supports interval='1d' or interval='15m'")

    # Filter index to start date
    idx_filtered = index_df[index_df["date"] >= start_date].copy()
    if idx_filtered.empty:
        return pd.DataFrame()

    idx_filtered = idx_filtered.sort_values("date")
    base_idx = idx_filtered["index_value"].iloc[0]
    # Return percentage relative performance (starting at 0%)
    idx_filtered["index_ret"] = (idx_filtered["index_value"] / base_idx - 1.0) * 100.0

    # Fetch price bars for QQQ and NVDA
    benchmarks = ["QQQ", "NVDA"]
    point_column = PriceBar.bar_time if interval == "15m" else PriceBar.date
    query = (
        session.query(point_column.label("date"), Company.symbol, PriceBar.adj_close)
        .join(Company, Company.id == PriceBar.company_id)
        .filter(
            Company.symbol.in_(benchmarks),
            PriceBar.provider == settings.market_data_provider,
            PriceBar.interval == interval,
            point_column >= start_date,
        )
        .order_by(point_column.asc())
    )
    bench_df = pd.read_sql_query(query.statement, session.connection())
    if interval == "15m" and not bench_df.empty:
        bench_df["date"] = pd.to_datetime(bench_df["date"])
        bench_df = filter_regular_market_hours(bench_df)

    merged = idx_filtered[["date", "index_ret"]].copy()

    for symbol in benchmarks:
        sym_df = bench_df[bench_df["symbol"] == symbol].copy()
        if sym_df.empty:
            merged[f"{symbol.lower()}_ret"] = pd.NA
            continue
        sym_df["date"] = pd.to_datetime(sym_df["date"])
        if interval == "1d":
            sym_df["date"] = sym_df["date"].dt.date
        sym_df = sym_df.sort_values("date")

        # Merge onto index dates to align timelines
        merged = pd.merge(
            merged,
            sym_df[["date", "adj_close"]].rename(columns={"adj_close": f"{symbol}_close"}),
            on="date",
            how="left",
        )
        merged[f"{symbol}_close"] = merged[f"{symbol}_close"].ffill()

        first_valid = merged[f"{symbol}_close"].first_valid_index()
        merged[f"{symbol.lower()}_ret"] = pd.NA
        if first_valid is not None:
            base_val = merged.loc[first_valid, f"{symbol}_close"]
            if base_val and base_val != 0:
                merged.loc[first_valid:, f"{symbol.lower()}_ret"] = (
                    merged.loc[first_valid:, f"{symbol}_close"] / base_val - 1.0
                ) * 100.0

    # Clean up intermediate close price columns
    cols_to_keep = ["date", "index_ret", "qqq_ret", "nvda_ret"]
    merged = merged[[c for c in cols_to_keep if c in merged]]
    return merged


def calculate_top_contributors(
    session: Session,
    symbols: list[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Calculate performance and index contribution for each constituent.
    Contribution = Return / N where N is the number of active constituents in the portfolio.
    Returns a DataFrame with columns: ['symbol', 'name', 'return', 'contribution'] sorted by contribution.
    """
    query = (
        session.query(PriceBar.date, Company.symbol, PriceBar.adj_close)
        .join(Company, Company.id == PriceBar.company_id)
        .filter(
            Company.symbol.in_(symbols),
            PriceBar.provider == settings.market_data_provider,
            PriceBar.interval == "1d",
            PriceBar.date >= start_date,
            PriceBar.date <= end_date,
        )
        .order_by(PriceBar.date.asc())
    )
    df = pd.read_sql_query(query.statement, session.connection())
    if df.empty:
        return pd.DataFrame(columns=["symbol", "name", "return", "contribution"])

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["adj_close"] = pd.to_numeric(df["adj_close"], errors="coerce")
    df = df.replace([np.inf, -np.inf], pd.NA).dropna(subset=["adj_close"])
    if df.empty:
        return pd.DataFrame(columns=["symbol", "name", "return", "contribution"])

    active_symbols = df["symbol"].unique()
    n_constituents = len(active_symbols)
    if n_constituents == 0:
        return pd.DataFrame(columns=["symbol", "name", "return", "contribution"])

    comp_names = {
        c.symbol: c.name
        for c in session.query(Company.symbol, Company.name)
        .filter(Company.symbol.in_(symbols))
        .all()
    }

    records = []
    for sym in active_symbols:
        sym_df = df[df["symbol"] == sym].sort_values("date")
        if len(sym_df) < 2:
            continue
        start_row = sym_df.iloc[0]
        end_row = sym_df.iloc[-1]

        base_price = start_row["adj_close"]
        end_price = end_row["adj_close"]
        if base_price and base_price > 0 and pd.notna(end_price):
            ret = (end_price / base_price) - 1.0
        else:
            continue

        contrib = ret / n_constituents
        records.append(
            {
                "symbol": sym,
                "name": comp_names.get(sym, sym),
                "return": ret,
                "contribution": contrib,
            }
        )

    res_df = pd.DataFrame(records, columns=["symbol", "name", "return", "contribution"])
    if not res_df.empty:
        res_df = res_df.sort_values("contribution", ascending=False)
    return res_df
