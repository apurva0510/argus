from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from sqlalchemy import select

from argus.core.db import session_scope
from argus.core.models import Company, JobRun
from argus.core.settings import settings
from argus.pipelines.job_runs import job_run_context
from argus.pipelines.news_items import stable_article_key, upsert_news_item as _upsert_news_item
from argus.pipelines.provider_health import (
    disabled_message,
    is_provider_available,
    get_provider_health,
    execute_provider_request,
)
from argus.sources.base import BaseNewsProvider
from argus.sources.gdelt_client import GdeltNewsProvider, fetch_gdelt_news_query
from argus.sources.news_rss_client import (
    NewsProviderRateLimitError,
    YahooRssNewsProvider,
    fetch_rss_news_query,
)

logger = logging.getLogger(__name__)
fetch_rss_news = fetch_rss_news_query
fetch_gdelt_news = fetch_gdelt_news_query


class refresh_news_rss_provider(YahooRssNewsProvider):
    def fetch_news(self, query: str) -> list[dict]:
        return fetch_rss_news(query)


class refresh_news_gdelt_provider(GdeltNewsProvider):
    def fetch_news(self, query: str) -> list[dict]:
        return fetch_gdelt_news(query, timespan="1d")


NEWS_PROVIDERS: list[BaseNewsProvider] = [
    refresh_news_rss_provider(),
    refresh_news_gdelt_provider(),
]


NEWS_QUERIES = [
    "data center AI infrastructure power demand grid",
    "liquid cooling data center AI servers",
    "optical networking data center AI",
    "semiconductor equipment AI capex",
    "nuclear power data center electricity",
    "hyperscaler capex AI infrastructure",
]

def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _job_error_text(
    *,
    failed_queries: list[str],
    failed_providers: list[str],
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
    else:
        sub_parts = []
        if failed_queries:
            sub_parts.append(f"failed_queries={', '.join(sorted(set(failed_queries)))}")
        if failed_providers:
            sub_parts.append(f"failed_providers={', '.join(sorted(set(failed_providers)))}")
        if sub_parts:
            parts.append("; ".join(sub_parts))

    return "; ".join(parts) if parts else None


def _last_successful_refresh_at(session) -> datetime | None:
    return (
        session.query(JobRun.finished_at)
        .filter(JobRun.job_name == "refresh_news", JobRun.status == "success")
        .order_by(JobRun.finished_at.desc())
        .limit(1)
        .scalar()
    )


def _should_skip_refresh(session, *, force: bool, now: datetime) -> bool:
    if force:
        return False
    last_success = _last_successful_refresh_at(session)
    if last_success is None:
        return False
    min_age = timedelta(hours=max(0.0, float(settings.news_refresh_min_hours)))
    return now - last_success < min_age


def clean_company_name(name: str) -> str:
    """Removes common business suffixes from company name for keyword matching."""
    clean = name.lower()
    suffixes = [
        " corporation",
        " corp.",
        " corp",
        " inc.",
        " inc",
        " plc",
        " co.",
        " co",
        " holding",
        " holdings",
        " ltd.",
        " ltd",
    ]
    for suffix in suffixes:
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)].strip()
            break
    return clean


def _company_aliases(company: Company) -> list[str]:
    aliases = []
    clean_name = clean_company_name(company.name)
    if clean_name:
        aliases.append(clean_name)

    static_aliases = {
        "NVDA": ["nvidia"],
        "GOOGL": ["alphabet", "google"],
        "META": ["meta"],
        "MSFT": ["microsoft"],
        "AMZN": ["amazon", "aws"],
        "VRT": ["vertiv"],
        "GEV": ["ge vernova"],
        "ETN": ["eaton"],
        "PWR": ["quanta services"],
        "ANET": ["arista networks"],
        "AVGO": ["broadcom"],
        "MRVL": ["marvell"],
        "MU": ["micron"],
        "MCHP": ["microchip"],
    }
    aliases.extend(static_aliases.get(company.symbol.upper(), []))
    return sorted({alias.strip().lower() for alias in aliases if len(alias.strip()) > 3})


