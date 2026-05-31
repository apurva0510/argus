import logging
import time
from datetime import UTC, datetime
import httpx

from argus.core.settings import settings
from argus.sources.news_rss_client import NewsProviderRateLimitError

logger = logging.getLogger(__name__)
_last_gdelt_request_at = 0.0


def parse_gdelt_date(date_str: str | None) -> datetime:
    """Parse GDELT's seendate string into a naive UTC datetime.

    Supported formats: '20250530T233000Z', '20250530233000', etc.
    """
    if not date_str:
        return datetime.now(UTC).replace(tzinfo=None)

    # Strip any trailing whitespace
    date_str = date_str.strip()

    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y%m%d%H%M%SZ"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue

    logger.warning("Could not parse GDELT date format: %s. Defaulting to now.", date_str)
    return datetime.now(UTC).replace(tzinfo=None)


def fetch_gdelt_news(ticker: str, timespan: str = "1d") -> list[dict]:
    return fetch_gdelt_news_query(f'"{ticker.strip().upper()}"', timespan=timespan)


def _rate_limit() -> None:
    global _last_gdelt_request_at
    delay = max(0.0, float(settings.news_request_delay_seconds))
    elapsed = time.monotonic() - _last_gdelt_request_at
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_gdelt_request_at = time.monotonic()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        return None


def fetch_gdelt_news_query(query: str, timespan: str = "1d") -> list[dict]:
    """Fetch news for a broad query from GDELT Doc 2.0 API.

    Returns a list of dictionaries with title, summary (None), url, source_name,
    and published_at (naive UTC datetime).
    """
    query_clean = query.strip()
    url = "https://api.gdeltproject.org/api/v2/doc/doc"

    params = {
        "query": f"{query_clean} sourcelang:English",
        "mode": "ArtList",
        "format": "json",
        "timespan": timespan,
    }

    logger.info("Fetching GDELT news for query %s with timespan %s", query_clean, timespan)
    max_retries = 2
    response = None

    for attempt in range(max_retries + 1):
        try:
            _rate_limit()
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = httpx.get(url, params=params, headers=headers, timeout=8.0)
            if response.status_code == 404:
                logger.warning("GDELT API returned 404 for %s. Returning empty list.", query_clean)
                return []
            if response.status_code == 429:
                if attempt == max_retries:
                    raise NewsProviderRateLimitError("gdelt", query_clean)
                wait = _retry_after_seconds(response)
                if wait is None:
                    wait = 2.0**attempt
                logger.warning("GDELT rate limit for %s. Retrying in %.1f seconds.", query_clean, wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            break
        except httpx.TimeoutException as exc:
            logger.warning("GDELT query timed out for %s: %s. Skipping GDELT for this query.", query_clean, exc)
            return []
        except httpx.HTTPError as exc:
            if attempt == max_retries:
                logger.error("All GDELT retry attempts failed for %s: %s", query_clean, exc)
                return []
            wait = 2.0**attempt
            logger.warning("GDELT query failed on attempt %d: %s. Retrying in %.1f seconds...", attempt + 1, exc, wait)
            time.sleep(wait)

    if not response or response.status_code != 200:
        return []

    try:
        data = response.json()
    except Exception as exc:
        logger.error("Failed to parse GDELT JSON response for %s: %s", query_clean, exc)
        return []

    articles = data.get("articles", [])
    news_items = []

    for art in articles:
        title = art.get("title", "").strip()
        if not title:
            continue

        link = art.get("url", "").strip()
        if not link:
            continue

        domain = art.get("domain", "").strip()
        source_name = domain if domain else "GDELT"

        seendate = art.get("seendate")
        published_at = parse_gdelt_date(seendate)

        news_items.append({
            "title": title,
            "summary": None,  # GDELT ArtList mode does not return full article summary text
            "url": link,
            "source_name": source_name,
            "published_at": published_at,
        })

    logger.info("Found %d news items in GDELT for %s", len(news_items), query_clean)
    return news_items
