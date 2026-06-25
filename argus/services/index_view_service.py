from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from argus.analytics.index_builder import (
    calculate_relative_performance,
    calculate_top_contributors_for_definition,
    calculate_weighted_index,
    get_index_weights,
    list_index_definitions,
)
from argus.analytics.market_hours import filter_latest_market_sessions
from argus.core.models import Company, PriceBar
from argus.core.settings import settings
from argus.core.timezones import to_et_naive_series


def load_index_options_from_engine(engine: Engine) -> list[dict[str, object]]:
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        return [
            {"id": definition.id, "name": definition.name, "mode": definition.mode}
            for definition in list_index_definitions(session)
        ]


def daily_close_levels_from_session_returns(
    intraday_frame: pd.DataFrame,
    daily_frame: pd.DataFrame,
    *,
    daily_value_column: str,
    output_column: str,
) -> pd.DataFrame:
    """Map official daily returns onto each session's intraday opening level."""
    if (
        intraday_frame.empty
        or daily_frame.empty
        or "date" not in intraday_frame
        or "date" not in daily_frame
        or output_column not in intraday_frame
        or daily_value_column not in daily_frame
    ):
        return pd.DataFrame(columns=["date", output_column])

    intraday = intraday_frame[["date", output_column]].copy()
    intraday["session_date"] = pd.to_datetime(to_et_naive_series(intraday["date"])).dt.date
    intraday[output_column] = pd.to_numeric(intraday[output_column], errors="coerce")
    session_open_levels = (
        intraday.dropna(subset=[output_column])
        .sort_values("date")
        .groupby("session_date", as_index=False)[output_column]
        .first()
    )
    if session_open_levels.empty:
        return pd.DataFrame(columns=["date", output_column])

    daily = daily_frame[["date", daily_value_column]].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    daily[daily_value_column] = pd.to_numeric(daily[daily_value_column], errors="coerce")
    daily = daily.dropna(subset=[daily_value_column]).sort_values("date")
    daily["session_return"] = daily[daily_value_column] / daily[daily_value_column].shift(1) - 1.0

    close_levels = session_open_levels.merge(
        daily[["date", "session_return"]],
        left_on="session_date",
        right_on="date",
        how="inner",
    ).dropna(subset=["session_return"])
    if close_levels.empty:
        return pd.DataFrame(columns=["date", output_column])

    close_levels[output_column] = close_levels[output_column] * (
        1.0 + close_levels["session_return"]
    )
    return pd.DataFrame(
        {
            "date": close_levels["session_date"],
            output_column: close_levels[output_column],
        }
    )


def load_dashboard_index_data_from_engine(
    engine: Engine, tf: str, index_definition_id: int | None = None
) -> dict:
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        short_range = tf in {"1D", "5D"}
        interval = "15m" if short_range else "1d"
        index_df = calculate_weighted_index(
            session,
            definition_id=index_definition_id,
            interval=interval,
            use_precomputed=not short_range,
        )
        if index_df.empty:
            return {}

        if short_range:
            index_df = filter_latest_market_sessions(index_df, 1 if tf == "1D" else 5)
            if index_df.empty:
                return {}

        latest_point = pd.to_datetime(index_df["date"]).max()
        if tf in {"1D", "5D"}:
            start_date = pd.to_datetime(index_df["date"]).min()
        elif tf == "1M":
            start_date = latest_point - pd.Timedelta(days=30)
        elif tf == "3M":
            start_date = latest_point - pd.Timedelta(days=90)
        elif tf == "6M":
            start_date = latest_point - pd.Timedelta(days=180)
        elif tf == "1Y":
            start_date = latest_point - pd.Timedelta(days=365)
        else:
            start_date = pd.to_datetime(index_df["date"]).min()

        if not short_range:
            start_date = pd.to_datetime(start_date).date()
        latest_date_date = latest_point.date()

        rel_df = calculate_relative_performance(
            session,
            index_df,
            start_date,
            interval=interval,
        )
        daily_close_levels = pd.DataFrame()
        if not rel_df.empty:
            rel_df["index_level"] = 100.0 + rel_df["index_ret"]
            if "qqq_ret" in rel_df and not rel_df["qqq_ret"].isna().all():
                rel_df["qqq_level"] = 100.0 + rel_df["qqq_ret"]
            if "nvda_ret" in rel_df and not rel_df["nvda_ret"].isna().all():
                rel_df["nvda_level"] = 100.0 + rel_df["nvda_ret"]

            if short_range:
                daily_close_levels = _build_daily_close_levels(
                    session, rel_df, index_definition_id, start_date
                )

        weights = get_index_weights(session, index_definition_id)
        symbols = list(weights)

        date_1m = latest_date_date - timedelta(days=30)
        date_3m = latest_date_date - timedelta(days=90)
        date_ytd = datetime(latest_date_date.year - 1, 12, 31).date()

        return {
            "rel_df": rel_df,
            "contrib_1m": calculate_top_contributors_for_definition(
                session,
                index_definition_id,
                date_1m,
                latest_date_date,
            ),
            "contrib_3m": calculate_top_contributors_for_definition(
                session,
                index_definition_id,
                date_3m,
                latest_date_date,
            ),
            "contrib_ytd": calculate_top_contributors_for_definition(
                session,
                index_definition_id,
                date_ytd,
                latest_date_date,
            ),
            "constituent_count": len(symbols),
            "interval": interval,
            "daily_close_levels": daily_close_levels,
        }


