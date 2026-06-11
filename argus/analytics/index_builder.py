from __future__ import annotations

from datetime import date
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from argus.analytics.market_hours import filter_regular_market_hours
from argus.core.models import (
    Company,
    CompanyThemeExposure,
    IndexConstituent,
    IndexDefinition,
    IndexValue,
    PriceBar,
    Theme,
)
from argus.core.settings import settings

DEFAULT_INDEX_NAME = "AI Infra Core"
LEGACY_DEFAULT_INDEX_NAME = "AI Infra Core Equal Weight"
INDEX_MODE_EQUAL = "equal"
INDEX_MODE_EXPOSURE = "exposure"
INDEX_MODE_MANUAL = "manual"
INDEX_MODES = {INDEX_MODE_EQUAL, INDEX_MODE_EXPOSURE, INDEX_MODE_MANUAL}


# ── Index Definitions & Constituent Administration ────────────────────────────
def get_default_index_symbols(session: Session) -> list[str]:
    """
    Get the default constituent symbols for the AI Infra Core Index.
    Excludes benchmark-only names, optional aggressive names, and Emerging
    Compute names by default so the index remains an AI Infrastructure index.
    """
    from argus.core.seed import AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS

    companies = session.query(Company).filter(Company.is_active.is_(True)).all()
    return [c.symbol for c in companies if c.symbol not in AI_INFRA_CORE_INDEX_EXCLUDED_SYMBOLS]


# ── Weight Normalization & Validation Helpers ─────────────────────────────────
def _normalize_weights(raw_weights: dict[str, float]) -> dict[str, float]:
    weights = {symbol: max(0.0, float(weight)) for symbol, weight in raw_weights.items()}
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {symbol: weight / total for symbol, weight in weights.items() if weight > 0}


def validate_manual_weights(weights: dict[str, float]) -> dict[str, float]:
    """Validate manual weights supplied as fractions whose total must equal 1.0."""
    if not weights:
        raise ValueError("manual index definitions require at least one included company")

    normalized_symbols = {
        symbol.strip().upper(): float(weight) for symbol, weight in weights.items()
    }
    if any(weight < 0 for weight in normalized_symbols.values()):
        raise ValueError("manual weights must be non-negative")

    total = sum(normalized_symbols.values())
    if abs(total - 1.0) > 0.000001:
        raise ValueError("manual weights must total exactly 100%")

    return {symbol: weight for symbol, weight in normalized_symbols.items() if weight > 0}


def _default_constituent_weights(session: Session) -> dict[str, float]:
    symbols = sorted(get_default_index_symbols(session))
    if not symbols:
        return {}
    equal_weight = 1.0 / len(symbols)
    return {symbol: equal_weight for symbol in symbols}


# ── Index Definition Synchronization & Access ─────────────────────────────────
def _sync_default_index_constituents(session: Session, definition: IndexDefinition) -> bool:
    if definition.name != DEFAULT_INDEX_NAME or definition.mode != INDEX_MODE_EQUAL:
        return False

    weights = _default_constituent_weights(session)
    company_by_symbol = {
        company.symbol: company
        for company in session.query(Company)
        .filter(Company.symbol.in_(sorted(weights)), Company.is_active.is_(True))
        .all()
    }
    current_rows = (
        session.query(IndexConstituent, Company.symbol)
        .join(Company, Company.id == IndexConstituent.company_id)
        .filter(IndexConstituent.index_definition_id == definition.id)
        .all()
    )
    current_by_symbol = {symbol: row for row, symbol in current_rows}
    dirty = False

    for row, symbol in current_rows:
        if symbol not in weights:
            session.delete(row)
            dirty = True
            continue
        target_weight = weights[symbol]
        if not row.is_included or abs(float(row.target_weight or 0.0) - target_weight) > 0.000001:
            row.is_included = True
            row.target_weight = target_weight
            dirty = True

    for symbol, target_weight in weights.items():
        if symbol in current_by_symbol:
            continue
        company = company_by_symbol.get(symbol)
        if company is None:
            continue
        session.add(
            IndexConstituent(
                index_definition_id=definition.id,
                company_id=company.id,
                target_weight=target_weight,
                is_included=True,
            )
        )
        dirty = True

    return dirty


