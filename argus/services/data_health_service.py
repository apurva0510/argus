from __future__ import annotations

from datetime import date
import pandas as pd
from sqlalchemy import text, Engine


def load_data_health_info(engine: Engine, today: date) -> dict[str, pd.DataFrame]:
    """Retrieve all diagnostic data frames representing database and pipeline health."""
    data = {}

    with engine.connect() as conn:
        # 1. Pipeline status
        data["pipeline_status"] = pd.read_sql_query(
            text(
                """
                SELECT jr.job_name, jr.started_at, jr.finished_at, jr.status, jr.rows_read, jr.rows_written, jr.error_text
                FROM job_runs jr
                JOIN (
                    SELECT job_name, MAX(id) as max_id
                    FROM job_runs
                    GROUP BY job_name
                ) latest ON jr.id = latest.max_id
                ORDER BY jr.job_name ASC
                """
            ),
            conn,
        )

        # 2. Provider Health
        data["provider_health"] = pd.read_sql_query(
            text(
                """
                SELECT provider, status, failure_count, disabled_until, last_success_at, last_failure_at, last_error
                FROM provider_health
                ORDER BY provider ASC
                """
            ),
            conn,
        )

        # 3. Provider Daily Usage
        data["provider_usage"] = pd.read_sql_query(
            text(
                """
                SELECT provider, request_count, success_count, failure_count, rate_limit_count, last_request_time
                FROM provider_daily_usage
                WHERE date = :today
                ORDER BY provider ASC
                """
            ),
            conn,
            params={"today": today.isoformat()},
        )

        # 4. CIK Integrity
        data["cik_integrity"] = pd.read_sql_query(
            text(
                """
                SELECT symbol, name, CIK as cik
                FROM companies
                WHERE is_active = TRUE AND (CIK IS NULL OR CIK = '' OR LENGTH(CIK) != 10)
                ORDER BY symbol ASC
                """
            ),
            conn,
        )

        # 5. Recent Errors
        data["recent_errors"] = pd.read_sql_query(
            text(
                """
                SELECT id, job_name, started_at, finished_at, status, error_text
                FROM job_runs
                WHERE status = 'failed'
                ORDER BY id DESC
                LIMIT 10
                """
            ),
            conn,
        )

        # 6. Latest Dates/Times for Stale & Freshness Checks
        data["latest_prices"] = pd.read_sql_query(
            text("SELECT bar_time as val, interval FROM price_bars ORDER BY bar_time DESC LIMIT 1"),
            conn,
        )
        data["latest_metrics"] = pd.read_sql_query(
            text("SELECT MAX(date) as val FROM daily_metrics"), conn
        )
        data["latest_macro"] = pd.read_sql_query(
            text("SELECT MAX(observation_date) as val FROM macro_observations"), conn
        )
        data["latest_news"] = pd.read_sql_query(
            text("SELECT published_at as val FROM news_items ORDER BY published_at DESC LIMIT 1"),
            conn,
        )
        data["latest_filings"] = pd.read_sql_query(
            text(
                "SELECT COALESCE(acceptance_datetime, filing_date) as val, (acceptance_datetime IS NOT NULL) as has_time FROM sec_filings ORDER BY COALESCE(acceptance_datetime, filing_date) DESC LIMIT 1"
            ),
            conn,
        )
        data["latest_signals"] = pd.read_sql_query(
            text("SELECT MAX(date) as val FROM signal_daily"), conn
        )

    return data
