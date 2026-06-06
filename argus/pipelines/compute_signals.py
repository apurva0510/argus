from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging

import numpy as np
import pandas as pd
from sqlalchemy import select

from argus.analytics.news_signals import mention_relevance, recency_weight, score_news_article
from argus.core.db import get_insert_statement_producer, session_scope
from argus.core.models import (
    CapexObservation,
    Company,
    EarningsEvent,
    JobRun,
    MacroObservation,
    NewsItem,
    NewsMention,
    PriceBar,
    SignalDaily,
    utc_now,
)
from argus.core.settings import settings

logger = logging.getLogger(__name__)

HYPERSCALER_SYMBOLS = ("MSFT", "AMZN", "GOOGL", "META")
SIGNAL_COLUMNS = [
    "sentiment_proxy_7d",
    "news_relevance_7d",
    "corr_nvda_60d",
    "corr_hyperscaler_60d",
    "earnings_sensitivity",
    "power_signal",
    "capex_signal",
]


def _create_job_run() -> int:
    with session_scope() as session:
        job = JobRun(job_name="compute_signals", started_at=utc_now(), status="running")
        session.add(job)
        session.flush()
        return job.id


def _finish_job_run(
    job_id: int,
    *,
    status: str,
    rows_read: int,
    rows_written: int,
    error_text: str | None = None,
) -> None:
    with session_scope() as session:
        job = session.get(JobRun, job_id)
        if job is None:
            job = JobRun(id=job_id, job_name="compute_signals", started_at=utc_now(), status=status)
            session.add(job)
        job.finished_at = utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        job.error_text = error_text


def compute_signals(*, as_of_date: date | None = None) -> dict[str, object]:
    job_id = _create_job_run()
    rows_read = 0
    rows_written = 0
    status = "success"
    error_text: str | None = None

    try:
        with session_scope() as session:
            companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()
            rows_read = len(companies)
            if not companies:
                return {"status": status, "rows_read": 0, "rows_written": 0, "error_text": None}

            prices = _load_daily_prices(session)
            if prices.empty:
                return {
                    "status": status,
                    "rows_read": rows_read,
                    "rows_written": 0,
                    "error_text": None,
                }

            signal_date = as_of_date or prices["date"].max().date()
            returns = _build_return_frame(prices, signal_date)
            nvda_returns = returns.get("NVDA")
            hyperscaler_returns = _hyperscaler_basket_returns(returns)
            capex_signal = _latest_capex_signal(session)
            power_signal = _compute_power_signal(session)
            earnings_events = _load_reference_earnings_events(session, signal_date)
            signal_rows = []

            for company in companies:
                symbol = company.symbol.upper()
                company_returns = returns.get(symbol)
                company_prices = _price_series_for_symbol(prices, symbol, signal_date)
                news_scores = _company_news_scores(session, company.id, signal_date)
                row = {
                    "company_id": company.id,
                    "date": signal_date,
                    "sentiment_proxy_7d": news_scores["sentiment_proxy_7d"],
                    "news_relevance_7d": news_scores["news_relevance_7d"],
                    "corr_nvda_60d": _rolling_corr(company_returns, nvda_returns, window=60),
                    "corr_hyperscaler_60d": _rolling_corr(
                        company_returns,
                        hyperscaler_returns,
                        window=60,
                    ),
                    "earnings_sensitivity": _earnings_sensitivity(company_prices, earnings_events),
                    "power_signal": power_signal,
                    "capex_signal": capex_signal,
                }
                signal_rows.append(_clean_row(row))

            rows_written = _upsert_signal_rows(session, signal_rows)
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("Signal computation failed")
    finally:
        _finish_job_run(
            job_id,
            status=status,
            rows_read=rows_read,
            rows_written=rows_written,
            error_text=error_text,
        )

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "error_text": error_text,
    }


def _load_daily_prices(session) -> pd.DataFrame:
    rows = (
        session.query(Company.symbol, PriceBar.date, PriceBar.adj_close)
        .join(Company, Company.id == PriceBar.company_id)
        .filter(
            PriceBar.provider == settings.market_data_provider,
            PriceBar.interval == "1d",
        )
        .order_by(PriceBar.date.asc(), Company.symbol.asc())
        .all()
    )
    frame = pd.DataFrame(rows, columns=["symbol", "date", "adj_close"])
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "date", "adj_close"])
    frame["symbol"] = frame["symbol"].str.upper()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["adj_close"] = pd.to_numeric(frame["adj_close"], errors="coerce")
    return frame.dropna(subset=["symbol", "date", "adj_close"])


def _build_return_frame(prices: pd.DataFrame, signal_date: date) -> pd.DataFrame:
    filtered = prices[prices["date"] <= pd.Timestamp(signal_date)]
    pivot = filtered.pivot_table(index="date", columns="symbol", values="adj_close", aggfunc="last")
    return pivot.sort_index().pct_change(fill_method=None)


