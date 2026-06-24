from __future__ import annotations

from datetime import UTC, datetime
import logging
import time

import feedparser
import httpx
from sqlalchemy import select

from argus.core.db import session_scope
from argus.core.models import Company, WatchlistItem
from argus.core.settings import settings
from argus.pipelines.job_runs import job_run_context
from argus.pipelines.provider_health import (
    disabled_message,
    is_provider_available,
    get_provider_health,
    execute_provider_request,
)
from argus.pipelines.news_items import detect_mentions_and_keywords, upsert_news_item
from argus.sources.news_rss_client import NewsProviderRateLimitError

logger = logging.getLogger(__name__)
_last_ir_request_at = 0.0

IR_FEED_URLS = {
    "AMZN": "https://ir.aboutamazon.com/rss/news-releases.xml",
    "GOOGL": "https://abc.xyz/investor/news/rss.xml",
    "META": "https://investor.fb.com/rss/news-releases.xml",
    "MSFT": "https://www.microsoft.com/en-us/investor/rss/rssfeed.aspx?ContentType=Microsoft%20News",
}

OTHER_IR_FEED_URLS = {
    "NVDA": "https://nvidianews.nvidia.com/rss.xml",
    "MSFT": "https://www.microsoft.com/en-us/investor/rss/rssfeed.aspx?ContentType=Microsoft%20News",
    "AMZN": "https://ir.aboutamazon.com/rss/news-releases.xml",
    "GOOGL": "https://abc.xyz/investor/news/rss.xml",
    "META": "https://investor.fb.com/rss/news-releases.xml",
    "QQQ": "https://www.invesco.com/us/financial-products/etfs/product-detail?productId=ETF-QQQ",
    "AVGO": "https://investors.broadcom.com/rss/news-releases.xml",
    "MRVL": "https://investor.marvell.com/rss/news-releases.xml",
    "MU": "https://investors.micron.com/rss/news-releases.xml",
    "MCHP": "https://investor.microchip.com/rss/news-releases.xml",
    "ETN": "https://www.eaton.com/us/en-us/company/news-insights/news-releases.feed.xml",
    "GEV": "https://investors.gevernova.com/rss/news-releases.xml",
    "PWR": "https://investors.quantaservices.com/rss/news-releases.xml",
    "ABBNY": "https://global.abb/group/en/media/releases/rss.xml",
    "SBGSY": "https://www.se.com/ww/en/about-us/newsroom/rss-feeds.xml",
    "SIEGY": "https://press.siemens.com/global/en/pressreleases.xml",
    "HUBB": "https://investors.hubbell.com/rss/news-releases.xml",
    "VRT": "https://investors.vertiv.com/rss/news-releases.xml",
    "TT": "https://investors.tranetechnologies.com/rss/news-releases.xml",
    "CARR": "https://ir.carrier.com/rss/news-releases.xml",
    "JCI": "https://investors.johnsoncontrols.com/rss/news-releases.xml",
    "CIEN": "https://investor.ciena.com/rss/news-releases.xml",
    "GLW": "https://investor.corning.com/rss/news-releases.xml",
    "COHR": "https://investors.coherent.com/rss/news-releases.xml",
    "LITE": "https://investor.lumentum.com/rss/news-releases.xml",
    "NOK": "https://www.nokia.com/en_int/news/releases/rss.xml",
    "CSCO": "https://newsroom.cisco.com/c/r/newsroom/en/us/rss-feeds/newsroom-rss-feed.xml",
    "ANET": "https://investors.arista.com/rss/news-releases.xml",
    "AMAT": "https://ir.appliedmaterials.com/rss/news-releases.xml",
    "KLAC": "https://ir.kla.com/rss/news-releases.xml",
    "LRCX": "https://investor.lamresearch.com/rss/news-releases.xml",
    "ASML": "https://www.asml.com/en/news/press-releases/rss",
    "ONTO": "https://investors.ontoinnovation.com/rss/news-releases.xml",
    "TER": "https://investors.teradyne.com/rss/news-releases.xml",
    "CEG": "https://investors.constellationenergy.com/rss/news-releases.xml",
    "VST": "https://investor.vistracorp.com/rss/news-releases.xml",
    "NEE": "https://investor.nexteraenergy.com/rss/news-releases.xml",
    "CCJ": "https://www.cameco.com/invest/news/rss",
    "SMR": "https://nuscalepower.gcs-web.com/rss/news-releases.xml",
    "CRWD": "https://ir.crowdstrike.com/rss/news-releases.xml",
    "PANW": "https://investors.paloaltonetworks.com/rss/news-releases.xml",
    "FTNT": "https://investor.fortinet.com/rss/news-releases.xml",
    "NET": "https://cloudflare.net/news/news-releases/rss",
    "S": "https://investors.sentinelone.com/rss/news-releases.xml",
    "ZS": "https://ir.zscaler.com/rss/news-releases.xml",
    "IONQ": "https://investors.ionq.com/rss/news-releases.xml",
    "RGTI": "https://investors.rigetti.com/rss/news-releases.xml",
    "QBTS": "https://ir.dwavesys.com/rss/news-releases.xml",
    "QUBT": "https://quantumcomputinginc.com/feed",
    "INFQ": "https://infleqtion.com/news/rss",
    "IBM": "https://newsroom.ibm.com/announcements?pagetemplate=rss",
    "ALAB": "https://investors.asteralabs.com/rss/news-releases.xml",
    "CRDO": "https://investors.credosemi.com/rss/news-releases.xml",
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

            # Start with base/configured IR_FEED_URLS (which only contains hyperscalers by default)
            active_feeds = dict(IR_FEED_URLS)

            # Retrieve active 'owned' companies from the database
            owned_symbols = session.scalars(
                select(Company.symbol)
                .join(WatchlistItem, WatchlistItem.company_id == Company.id)
                .where(
                    Company.is_active.is_(True),
                    WatchlistItem.watch_status == "owned",
                )
            ).all()

            for symbol in owned_symbols:
                sym_upper = symbol.upper()
                if sym_upper in OTHER_IR_FEED_URLS and sym_upper not in active_feeds:
                    active_feeds[sym_upper] = OTHER_IR_FEED_URLS[sym_upper]

            companies = session.scalars(
                select(Company).where(
                    Company.is_active.is_(True),
                    Company.symbol.in_(sorted(active_feeds)),
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

            for symbol, url in active_feeds.items():
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
