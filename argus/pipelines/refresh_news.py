from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from sqlalchemy import select

from argus.core.db import session_scope
from argus.core.models import Company, JobRun, NewsItem, NewsMention
from argus.sources.gdelt_client import fetch_gdelt_news
from argus.sources.news_rss_client import fetch_rss_news

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _create_job_run() -> int:
    with session_scope() as session:
        job = JobRun(job_name="refresh_news", started_at=_utc_now(), status="running")
        session.add(job)
        session.flush()
        return job.id


def _finish_job_run(
    job_id: int,
    *,
    status: str,
    rows_read: int,
    rows_written: int,
    failed_symbols: list[str],
    error_text: str | None = None,
) -> None:
    with session_scope() as session:
        job = session.get(JobRun, job_id)
        if job is None:
            job = JobRun(id=job_id, job_name="refresh_news", started_at=_utc_now(), status=status)
            session.add(job)

        job.finished_at = _utc_now()
        job.status = status
        job.rows_read = rows_read
        job.rows_written = rows_written
        if error_text:
            job.error_text = error_text
        elif failed_symbols:
            job.error_text = f"Failed symbols: {', '.join(sorted(failed_symbols))}"


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
        "reit",
    ]

    matched_infra = [
        kw for kw in infra_keywords if re.search(r"\b" + re.escape(kw) + r"\b", text)
    ]

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

        # Match clean company name
        clean_name = clean_company_name(comp.name)
        name_match = False
        if len(clean_name) > 3:  # Avoid matching very short parts of company names
            name_match = re.search(r"\b" + re.escape(clean_name) + r"\b", text)

        if ticker_match or name_match:
            matched_comp_kws = []
            if ticker_match:
                matched_comp_kws.append(comp.symbol)
            if name_match:
                matched_comp_kws.append(clean_name.upper())

            all_kws = matched_comp_kws + matched_infra

            # Primary match if ticker or company name is found in the title
            if len(symbol) <= 3:
                ticker_in_title = bool(re.search(r"\b" + re.escape(symbol) + r"\b", title))
            else:
                ticker_in_title = bool(re.search(r"\b" + re.escape(ticker_lower) + r"\b", title.lower()))

            name_in_title = False
            if len(clean_name) > 3:
                name_in_title = bool(re.search(r"\b" + re.escape(clean_name) + r"\b", title.lower()))

            is_primary = ticker_in_title or name_in_title

            mentions.append({
                "company_id": comp.id,
                "ticker": comp.symbol,
                "is_primary_match": is_primary,
                "matched_keywords": ", ".join(all_kws) if all_kws else None,
            })

    return mentions


def _upsert_news_item(session, art: dict, mentions: list[dict]) -> int:
    """Inserts a news item and its mentions if it doesn't exist.

    If it exists, adds any new company mentions not previously recorded.
    """
    # Check if URL already exists
    existing_item = (
        session.query(NewsItem).filter(NewsItem.url == art["url"]).one_or_none()
    )

    if existing_item is None:
        # Create news item
        item = NewsItem(
            title=art["title"][:512],
            summary=art["summary"][:2000] if art["summary"] else None,
            url=art["url"][:1024],
            source_name=art["source_name"][:128] if art["source_name"] else None,
            provider=art["provider"],
            published_at=art["published_at"],
        )
        session.add(item)
        session.flush()

        # Insert mentions
        for m in mentions:
            mention = NewsMention(
                news_id=item.id,
                company_id=m["company_id"],
                ticker=m["ticker"],
                is_primary_match=m["is_primary_match"],
                matched_keywords=m["matched_keywords"],
            )
            session.add(mention)
        return 1

    else:
        # Update details if needed
        existing_item.title = art["title"][:512]
        if art["summary"] and not existing_item.summary:
            existing_item.summary = art["summary"][:2000]

        # Check existing mentions
        existing_mentions = (
            session.query(NewsMention)
            .filter(NewsMention.news_id == existing_item.id)
            .all()
        )
        existing_company_ids = {m.company_id for m in existing_mentions}

        written = 0
        for m in mentions:
            if m["company_id"] not in existing_company_ids:
                mention = NewsMention(
                    news_id=existing_item.id,
                    company_id=m["company_id"],
                    ticker=m["ticker"],
                    is_primary_match=m["is_primary_match"],
                    matched_keywords=m["matched_keywords"],
                )
                session.add(mention)
                written += 1
        return 1 if written > 0 else 0


def refresh_news() -> dict[str, object]:
    """Fetch and process news articles from RSS and GDELT for all active companies.

    Detects mentions, maps keywords, and writes to database.
    """
    job_id = _create_job_run()
    rows_written = 0
    rows_read = 0
    failed_symbols: list[str] = []
    status = "success"
    error_text: str | None = None

    try:
        with session_scope() as session:
            companies = session.scalars(
                select(Company).where(Company.is_active.is_(True))
            ).all()

            global_unique_articles = {}

            for i, company in enumerate(companies):
                fetched_articles = []

                # 1. Fetch RSS news
                try:
                    rss_items = fetch_rss_news(company.symbol)
                    for item in rss_items:
                        item["provider"] = "rss"
                        fetched_articles.append(item)
                except Exception:
                    logger.exception("Failed to fetch RSS news for %s", company.symbol)
                    failed_symbols.append(company.symbol)

                # 2. Fetch GDELT news
                try:
                    gdelt_items = fetch_gdelt_news(company.symbol, timespan="1d")
                    for item in gdelt_items:
                        item["provider"] = "gdelt"
                        fetched_articles.append(item)
                except Exception:
                    logger.exception("Failed to fetch GDELT news for %s", company.symbol)
                    if company.symbol not in failed_symbols:
                        failed_symbols.append(company.symbol)

                rows_read += len(fetched_articles)

                # Collect in globally unique dictionary by URL
                for art in fetched_articles:
                    global_unique_articles[art["url"]] = art

                if i < len(companies) - 1:
                    time.sleep(1.0)

            # Process globally unique articles
            for art in global_unique_articles.values():
                # Check mentions across ALL active companies in DB
                mentions = detect_mentions_and_keywords(
                    art["title"], art["summary"], companies
                )
                if mentions:
                    rows_written += _upsert_news_item(session, art, mentions)

            if failed_symbols:
                # If we succeeded for some companies, it's a partial success
                status = (
                    "partial_success"
                    if rows_written > 0 or rows_read > 0
                    else "failed"
                )
                logger.warning(
                    "News refresh experienced failures for symbols: %s",
                    ",".join(failed_symbols),
                )
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        logger.exception("News refresh failed")
    finally:
        _finish_job_run(
            job_id,
            status=status,
            rows_read=rows_read,
            rows_written=rows_written,
            failed_symbols=failed_symbols,
            error_text=error_text,
        )

    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "failed_symbols": failed_symbols,
        "error_text": error_text,
    }

