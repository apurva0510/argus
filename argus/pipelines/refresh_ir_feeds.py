from __future__ import annotations

from datetime import UTC, datetime
import logging
import time

import feedparser
import httpx
from sqlalchemy import select

from argus.core.db import session_scope
from argus.core.models import Company
from argus.core.settings import settings
from argus.pipelines.job_runs import job_run_context
from argus.pipelines.provider_health import (
    disabled_message,
    is_provider_available,
    get_provider_health,
    execute_provider_request,
)
from argus.pipelines.news_items import upsert_news_item
from argus.pipelines.refresh_news import detect_mentions_and_keywords
from argus.sources.news_rss_client import NewsProviderRateLimitError

logger = logging.getLogger(__name__)
_last_ir_request_at = 0.0

IR_FEED_URLS = {
    "ANET": "https://investors.arista.com/rss/news-releases.xml",
    "CIEN": "https://investor.ciena.com/rss/news-releases.xml",
    "COHR": "https://investors.coherent.com/rss/news-releases.xml",
    "CRWD": "https://ir.crowdstrike.com/rss/news-releases.xml",
    "CSCO": "https://newsroom.cisco.com/c/r/newsroom/en/us/rss-feeds/newsroom-rss-feed.xml",
    "FTNT": "https://investor.fortinet.com/rss/news-releases.xml",
    "GLW": "https://investor.corning.com/rss/news-releases.xml",
    "LITE": "https://investor.lumentum.com/rss/news-releases.xml",
    "NET": "https://cloudflare.net/news/news-releases/rss",
    "PANW": "https://investors.paloaltonetworks.com/rss/news-releases.xml",
    "ZS": "https://ir.zscaler.com/rss/news-releases.xml",
}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _rate_limit() -> None:
    global _last_ir_request_at
    delay = max(0.0, float(settings.news_request_delay_seconds))
    elapsed = time.monotonic() - _last_ir_request_at
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_ir_request_at = time.monotonic()


def _job_error_text(
    provider_outcomes: dict[str, str] | None = None,
    error_text: str | None = None,
) -> str | None:
    parts = []
    if provider_outcomes:
        outcome_parts = [
            f"{p}={status_val}" for p, status_val in sorted(provider_outcomes.items())
        ]
        parts.append(f"provider_outcomes: {', '.join(outcome_parts)}")

    if error_text:
        parts.append(error_text)

    return "; ".join(parts) if parts else None


def fetch_ir_feed(symbol: str, url: str) -> list[dict]:
    _rate_limit()
    response = httpx.get(
        url,
        headers={"User-Agent": "Argus/0.1 IR feed monitor"},
        follow_redirects=True,
        timeout=10.0,
    )
    if response.status_code == 404:
        logger.warning("IR feed not found for %s: %s", symbol, url)
        return []
    if response.status_code == 429:
        raise NewsProviderRateLimitError("ir_feed", symbol)
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    entries = feed.get("entries", [])
    items = []
    for entry in entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue
        summary = entry.get("summary") or entry.get("description")
        if summary:
            summary = summary.strip()
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            published_at = datetime(*published_parsed[:6], tzinfo=UTC).replace(tzinfo=None)
        else:
            published_at = _utc_now()
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "source_name": f"{symbol} investor relations",
                "provider": "ir_feed",
                "published_at": published_at,
            }
        )
    return items


def refresh_ir_feeds(*, force: bool = False) -> dict[str, object]:
    errors: list[str] = []
    provider_outcomes: dict[str, str] = {}

    with job_run_context("refresh_ir_feeds") as state:
        with session_scope() as session:
            now = _utc_now()
            companies = session.scalars(
                select(Company).where(
                    Company.is_active.is_(True),
                    Company.symbol.in_(sorted(IR_FEED_URLS)),
                )
            ).all()
            companies_by_symbol = {company.symbol.upper(): company for company in companies}
            all_companies = session.scalars(
                select(Company).where(Company.is_active.is_(True))
            ).all()

            if force:
                health = get_provider_health(session, "ir_feed")
                health.disabled_until = None
                health.status = "healthy"
                session.flush()

            if not is_provider_available(session, "ir_feed", now):
                provider_outcomes["ir_feed"] = "cooldown"
            else:
                provider_outcomes["ir_feed"] = "success"

            for symbol, url in IR_FEED_URLS.items():
                company = companies_by_symbol.get(symbol)
                if company is None:
                    continue
                if provider_outcomes["ir_feed"] == "cooldown":
                    message = disabled_message("ir_feed")
                    logger.warning(message)
                    errors.append(message)
                    break

                try:
                    articles = execute_provider_request(
                        session,
                        "ir_feed",
                        fetch_ir_feed,
                        symbol,
                        url,
                    )
                except NewsProviderRateLimitError as exc:
                    provider_outcomes["ir_feed"] = "429"
                    message = disabled_message("ir_feed")
                    logger.warning("%s: %s", message, exc)
                    errors.append(message)
                    break
                except Exception as exc:
                    logger.warning("IR feed failed for %s: %s", symbol, exc)
                    errors.append(f"{symbol}: {exc}")
                    if provider_outcomes["ir_feed"] != "429":
                        provider_outcomes["ir_feed"] = "failure"
                    continue

                state.rows_read += len(articles)
                for article in articles:
                    mentions = detect_mentions_and_keywords(
                        article["title"],
                        article["summary"],
                        all_companies,
                    )
                    if not any(mention["company_id"] == company.id for mention in mentions):
                        mentions.append(
                            {
                                "company_id": company.id,
                                "ticker": company.symbol,
                                "is_primary_match": True,
                                "matched_keywords": company.symbol,
                            }
                        )
                    state.rows_written += upsert_news_item(session, article, mentions)

            if errors:
                has_provider_cooldown = any(
                    "disabled until tomorrow due to rate limit" in error for error in errors
                )
                state.status = (
                    "partial_success"
                    if has_provider_cooldown or state.rows_read or state.rows_written
                    else "failed"
                )

            state.error_text = _job_error_text(
                provider_outcomes=provider_outcomes,
                error_text="; ".join(dict.fromkeys(errors)) if errors else None,
            )

    return {
        "status": state.status,
        "rows_read": state.rows_read,
        "rows_written": state.rows_written,
        "error_text": state.error_text,
    }