def ensure_default_index_definition(session: Session) -> IndexDefinition:
    """Create the default immutable definition shell and migrate legacy values."""
    definition = (
        session.query(IndexDefinition)
        .filter(IndexDefinition.name == DEFAULT_INDEX_NAME)
        .one_or_none()
    )
    dirty = False
    if definition is None:
        legacy_definition = (
            session.query(IndexDefinition)
            .filter(IndexDefinition.name == LEGACY_DEFAULT_INDEX_NAME)
            .one_or_none()
        )
        if legacy_definition is not None:
            legacy_definition.name = DEFAULT_INDEX_NAME
            definition = legacy_definition
            dirty = True

    if definition is None:
        definition = IndexDefinition(
            name=DEFAULT_INDEX_NAME,
            mode=INDEX_MODE_EQUAL,
            base_value=100.0,
            is_active=True,
        )
        session.add(definition)
        session.flush()
        dirty = True

    has_constituents = (
        session.query(IndexConstituent)
        .filter(IndexConstituent.index_definition_id == definition.id)
        .first()
        is not None
    )
    if not has_constituents:
        for symbol, weight in _default_constituent_weights(session).items():
            company = session.query(Company).filter(Company.symbol == symbol).one_or_none()
            if company is not None:
                session.add(
                    IndexConstituent(
                        index_definition_id=definition.id,
                        company_id=company.id,
                        target_weight=weight,
                        is_included=True,
                    )
                )
                dirty = True
    else:
        dirty = _sync_default_index_constituents(session, definition) or dirty

    updated_rows = (
        session.query(IndexValue)
        .filter(IndexValue.index_definition_id.is_(None))
        .update(
            {IndexValue.index_definition_id: definition.id},
            synchronize_session=False,
        )
    )
    if updated_rows > 0:
        dirty = True

    if dirty:
        session.commit()
    else:
        session.flush()
    return definition


def list_index_definitions(session: Session, active_only: bool = True) -> list[IndexDefinition]:
    ensure_default_index_definition(session)
    query = session.query(IndexDefinition)
    if active_only:
        query = query.filter(IndexDefinition.is_active.is_(True))
    return query.order_by(IndexDefinition.created_at.asc(), IndexDefinition.name.asc()).all()


def get_index_definition(session: Session, definition_id: int | None = None) -> IndexDefinition:
    default_definition = ensure_default_index_definition(session)
    if definition_id is None:
        return default_definition

    definition = session.get(IndexDefinition, definition_id)
    if definition is None:
        return default_definition
    return definition


# ── Weight & Constituent Accessors ────────────────────────────────────────────
def _included_constituents(
    session: Session, definition: IndexDefinition
) -> list[tuple[Company, float]]:
    rows = (
        session.query(Company, IndexConstituent.target_weight)
        .join(IndexConstituent, IndexConstituent.company_id == Company.id)
        .filter(
            IndexConstituent.index_definition_id == definition.id,
            IndexConstituent.is_included.is_(True),
            Company.is_active.is_(True),
        )
        .order_by(Company.symbol.asc())
        .all()
    )
    return rows


def get_index_weights(
    session: Session,
    definition_id: int | None = None,
) -> dict[str, float]:
    definition = get_index_definition(session, definition_id)
    rows = _included_constituents(session, definition)
    symbols = [company.symbol for company, _target_weight in rows]
    if not symbols:
        return {}

    if definition.mode == INDEX_MODE_EQUAL:
        return {symbol: 1.0 / len(symbols) for symbol in symbols}

    if definition.mode == INDEX_MODE_EXPOSURE:
        exposure_rows = (
            session.query(Company.symbol, CompanyThemeExposure.exposure_score)
            .join(CompanyThemeExposure, CompanyThemeExposure.company_id == Company.id)
            .filter(Company.symbol.in_(symbols))
            .all()
        )
        raw_weights = {symbol: 0.0 for symbol in symbols}
        for symbol, exposure_score in exposure_rows:
            raw_weights[symbol] += max(0.0, float(exposure_score or 0.0))
        normalized = _normalize_weights(raw_weights)
        return normalized or {symbol: 1.0 / len(symbols) for symbol in symbols}

    if definition.mode == INDEX_MODE_MANUAL:
        return _normalize_weights(
            {company.symbol: target_weight for company, target_weight in rows}
        )

    raise ValueError(f"unsupported index mode: {definition.mode}")