def _price_series_for_symbol(prices: pd.DataFrame, symbol: str, signal_date: date) -> pd.Series:
    frame = prices[
        (prices["symbol"] == symbol) & (prices["date"] <= pd.Timestamp(signal_date))
    ].sort_values("date")
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.set_index("date")["adj_close"].astype(float)


def _hyperscaler_basket_returns(returns: pd.DataFrame) -> pd.Series | None:
    available = [symbol for symbol in HYPERSCALER_SYMBOLS if symbol in returns.columns]
    if set(available) != set(HYPERSCALER_SYMBOLS):
        return None
    basket = returns[list(HYPERSCALER_SYMBOLS)]
    return basket.dropna(how="any").mean(axis=1)


def _rolling_corr(
    company_returns: pd.Series | None,
    benchmark_returns: pd.Series | None,
    *,
    window: int,
) -> float | None:
    if company_returns is None or benchmark_returns is None:
        return None
    aligned = pd.concat([company_returns, benchmark_returns], axis=1).dropna()
    if len(aligned) < window:
        return None
    corr = aligned.iloc[-window:, 0].corr(aligned.iloc[-window:, 1])
    if pd.isna(corr):
        return None
    return float(corr)


def _company_news_scores(session, company_id: int, signal_date: date) -> dict[str, float | None]:
    start_dt = datetime.combine(signal_date - timedelta(days=7), time.min)
    as_of_dt = datetime.combine(signal_date, time.max)
    rows = (
        session.query(NewsItem, NewsMention)
        .join(NewsMention, NewsMention.news_id == NewsItem.id)
        .filter(
            NewsMention.company_id == company_id,
            NewsItem.published_at >= start_dt,
            NewsItem.published_at <= as_of_dt,
        )
        .all()
    )
    if not rows:
        return {"sentiment_proxy_7d": None, "news_relevance_7d": None}

    weighted_sentiment = []
    weighted_relevance = []
    for item, mention in rows:
        current_mention = {
            "is_primary_match": mention.is_primary_match,
            "matched_keywords": mention.matched_keywords,
        }
        if item.sentiment_score is None or item.relevance_score is None:
            sentiment_score, relevance_score = score_news_article(
                item.title,
                item.summary,
                [current_mention],
            )
            item.sentiment_score = sentiment_score
            item.relevance_score = relevance_score
        weight = recency_weight(item.published_at, as_of_dt)
        if item.sentiment_score is not None:
            weighted_sentiment.append((float(item.sentiment_score), weight))
        weighted_relevance.append((mention_relevance(current_mention), weight))

    return {
        "sentiment_proxy_7d": _weighted_average(weighted_sentiment),
        "news_relevance_7d": _weighted_average(weighted_relevance),
    }


def _weighted_average(values: list[tuple[float, float]]) -> float | None:
    if not values:
        return None
    total_weight = sum(weight for _, weight in values)
    if total_weight == 0:
        return None
    return sum(value * weight for value, weight in values) / total_weight


def _load_reference_earnings_events(session, signal_date: date) -> list[date]:
    rows = (
        session.query(EarningsEvent.event_date)
        .join(Company, Company.id == EarningsEvent.company_id)
        .filter(
            Company.symbol.in_(("NVDA", *HYPERSCALER_SYMBOLS)),
            EarningsEvent.event_date <= signal_date,
        )
        .order_by(EarningsEvent.event_date.asc())
        .all()
    )
    return [row[0] for row in rows]


def _earnings_sensitivity(price_series: pd.Series, event_dates: list[date]) -> float | None:
    if price_series.empty or len(event_dates) < 4:
        return None
    returns = []
    for event_date in event_dates:
        start = _last_price_before(price_series, event_date)
        end = _nth_price_on_or_after(price_series, event_date, 3)
        if start is None or end is None or start == 0:
            continue
        returns.append((end / start) - 1.0)
    if len(returns) < 4:
        return None
    return float(np.mean(returns))


def _last_price_before(price_series: pd.Series, event_date: date) -> float | None:
    prior = price_series[price_series.index.date < event_date]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def _nth_price_on_or_after(price_series: pd.Series, event_date: date, offset: int) -> float | None:
    after = price_series[price_series.index.date >= event_date]
    if len(after) <= offset:
        return None
    return float(after.iloc[offset])


