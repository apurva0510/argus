from __future__ import annotations

from datetime import date
import pandas as pd
from sqlalchemy.orm import Session
from argus.core.models import Company, PriceBar
from argus.core.settings import settings


def get_default_index_symbols(session: Session) -> list[str]:
    """
    Get the default constituent symbols for the AI Infra Core Index.
    Excludes benchmark-only names (NVDA, MSFT, AMZN, GOOGL, META, QQQ)
    and optional aggressive names (ALAB, CRDO) by default.
    """
    from argus.core.seed import BENCHMARKS, OPTIONAL_AGGRESSIVE_SYMBOLS
    companies = session.query(Company).filter(Company.is_active.is_(True)).all()
    excluded = BENCHMARKS | OPTIONAL_AGGRESSIVE_SYMBOLS
    return [c.symbol for c in companies if c.symbol not in excluded]


def calculate_equal_weight_index(
    session: Session,
    symbols: list[str] | None = None,
    base_value: float = 100.0,
) -> pd.DataFrame:
    """
    Build an equal-weight index from price_bars using adjusted close prices.
    Returns a DataFrame with columns: ['date', 'index_value']
    Gracefully handles tickers with missing histories or different start dates.
    """
    if symbols is None:
        symbols = get_default_index_symbols(session)

    if not symbols:
        return pd.DataFrame(columns=["date", "index_value"])

    # Query daily price bars for the requested symbols
    query = (
        session.query(PriceBar.date, Company.symbol, PriceBar.adj_close)
        .join(Company, Company.id == PriceBar.company_id)
        .filter(
            Company.symbol.in_(symbols),
            PriceBar.provider == settings.market_data_provider,
            PriceBar.interval == "1d",
        )
        .order_by(PriceBar.date.asc())
    )
    df = pd.read_sql_query(query.statement, session.connection())

    if df.empty:
        return pd.DataFrame(columns=["date", "index_value"])

    # Convert date to datetime to facilitate formatting/sorting
    df["date"] = pd.to_datetime(df["date"])
    
    # Pivot so each column represents a ticker, and the index represents dates
    pivot_df = df.pivot(index="date", columns="symbol", values="adj_close")
    pivot_df = pivot_df.sort_index().astype(float)

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
    result["date"] = result["date"].dt.date
    return result


def calculate_relative_performance(
    session: Session,
    index_df: pd.DataFrame,
    start_date: date,
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
    query = (
        session.query(PriceBar.date, Company.symbol, PriceBar.adj_close)
        .join(Company, Company.id == PriceBar.company_id)
        .filter(
            Company.symbol.in_(benchmarks),
            PriceBar.provider == settings.market_data_provider,
            PriceBar.interval == "1d",
            PriceBar.date >= start_date,
        )
        .order_by(PriceBar.date.asc())
    )
    bench_df = pd.read_sql_query(query.statement, session.connection())

    merged = idx_filtered[["date", "index_ret"]].copy()

    for symbol in benchmarks:
        sym_df = bench_df[bench_df["symbol"] == symbol].copy()
        if sym_df.empty:
            merged[f"{symbol.lower()}_ret"] = pd.NA
            continue
        sym_df["date"] = pd.to_datetime(sym_df["date"]).dt.date
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
                    (merged.loc[first_valid:, f"{symbol}_close"] / base_val - 1.0) * 100.0
                )

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
        if sym_df.empty:
            continue
        start_row = sym_df.iloc[0]
        end_row = sym_df.iloc[-1]

        if start_row["date"] == end_row["date"]:
            ret = 0.0
        else:
            base_price = start_row["adj_close"]
            if base_price and base_price != 0:
                ret = (end_row["adj_close"] / base_price) - 1.0
            else:
                ret = 0.0

        contrib = ret / n_constituents
        records.append({
            "symbol": sym,
            "name": comp_names.get(sym, sym),
            "return": ret,
            "contribution": contrib,
        })

    res_df = pd.DataFrame(records)
    if not res_df.empty:
        res_df = res_df.sort_values("contribution", ascending=False)
    return res_df