def get_index_constituent_table(
    session: Session,
    definition_id: int | None = None,
) -> pd.DataFrame:
    definition = get_index_definition(session, definition_id)
    weights = get_index_weights(session, definition.id)
    rows = _included_constituents(session, definition)
    records = []
    for company, target_weight in rows:
        records.append(
            {
                "company_id": company.id,
                "symbol": company.symbol,
                "name": company.name,
                "sector": company.sector,
                "mode": definition.mode,
                "target_weight": float(target_weight or 0.0),
                "effective_weight": weights.get(company.symbol, 0.0),
            }
        )
    return pd.DataFrame(records)


def create_index_definition(
    session: Session,
    name: str,
    mode: str,
    company_weights: dict[str, float] | None = None,
    base_value: float = 100.0,
) -> IndexDefinition:
    """Create an immutable index definition. Future edits should create another definition."""
    mode = mode.strip().lower()
    if mode not in INDEX_MODES:
        raise ValueError(f"unsupported index mode: {mode}")

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("index name is required")
    if session.query(IndexDefinition).filter(IndexDefinition.name == clean_name).one_or_none():
        raise ValueError("index name already exists")

    if company_weights is None:
        company_weights = _default_constituent_weights(session)

    if mode == INDEX_MODE_MANUAL:
        company_weights = validate_manual_weights(company_weights)
    else:
        company_weights = _normalize_weights(company_weights)

    if not company_weights:
        raise ValueError("index definitions require at least one included company")

    companies = (
        session.query(Company)
        .filter(Company.symbol.in_(sorted(company_weights)), Company.is_active.is_(True))
        .all()
    )
    company_by_symbol = {company.symbol: company for company in companies}
    missing = sorted(set(company_weights) - set(company_by_symbol))
    if missing:
        raise ValueError(f"unknown or inactive companies: {', '.join(missing)}")

    definition = IndexDefinition(
        name=clean_name,
        mode=mode,
        base_value=float(base_value),
        is_active=True,
    )
    session.add(definition)
    session.flush()
    for symbol, weight in sorted(company_weights.items()):
        session.add(
            IndexConstituent(
                index_definition_id=definition.id,
                company_id=company_by_symbol[symbol].id,
                target_weight=float(weight),
                is_included=True,
            )
        )
    session.flush()
    return definition


def clone_index_definition(
    session: Session,
    source_definition_id: int,
    name: str,
    mode: str | None = None,
    company_weights: dict[str, float] | None = None,
) -> IndexDefinition:
    source = get_index_definition(session, source_definition_id)
    if company_weights is None:
        current = get_index_constituent_table(session, source.id)
        company_weights = dict(zip(current["symbol"], current["target_weight"], strict=False))
    return create_index_definition(
        session,
        name=name,
        mode=mode or source.mode,
        company_weights=company_weights,
        base_value=source.base_value,
    )


# ── Index Calculation Helpers & Calculators ───────────────────────────────────
def _load_price_matrix(
    session: Session,
    symbols: list[str],
    *,
    interval: str,
) -> pd.DataFrame:
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
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    if interval == "15m":
        df = filter_regular_market_hours(df)
        if df.empty:
            return pd.DataFrame()

    pivot_df = df.pivot(index="date", columns="symbol", values="adj_close")
    pivot_df = pivot_df.sort_index().astype(float)
    if interval == "15m":
        pivot_df = pivot_df.ffill(limit=4)
    return pivot_df