def detect_mentions_and_keywords(
    title: str, summary: str | None, companies: list[Company]
) -> list[dict]:
    """Detects company mentions and AI infrastructure keywords in news article text.

    Returns a list of mention configurations with company_id, ticker,
    is_primary_match, and matched_keywords.
    """
    text = f"{title} {summary or ''}".lower()
    original_text = f"{title} {summary or ''}"
    mentions = []

    # AI infra keywords to match
    infra_keywords = [
        "ai",
        "gpu",
        "data center",
        "datacenter",
        "liquid cooling",
        "semiconductor",
        "hbm",
        "advanced packaging",
        "power grid",
        "nuclear energy",
        "electricity",
        "nuclear",
        "utility",
        "fiber",
        "optical",
        "networking",
    ]

    matched_infra = [kw for kw in infra_keywords if re.search(r"\b" + re.escape(kw) + r"\b", text)]

    for comp in companies:
        symbol = comp.symbol.strip().upper()
        ticker_lower = symbol.lower()

        # Match exact ticker as a word.
        # Short tickers (length <= 3) must match case-sensitively in the original text.
        # Long tickers (length >= 4) match case-insensitively.
        if len(symbol) <= 3:
            ticker_match = re.search(r"\b" + re.escape(symbol) + r"\b", original_text)
        else:
            ticker_match = re.search(r"\b" + re.escape(ticker_lower) + r"\b", text)

        # Match clean company name and common aliases.
        name_match = False
        matched_alias = None
        for alias in _company_aliases(comp):
            if re.search(r"\b" + re.escape(alias) + r"\b", text):
                name_match = True
                matched_alias = alias
                break

        if ticker_match or name_match:
            matched_comp_kws = []
            if ticker_match:
                matched_comp_kws.append(comp.symbol)
            if matched_alias:
                matched_comp_kws.append(matched_alias.upper())

            all_kws = matched_comp_kws + matched_infra

            # Primary match if ticker or company name is found in the title
            if len(symbol) <= 3:
                ticker_in_title = bool(re.search(r"\b" + re.escape(symbol) + r"\b", title))
            else:
                ticker_in_title = bool(
                    re.search(r"\b" + re.escape(ticker_lower) + r"\b", title.lower())
                )

            name_in_title = False
            for alias in _company_aliases(comp):
                if re.search(r"\b" + re.escape(alias) + r"\b", title.lower()):
                    name_in_title = True
                    break

            is_primary = ticker_in_title or name_in_title

            mentions.append(
                {
                    "company_id": comp.id,
                    "ticker": comp.symbol,
                    "is_primary_match": is_primary,
                    "matched_keywords": ", ".join(all_kws) if all_kws else None,
                }
            )

    # Deduplicate mentions by company_id before returning
    seen_company_ids = set()
    unique_mentions = []
    for m in mentions:
        if m["company_id"] not in seen_company_ids:
            seen_company_ids.add(m["company_id"])
            unique_mentions.append(m)

    return unique_mentions


def _fetch_provider_query(provider: BaseNewsProvider, query: str) -> list[dict]:
    return provider.fetch_news(query)