def _latest_capex_signal(session) -> float | None:
    rows = (
        session.query(
            Company.symbol, CapexObservation.fiscal_period_end, CapexObservation.capex_amount
        )
        .join(Company, Company.id == CapexObservation.company_id)
        .filter(Company.symbol.in_(HYPERSCALER_SYMBOLS))
        .order_by(CapexObservation.fiscal_period_end.asc())
        .all()
    )
    if not rows:
        return None
    frame = pd.DataFrame(rows, columns=["symbol", "fiscal_period_end", "capex_amount"])
    frame["fiscal_period_end"] = pd.to_datetime(frame["fiscal_period_end"])
    frame["capex_amount"] = pd.to_numeric(frame["capex_amount"], errors="coerce")
    frame = frame.dropna(subset=["fiscal_period_end", "capex_amount"])
    if frame.empty:
        return None
    frame["period_q"] = frame["fiscal_period_end"].dt.to_period("Q")
    grouped = (
        frame.groupby("period_q", as_index=False)
        .agg(
            capex_amount=("capex_amount", "sum"),
            symbols=("symbol", lambda values: frozenset(str(value).upper() for value in values)),
        )
        .sort_values("period_q")
    )
    latest = grouped.iloc[-1]
    prior = grouped[grouped["period_q"] == latest["period_q"] - 4]
    if prior.empty or float(prior.iloc[0]["capex_amount"]) == 0:
        return None
    if set(latest["symbols"]) != set(HYPERSCALER_SYMBOLS):
        return None
    if latest["symbols"] != prior.iloc[0]["symbols"]:
        return None
    return (float(latest["capex_amount"]) / float(prior.iloc[0]["capex_amount"])) - 1.0


def _compute_power_signal(session) -> float | None:
    """Compute power signal from EIA electricity price and demand data.

    Returns the average YoY change of monthly retail price and 7-day average demand.
    Returns None if sufficient EIA data is unavailable.
    """
    rows = (
        session.query(
            MacroObservation.series_code, MacroObservation.observation_date, MacroObservation.value
        )
        .filter(MacroObservation.series_code.in_(["EIA_ELEC_PRICE", "EIA_ELEC_DEMAND"]))
        .order_by(MacroObservation.observation_date.asc())
        .all()
    )
    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["series_code", "observation_date", "value"])
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["observation_date", "value"])

    price_df = df[df["series_code"] == "EIA_ELEC_PRICE"].sort_values("observation_date")
    demand_df = df[df["series_code"] == "EIA_ELEC_DEMAND"].sort_values("observation_date")

    if price_df.empty or demand_df.empty:
        return None

    # Compute price YoY
    latest_price_row = price_df.iloc[-1]
    latest_price_date = latest_price_row["observation_date"]
    latest_price_val = latest_price_row["value"]

    prior_price_df = price_df[
        (price_df["observation_date"] >= latest_price_date - pd.Timedelta(days=380))
        & (price_df["observation_date"] <= latest_price_date - pd.Timedelta(days=340))
    ]
    if prior_price_df.empty:
        return None

    prior_price_df = prior_price_df.copy()
    prior_price_df["diff"] = (
        prior_price_df["observation_date"] - (latest_price_date - pd.Timedelta(days=365))
    ).abs()
    prior_price_val = prior_price_df.sort_values("diff").iloc[0]["value"]
    if prior_price_val == 0:
        return None
    price_yoy = (latest_price_val / prior_price_val) - 1.0

    # Compute demand YoY using 7-day average to smooth day-of-week fluctuations
    latest_demand_row = demand_df.iloc[-1]
    latest_demand_date = latest_demand_row["observation_date"]

    latest_demand_7d = demand_df[
        (demand_df["observation_date"] >= latest_demand_date - pd.Timedelta(days=6))
        & (demand_df["observation_date"] <= latest_demand_date)
    ]
    if len(latest_demand_7d) < 5:
        return None
    latest_demand_val = latest_demand_7d["value"].mean()

    prior_demand_date = latest_demand_date - pd.Timedelta(days=365)
    prior_demand_7d = demand_df[
        (demand_df["observation_date"] >= prior_demand_date - pd.Timedelta(days=6))
        & (demand_df["observation_date"] <= prior_demand_date)
    ]
    if len(prior_demand_7d) < 5:
        return None
    prior_demand_val = prior_demand_7d["value"].mean()
    if prior_demand_val == 0:
        return None
    demand_yoy = (latest_demand_val / prior_demand_val) - 1.0

    return float((price_yoy + demand_yoy) / 2.0)


def _upsert_signal_rows(session, rows: list[dict]) -> int:
    if not rows:
        return 0
    insert = get_insert_statement_producer(session)
    statement = insert(SignalDaily).values(rows)
    update_values = {column: getattr(statement.excluded, column) for column in SIGNAL_COLUMNS}
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "date"],
        set_=update_values,
    )
    session.execute(statement)
    return len(rows)


def _clean_row(row: dict) -> dict:
    cleaned = {}
    for key, value in row.items():
        if value is pd.NA or value is None:
            cleaned[key] = None
        elif isinstance(value, np.generic):
            cleaned[key] = value.item()
        elif pd.isna(value):
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned
