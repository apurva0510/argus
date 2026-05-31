import logging
from datetime import UTC, datetime
import feedparser
import httpx

logger = logging.getLogger(__name__)


def fetch_rss_news(ticker: str) -> list[dict]:
    """Fetch news for a given ticker from Yahoo Finance RSS feed.

    Returns a list of dictionaries containing title, summary, url, source_name,
    and published_at (naive UTC datetime).
    """
    ticker_clean = ticker.strip().upper()
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker_clean}&region=US&lang=en-US"

    logger.info("Fetching RSS news for %s from %s", ticker_clean, url)
    
    max_retries = 3
    backoff_factor = 2.0
    response = None

    for attempt in range(max_retries):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = httpx.get(url, headers=headers, follow_redirects=True, timeout=10.0)
            if response.status_code == 404:
                logger.warning("RSS feed for %s not found (404). Returning empty list.", ticker_clean)
                return []
            if response.status_code == 429:
                wait = backoff_factor ** (attempt + 1)
                logger.warning("RSS rate limit (429) on attempt %d. Retrying in %d seconds...", attempt + 1, wait)
                import time
                time.sleep(wait)
                continue
            response.raise_for_status()
            break
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            if attempt == max_retries - 1:
                logger.error("All RSS retry attempts failed for %s: %s", ticker_clean, exc)
                return []
            wait = backoff_factor ** (attempt + 1)
            logger.warning("RSS query failed on attempt %d: %s. Retrying in %d seconds...", attempt + 1, exc, wait)
            import time
            time.sleep(wait)

    if not response or response.status_code != 200:
        return []

    try:
        feed = feedparser.parse(response.content)
    except Exception as exc:
        logger.error("Failed to parse RSS feed for %s: %s", ticker_clean, exc)
        return []

    if getattr(feed, "bozo", 0) == 1:
        logger.warning(
            "Feedparser reported bozo exception when parsing feed for %s: %s",
            ticker_clean,
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

    logger.info("Found %d news items in RSS feed for %s", len(news_items), ticker_clean)
    return news_items
