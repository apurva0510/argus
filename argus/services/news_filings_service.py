from __future__ import annotations

from datetime import date
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


def get_filtered_news(
    engine: Engine,
    ticker: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 100,
) -> pd.DataFrame:
    """Fetch news items applying filters for ticker, source, keyword search, and date range.

    Returns a pandas DataFrame.
    """
    dialect_name = engine.dialect.name
    if dialect_name == "postgresql":
        tickers_agg = "string_agg(DISTINCT nm2.ticker, ',')"
        keywords_agg = "string_agg(DISTINCT nm3.matched_keywords, ',')"
        date_cast_published = "CAST(ni.published_at AS DATE)"
    else:
        tickers_agg = "group_concat(DISTINCT nm2.ticker)"
        keywords_agg = "group_concat(DISTINCT nm3.matched_keywords)"
        date_cast_published = "date(ni.published_at)"

    query = f"""
        SELECT DISTINCT
            ni.id,
            ni.published_at,
            ni.title,
            ni.summary,
            ni.url,
            ni.source_name,
            ni.provider,
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


def get_all_news_sources(engine: Engine) -> list[str]:
    """Retrieves all unique source names from the news items table."""
    query = "SELECT DISTINCT source_name FROM news_items WHERE source_name IS NOT NULL ORDER BY source_name"
    with engine.connect() as conn:
        df = pd.read_sql_query(text(query), conn)
        return df["source_name"].tolist()


def get_last_job_run(engine: Engine, job_name: str) -> dict[str, object] | None:
    """Retrieves the details of the last execution for the specified job."""
    query = """
        SELECT started_at, finished_at, status, rows_read, rows_written, error_text
        FROM job_runs
        WHERE job_name = :job_name
        ORDER BY id DESC LIMIT 1
    """
    with engine.connect() as conn:
        df = pd.read_sql_query(text(query), conn, params={"job_name": job_name})
        if df.empty:
            return None
        return df.iloc[0].to_dict()