def _calculate_weighted_returns(price_matrix: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    returns_df = price_matrix.pct_change(fill_method=None)
    weight_series = pd.Series(weights, dtype=float)
    aligned_weights = weight_series.reindex(returns_df.columns).fillna(0.0)
    valid_returns = returns_df.notna()
    active_weight_total = valid_returns.multiply(aligned_weights, axis=1).sum(axis=1)
    weighted_return_sum = returns_df.fillna(0.0).multiply(aligned_weights, axis=1).sum(axis=1)
    weighted_returns = weighted_return_sum.divide(
        active_weight_total.where(active_weight_total > 0)
    )
    return weighted_returns.fillna(0.0)


def _calculate_equal_weight_returns(price_matrix: pd.DataFrame) -> pd.Series:
    returns_df = price_matrix.pct_change(fill_method=None)
    return returns_df.mean(axis=1, skipna=True).fillna(0.0)


def _returns_to_index_values(
    returns: pd.Series,
    *,
    base_value: float,
    interval: str,
) -> pd.DataFrame:
    index_values = base_value * (1.0 + returns).cumprod()
    result = index_values.reset_index()
    result.columns = ["date", "index_value"]
    if interval == "1d":
        result["date"] = result["date"].dt.date
    return result


def calculate_weighted_index(
    session: Session,
    definition_id: int | None = None,
    base_value: float | None = None,
    use_precomputed: bool = True,
    interval: str = "1d",
) -> pd.DataFrame:
    definition = get_index_definition(session, definition_id)
    interval = interval.strip().lower()
    if interval not in {"1d", "15m"}:
        raise ValueError("calculate_weighted_index supports interval='1d' or interval='15m'")

    if interval == "15m":
        use_precomputed = False

    if use_precomputed:
        try:
            query = (
                session.query(IndexValue.date, IndexValue.index_value)
                .filter(IndexValue.index_definition_id == definition.id)
                .order_by(IndexValue.date.asc())
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

    weights = get_index_weights(session, definition.id)
    if not weights:
        return pd.DataFrame(columns=["date", "index_value"])

    price_matrix = _load_price_matrix(session, list(weights), interval=interval)
    if price_matrix.empty:
        return pd.DataFrame(columns=["date", "index_value"])

    index_base_value = float(base_value if base_value is not None else definition.base_value)
    weighted_returns = _calculate_weighted_returns(price_matrix, weights)
    return _returns_to_index_values(
        weighted_returns,
        base_value=index_base_value,
        interval=interval,
    )


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
    if symbols is None:
        return calculate_weighted_index(
            session,
            base_value=base_value,
            use_precomputed=use_precomputed,
            interval=interval,
        )

    interval = interval.strip().lower()
    if interval not in {"1d", "15m"}:
        raise ValueError("calculate_equal_weight_index supports interval='1d' or interval='15m'")

    if interval == "15m":
        use_precomputed = False

    if not symbols:
        return pd.DataFrame(columns=["date", "index_value"])

    price_matrix = _load_price_matrix(session, symbols, interval=interval)
    if price_matrix.empty:
        return pd.DataFrame(columns=["date", "index_value"])

    mean_returns = _calculate_equal_weight_returns(price_matrix)
    return _returns_to_index_values(mean_returns, base_value=base_value, interval=interval)


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
    weights: dict[str, float] | None = None,
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

    active_symbols = sorted(df["symbol"].unique())
    n_constituents = len(active_symbols)
    if n_constituents == 0:
        return pd.DataFrame(columns=["symbol", "name", "return", "contribution"])

    if weights is None:
        active_weights = {symbol: 1.0 / n_constituents for symbol in active_symbols}
    else:
        active_weights = _normalize_weights(
            {symbol: weights.get(symbol, 0.0) for symbol in active_symbols}
        )

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

        contrib = ret * active_weights.get(sym, 0.0)
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


def calculate_top_contributors_for_definition(
    session: Session,
    definition_id: int | None,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    weights = get_index_weights(session, definition_id)
    return calculate_top_contributors(
        session,
        symbols=list(weights),
        start_date=start_date,
        end_date=end_date,
        weights=weights,
    )


def calculate_theme_concentration(
    session: Session,
    definition_id: int | None = None,
) -> pd.DataFrame:
    definition = get_index_definition(session, definition_id)
    weights = get_index_weights(session, definition.id)
    if not weights:
        return pd.DataFrame(columns=["theme", "weight"])

    rows = (
        session.query(Company.symbol, Theme.name, CompanyThemeExposure.exposure_score)
        .join(CompanyThemeExposure, CompanyThemeExposure.company_id == Company.id)
        .join(Theme, Theme.id == CompanyThemeExposure.theme_id)
        .filter(Company.symbol.in_(list(weights)))
        .all()
    )
    by_symbol: dict[str, list[tuple[str, float]]] = {}
    for symbol, theme_name, exposure_score in rows:
        score = max(0.0, float(exposure_score or 0.0))
        if score <= 0:
            continue
        by_symbol.setdefault(symbol, []).append((theme_name, score))

    concentration: dict[str, float] = {}
    for symbol, company_weight in weights.items():
        exposures = by_symbol.get(symbol)
        if not exposures:
            concentration["Unclassified"] = concentration.get("Unclassified", 0.0) + company_weight
            continue
        exposure_total = sum(score for _theme_name, score in exposures)
        for theme_name, score in exposures:
            concentration[theme_name] = concentration.get(theme_name, 0.0) + (
                company_weight * score / exposure_total
            )

    return pd.DataFrame(
        [{"theme": theme, "weight": weight} for theme, weight in concentration.items()]
    ).sort_values("weight", ascending=False)
