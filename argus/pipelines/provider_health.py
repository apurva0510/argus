from __future__ import annotations

from datetime import datetime, timedelta

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