def load_index_relative_returns_from_engine(
    engine: Engine,
    start_date,
    interval: str = "1d",
    index_definition_id: int | None = None,
) -> pd.DataFrame:
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        interval = interval.strip().lower()
        index_df = calculate_weighted_index(
            session,
            definition_id=index_definition_id,
            interval=interval,
            use_precomputed=interval == "1d",
        )
        if index_df.empty:
            return pd.DataFrame()

        if interval == "15m" and start_date is not None:
            start_date_utc = (
                pd.to_datetime(start_date)
                .tz_localize("America/New_York")
                .tz_convert("UTC")
                .tz_localize(None)
                .to_pydatetime()
            )
        else:
            start_date_utc = start_date

        return calculate_relative_performance(session, index_df, start_date_utc, interval=interval)


def _build_daily_close_levels(
    session,
    rel_df: pd.DataFrame,
    index_definition_id: int | None,
    start_date,
) -> pd.DataFrame:
    daily_index_df = calculate_weighted_index(
        session,
        definition_id=index_definition_id,
        interval="1d",
        use_precomputed=True,
    )
    if daily_index_df.empty:
        daily_index_df = calculate_weighted_index(
            session,
            definition_id=index_definition_id,
            interval="1d",
            use_precomputed=False,
        )

    daily_close_levels = pd.DataFrame()
    if not daily_index_df.empty:
        daily_close_levels = daily_close_levels_from_session_returns(
            rel_df,
            daily_index_df,
            daily_value_column="index_value",
            output_column="index_level",
        )

    benchmark_bases = _load_benchmark_bases(session, rel_df, start_date)
    if not benchmark_bases:
        return daily_close_levels

    benchmark_daily = pd.read_sql_query(
        session.query(PriceBar.date, Company.symbol, PriceBar.adj_close)
        .join(Company, Company.id == PriceBar.company_id)
        .filter(
            Company.symbol.in_(list(benchmark_bases)),
            PriceBar.provider == settings.market_data_provider,
            PriceBar.interval == "1d",
        )
        .order_by(PriceBar.date.asc())
        .statement,
        session.connection(),
    )
    if benchmark_daily.empty:
        return daily_close_levels

    for symbol in benchmark_bases:
        level_column = f"{symbol.lower()}_level"
        symbol_daily = benchmark_daily[benchmark_daily["symbol"] == symbol].copy()
        if symbol_daily.empty:
            continue
        symbol_close_levels = daily_close_levels_from_session_returns(
            rel_df,
            symbol_daily,
            daily_value_column="adj_close",
            output_column=level_column,
        )
        if symbol_close_levels.empty:
            continue
        if daily_close_levels.empty:
            daily_close_levels = symbol_close_levels.copy()
        else:
            daily_close_levels = daily_close_levels.merge(
                symbol_close_levels,
                on="date",
                how="outer",
            )
    return daily_close_levels


def _load_benchmark_bases(session, rel_df: pd.DataFrame, start_date) -> dict[str, float]:
    benchmark_bases = {}
    for symbol in ("QQQ", "NVDA"):
        close_column = f"{symbol.lower()}_level"
        if close_column not in rel_df or rel_df[close_column].isna().all():
            continue
        intraday_bench = (
            session.query(PriceBar.adj_close)
            .join(Company, Company.id == PriceBar.company_id)
            .filter(
                Company.symbol == symbol,
                PriceBar.provider == settings.market_data_provider,
                PriceBar.interval == "15m",
                PriceBar.bar_time >= start_date,
            )
            .order_by(PriceBar.bar_time.asc())
            .first()
        )
        if intraday_bench and intraday_bench[0]:
            benchmark_bases[symbol] = float(intraday_bench[0])
    return benchmark_bases
