from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from argus.core.models import ProviderHealth
from argus.core.settings import settings


def provider_label(provider: str) -> str:
    labels = {
        "gdelt": "GDELT",
        "rss": "RSS",
        "ir_feed": "IR feeds",
    }
    return labels.get(provider.lower(), provider.upper())


def disabled_message(provider: str) -> str:
    return f"{provider_label(provider)} disabled until tomorrow due to rate limit"


def get_provider_health(session: Session, provider: str) -> ProviderHealth:
    provider_key = provider.strip().lower()
    health = (
        session.query(ProviderHealth)
        .filter(ProviderHealth.provider == provider_key)
        .one_or_none()
    )
    if health is None:
        health = ProviderHealth(provider=provider_key, status="healthy", failure_count=0)
        session.add(health)
        session.flush()
    return health


def is_provider_available(session: Session, provider: str, now: datetime) -> bool:
    health = get_provider_health(session, provider)
    return not (health.disabled_until and health.disabled_until > now)


def mark_provider_success(session: Session, provider: str, now: datetime) -> None:
    health = get_provider_health(session, provider)
    health.status = "healthy"
    health.last_success_at = now
    health.disabled_until = None
    health.last_error = None


def mark_provider_rate_limited(session: Session, provider: str, now: datetime) -> str:
    health = get_provider_health(session, provider)
    health.status = "unhealthy"
    health.last_failure_at = now
    health.failure_count = int(health.failure_count or 0) + 1
    health.disabled_until = now + timedelta(hours=max(1.0, float(settings.provider_disable_hours)))
    health.last_error = disabled_message(provider)
    return health.last_error


def record_provider_attempt(
    session: Session,
    provider: str,
    outcome: str,  # "success", "failure", "rate_limit"
    now: datetime,
    error_message: str | None = None,
) -> None:
    """Record a provider request attempt, updating both provider_daily_usage and provider_health."""
    provider_key = provider.strip().lower()
    today_date = now.date()

    from argus.core.models import ProviderDailyUsage

    usage = (
        session.query(ProviderDailyUsage)
        .filter(ProviderDailyUsage.provider == provider_key, ProviderDailyUsage.date == today_date)
        .one_or_none()
    )
    if usage is None:
        usage = ProviderDailyUsage(
            provider=provider_key,
            date=today_date,
            request_count=0,
            success_count=0,
            failure_count=0,
            rate_limit_count=0,
        )
        session.add(usage)
        session.flush()

    usage.request_count += 1
    usage.last_request_time = now

    if outcome == "success":
        usage.success_count += 1
    elif outcome == "rate_limit":
        usage.rate_limit_count += 1
    else:
        usage.failure_count += 1

    # Update Provider Health (retain cooldown and last-error state)
    if outcome == "success":
        mark_provider_success(session, provider_key, now)
    elif outcome == "rate_limit":
        mark_provider_rate_limited(session, provider_key, now)
    else:
        health = get_provider_health(session, provider_key)
        health.status = "unhealthy"
        health.last_failure_at = now
        health.failure_count = int(health.failure_count or 0) + 1
        health.last_error = error_message or "General failure"


def execute_provider_request(
    session: Session,
    provider: str,
    func,
    *args,
    **kwargs,
):
    """Executes a provider request callable and records usage and health."""
    provider_key = provider.strip().lower()
    now = datetime.now(UTC).replace(tzinfo=None)

    outcome = "success"
    error_msg = None
    try:
        result = func(*args, **kwargs)
        record_provider_attempt(session, provider_key, "success", now)
        return result
    except Exception as exc:
        from argus.sources.news_rss_client import NewsProviderRateLimitError

        is_429 = False
        if isinstance(exc, NewsProviderRateLimitError):
            is_429 = True
        elif hasattr(exc, "status_code") and exc.status_code == 429:
            is_429 = True
        elif (
            hasattr(exc, "response")
            and hasattr(exc.response, "status_code")
            and exc.response.status_code == 429
        ):
            is_429 = True

        if is_429:
            outcome = "rate_limit"
            error_msg = str(exc)
        else:
            outcome = "failure"
            error_msg = f"{type(exc).__name__}: {str(exc)}"

        record_provider_attempt(session, provider_key, outcome, now, error_message=error_msg)
        raise