def refresh_news(
    *,
    force: bool = False,
    bypass_recent_success: bool = False,
    max_queries: int | None = None,
    queries: list[str] | None = None,
) -> dict[str, object]:
    """Fetch and process theme-level news articles from RSS and GDELT.

    Detects mentions, maps keywords, and writes to database.
    """
    failed_queries: list[str] = []
    failed_providers: list[str] = []
    disabled_providers: set[str] = set()
    provider_outcomes: dict[str, str] = {}
    health_messages: list[str] = []

    with job_run_context("refresh_news") as state:
        with session_scope() as session:
            now = _utc_now()
            if _should_skip_refresh(
                session,
                force=force or bypass_recent_success,
                now=now,
            ):
                state.status = "skipped"
                state.error_text = "Skipped refresh_news because the last successful run is recent."
                return {
                    "status": state.status,
                    "rows_read": 0,
                    "rows_written": 0,
                    "failed_queries": [],
                    "failed_providers": [],
                    "error_text": state.error_text,
                }

            companies = session.scalars(select(Company).where(Company.is_active.is_(True))).all()

            for provider in NEWS_PROVIDERS:
                p_name = provider.name
                if force:
                    health = get_provider_health(session, p_name)
                    health.disabled_until = None
                    health.status = "healthy"
                    session.flush()

                if not is_provider_available(session, p_name, now):
                    provider_outcomes[p_name] = "cooldown"
                else:
                    provider_outcomes[p_name] = "success"

            global_unique_articles: dict[str, dict] = {}

            provider_queries = []
            for provider in NEWS_PROVIDERS:
                p_name = provider.name
                if queries is not None:
                    p_queries = list(queries)
                elif p_name == "rss":
                    p_queries = [c.symbol for c in companies if c.symbol]
                elif p_name == "gdelt":
                    p_queries = list(NEWS_QUERIES)
                else:
                    p_queries = []

                if max_queries is not None:
                    p_queries = p_queries[: max(0, max_queries)]

                for q in p_queries:
                    provider_queries.append((provider, q))

            for provider, query in provider_queries:
                p_name = provider.name
                if p_name in disabled_providers or provider_outcomes[p_name] == "cooldown":
                    failed_providers.append(p_name)
                    message = disabled_message(p_name)
                    if message not in health_messages:
                        health_messages.append(message)
                        logger.warning(message)
                    continue

                try:
                    fetched_articles = execute_provider_request(
                        session,
                        p_name,
                        _fetch_provider_query,
                        provider,
                        query,
                    )
                except NewsProviderRateLimitError as exc:
                    disabled_providers.add(p_name)
                    provider_outcomes[p_name] = "429"
                    message = disabled_message(p_name)
                    logger.warning("%s: %s", message, exc)
                    if message not in health_messages:
                        health_messages.append(message)
                    failed_queries.append(query)
                    failed_providers.append(p_name)
                    continue
                except Exception:
                    logger.exception("Failed to fetch %s news for query: %s", p_name, query)
                    failed_queries.append(query)
                    failed_providers.append(p_name)
                    if provider_outcomes[p_name] != "429":
                        provider_outcomes[p_name] = "failure"
                    continue

                state.rows_read += len(fetched_articles)
                for article in fetched_articles:
                    article["provider"] = p_name
                    global_unique_articles[stable_article_key(article)] = article


            # Process globally unique articles
            for art in global_unique_articles.values():
                # Check mentions across ALL active companies in DB
                mentions = detect_mentions_and_keywords(art["title"], art["summary"], companies)
                if mentions:
                    state.rows_written += _upsert_news_item(session, art, mentions)

            if failed_queries or failed_providers:
                if health_messages:
                    state.status = "partial_success"
                else:
                    state.status = "partial_success" if state.rows_written > 0 or state.rows_read > 0 else "failed"
                logger.warning(
                    "News refresh experienced failures for providers=%s queries=%s",
                    ",".join(sorted(set(failed_providers))),
                    ",".join(sorted(set(failed_queries))),
                )
                if health_messages:
                    state.error_text = "; ".join(health_messages)

            state.error_text = _job_error_text(
                failed_queries=failed_queries,
                failed_providers=failed_providers,
                provider_outcomes=provider_outcomes,
                error_text=state.error_text,
            )

    return {
        "status": state.status,
        "rows_read": state.rows_read,
        "rows_written": state.rows_written,
        "failed_queries": failed_queries,
        "failed_providers": failed_providers,
        "error_text": state.error_text if state.status == "failed" else ("; ".join(health_messages) if health_messages else None),
    }
