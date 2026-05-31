import logging
import time
from datetime import UTC, datetime
from urllib.parse import quote_plus
import feedparser
import httpx

from argus.core.settings import settings

logger = logging.getLogger(__name__)
_last_rss_request_at = 0.0


class NewsProviderRateLimitError(RuntimeError):
    def __init__(self, provider: str, query: str, status_code: int = 429):
        self.provider = provider
        self.query = query
        self.status_code = status_code
        super().__init__(f"{provider} rate limited query '{query}' with HTTP {status_code}")


def _rate_limit() -> None:
    global _last_rss_request_at
    delay = max(0.0, float(settings.news_request_delay_seconds))
    elapsed = time.monotonic() - _last_rss_request_at
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_rss_request_at = time.monotonic()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        return None


def _get_with_retries(url: str, *, query: str, timeout: float = 10.0) -> httpx.Response | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    max_retries = 2
    for attempt in range(max_retries + 1):
        _rate_limit()
        try:
            response = httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            if attempt == max_retries:
                logger.warning("RSS query failed for %s after retries: %s", query, exc)
                return None
            time.sleep(2.0**attempt)
            continue

        if response.status_code == 404:
            logger.warning("RSS feed for %s not found (404). Returning empty list.", query)
            return None
        if response.status_code == 429:
            if attempt == max_retries:
                raise NewsProviderRateLimitError("rss", query)
            wait = _retry_after_seconds(response)
            if wait is None:
                wait = 2.0**attempt
            logger.warning("RSS rate limit for %s. Retrying in %.1f seconds.", query, wait)
            time.sleep(wait)
            continue

        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if attempt == max_retries:
                logger.warning("RSS query failed for %s after retries: %s", query, exc)
                return None
            time.sleep(2.0**attempt)
            continue
        return response

    return None


def fetch_rss_news(ticker: str) -> list[dict]:
    return fetch_rss_news_query(ticker)


def fetch_rss_news_query(query: str) -> list[dict]:
    """Fetch Yahoo Finance RSS news for a broad search query.

    Returns a list of dictionaries containing title, summary, url, source_name,
    and published_at (naive UTC datetime).
    """
    query_clean = query.strip()
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(query_clean)}&region=US&lang=en-US"

    logger.info("Fetching RSS news for query %s from %s", query_clean, url)
    response = _get_with_retries(url, query=query_clean)

    if not response or response.status_code != 200:
        return []

    try:
        feed = feedparser.parse(response.content)
    except Exception as exc:
        logger.error("Failed to parse RSS feed for %s: %s", query_clean, exc)
        return []

    if getattr(feed, "bozo", 0) == 1:
        logger.warning(
            "Feedparser reported bozo exception when parsing feed for %s: %s",
            query_clean,
            getattr(feed, "bozo_exception", "Unknown error"),
        )

    entries = feed.get("entries", [])
    news_items = []

    for entry in entries:
        title = entry.get("title", "").strip()
        if not title:
            continue

        link = entry.get("link", "").strip()
        if not link:
            continue

        # Get summary or description
        summary = entry.get("summary") or entry.get("description")
        if summary:
            summary = summary.strip()

        # Extract source name if available, otherwise default to Yahoo Finance
        source = entry.get("source", {})
        source_name = None
        if isinstance(source, dict):
            source_name = source.get("title")
        if not source_name:
            source_name = "Yahoo Finance"

        # Parse published date
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            try:
                published_at = datetime(*published_parsed[:6], tzinfo=UTC).replace(tzinfo=None)
            except (ValueError, TypeError):
                published_at = datetime.now(UTC).replace(tzinfo=None)
        else:
            published_at = datetime.now(UTC).replace(tzinfo=None)

        news_items.append({
            "title": title,
            "summary": summary,
            "url": link,
            "source_name": source_name,
            "published_at": published_at,
        })

    logger.info("Found %d news items in RSS feed for %s", len(news_items), query_clean)
    return news_items
