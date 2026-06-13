from __future__ import annotations

from datetime import date
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from argus.core.sql import date_cast, distinct_string_agg


def get_filtered_news(
    engine: Engine,
    ticker: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    min_relevance: float | None = None,
    sentiment_band: str | None = None,
    limit: int = 100,
) -> pd.DataFrame:
    """Fetch news items applying filters for ticker, source, keyword search, and date range.

    Returns a pandas DataFrame.
    """
    dialect_name = engine.dialect.name
    tickers_agg = distinct_string_agg(dialect_name, "nm2.ticker")
    keywords_agg = distinct_string_agg(dialect_name, "nm3.matched_keywords")
    date_cast_published = date_cast(dialect_name, "ni.published_at")

    query = f"""
        SELECT DISTINCT
            ni.id,
            ni.published_at,
            ni.title,
            ni.summary,
            ni.url,
            ni.source_name,
            ni.provider,
            ni.sentiment_score,
            ni.relevance_score,
            ni.sentiment_explanation,
            (
                SELECT {tickers_agg}
                FROM news_mentions nm2
                WHERE nm2.news_id = ni.id
            ) as tickers,
            (
                SELECT {keywords_agg}
                FROM news_mentions nm3
                WHERE nm3.news_id = ni.id
            ) as keywords
        FROM news_items ni
        LEFT JOIN news_mentions nm ON nm.news_id = ni.id
        LEFT JOIN companies c ON c.id = nm.company_id
        WHERE 1=1
    """
    params: dict[str, object] = {}

    if ticker and ticker != "All":
        query += " AND c.symbol = :ticker"
        params["ticker"] = ticker

    if source and source != "All":
        query += " AND ni.source_name = :source"
        params["source"] = source

    if keyword and keyword.strip():
        query += " AND (ni.title LIKE :keyword_like OR ni.summary LIKE :keyword_like OR nm.matched_keywords LIKE :keyword_like)"
        params["keyword_like"] = f"%{keyword.strip()}%"

    if start_date:
        query += f" AND {date_cast_published} >= :start_date"
        params["start_date"] = start_date.isoformat()

    if end_date:
        query += f" AND {date_cast_published} <= :end_date"
        params["end_date"] = end_date.isoformat()

    if min_relevance is not None:
        query += " AND ni.relevance_score >= :min_relevance"
        params["min_relevance"] = min_relevance

    if sentiment_band and sentiment_band != "All":
        if sentiment_band == "Positive":
            query += " AND ni.sentiment_score > 0.05"
        elif sentiment_band == "Negative":
            query += " AND ni.sentiment_score < -0.05"
        elif sentiment_band == "Neutral":
            query += " AND ni.sentiment_score >= -0.05 AND ni.sentiment_score <= 0.05"

    query += " ORDER BY ni.published_at DESC LIMIT :limit"
    params["limit"] = limit

    with engine.connect() as conn:
        return pd.read_sql_query(text(query), conn, params=params)


def get_filtered_filings(
    engine: Engine,
    ticker: str | None = None,
    form: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 100,
) -> pd.DataFrame:
    """Fetch SEC filings applying filters for ticker, form type, and date range.

    Returns a pandas DataFrame.
    """
    query = """
        SELECT
            sf.id,
            c.symbol,
            c.name as company_name,
            sf.accession_no,
            sf.form,
            sf.filing_date,
            sf.acceptance_datetime,
            sf.primary_doc_url,
            sf.filing_detail_url,
            sf.is_new
        FROM sec_filings sf
        JOIN companies c ON c.id = sf.company_id
        WHERE 1=1
    """
    params: dict[str, object] = {}

    if ticker and ticker != "All":
        query += " AND c.symbol = :ticker"
        params["ticker"] = ticker

    if form and form != "All":
        query += " AND sf.form = :form"
        params["form"] = form

    if start_date:
        query += " AND sf.filing_date >= :start_date"
        params["start_date"] = start_date.isoformat()

    if end_date:
        query += " AND sf.filing_date <= :end_date"
        params["end_date"] = end_date.isoformat()

    query += " ORDER BY sf.filing_date DESC, sf.acceptance_datetime DESC LIMIT :limit"
    params["limit"] = limit

    with engine.connect() as conn:
        return pd.read_sql_query(text(query), conn, params=params)
