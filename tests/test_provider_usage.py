from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy.orm import Session

from argus.core.models import ProviderDailyUsage, ProviderHealth
from argus.pipelines.provider_health import execute_provider_request, record_provider_attempt
from argus.sources.news_rss_client import NewsProviderRateLimitError


def test_execute_provider_request_success(sqlite_engine) -> None:
    with Session(sqlite_engine) as session:
        # Success request
        result = execute_provider_request(
            session,
            "yfinance",
            lambda x: x + 1,
            2,
        )
        assert result == 3

        # Check DB
        usage = session.query(ProviderDailyUsage).filter_by(provider="yfinance").one()
        assert usage.request_count == 1
        assert usage.success_count == 1
        assert usage.failure_count == 0
        assert usage.rate_limit_count == 0
        assert usage.last_request_time is not None
        assert usage.date == datetime.now(UTC).date()

        health = session.query(ProviderHealth).filter_by(provider="yfinance").one()
        assert health.status == "healthy"
        assert health.last_success_at is not None
        assert health.disabled_until is None


def test_execute_provider_request_rate_limited(sqlite_engine) -> None:
    with Session(sqlite_engine) as session:

        def fail_rate_limit():
            raise NewsProviderRateLimitError("yfinance", "dummy")

        with pytest.raises(NewsProviderRateLimitError):
            execute_provider_request(session, "yfinance", fail_rate_limit)

        # Check DB
        usage = session.query(ProviderDailyUsage).filter_by(provider="yfinance").one()
        assert usage.request_count == 1
        assert usage.success_count == 0
        assert usage.failure_count == 0
        assert usage.rate_limit_count == 1
        assert usage.last_request_time is not None

        health = session.query(ProviderHealth).filter_by(provider="yfinance").one()
        assert health.status == "unhealthy"
        assert health.last_failure_at is not None
        assert health.disabled_until is not None


def test_execute_provider_request_general_failure(sqlite_engine) -> None:
    with Session(sqlite_engine) as session:

        def fail_general():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            execute_provider_request(session, "yfinance", fail_general)

        # Check DB
        usage = session.query(ProviderDailyUsage).filter_by(provider="yfinance").one()
        assert usage.request_count == 1
        assert usage.success_count == 0
        assert usage.failure_count == 1
        assert usage.rate_limit_count == 0
        assert usage.last_request_time is not None

        health = session.query(ProviderHealth).filter_by(provider="yfinance").one()
        assert health.status == "unhealthy"
        assert health.last_failure_at is not None
        assert "ValueError" in (health.last_error or "")


def test_execute_provider_request_across_multiple_dates(sqlite_engine) -> None:
    with Session(sqlite_engine) as session:
        now = datetime.now(UTC).replace(tzinfo=None)
        yesterday = now - timedelta(days=1)

        # Record yesterday attempt
        record_provider_attempt(session, "yfinance", "success", yesterday)
        # Record today attempt
        record_provider_attempt(session, "yfinance", "success", now)

        usages = (
            session.query(ProviderDailyUsage)
            .filter_by(provider="yfinance")
            .order_by(ProviderDailyUsage.date.asc())
            .all()
        )
        assert len(usages) == 2
        assert usages[0].date == yesterday.date()
        assert usages[0].request_count == 1
        assert usages[0].success_count == 1

        assert usages[1].date == now.date()
        assert usages[1].request_count == 1
        assert usages[1].success_count == 1
