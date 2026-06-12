from __future__ import annotations

from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from argus.analytics.news_signals import score_news_article
from argus.core.models import NewsItem, NewsMention


TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "guccounter",
}


def normalize_news_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlsplit(url.strip())
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_QUERY_PARAMS
        ],
        doseq=True,
    )
    path = parsed.path.rstrip("/") or parsed.path
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def stable_article_key(article: dict) -> str:
    normalized_url = normalize_news_url(article.get("url"))
    if normalized_url:
        return normalized_url
    published = article.get("published_at")
    published_key = (
        published.date().isoformat() if hasattr(published, "date") else str(published or "")
    )
    raw = f"{article.get('title', '').strip().lower()}|{published_key}"
    return "urn:argus-news:" + sha256(raw.encode("utf-8")).hexdigest()


def upsert_news_item(session, art: dict, mentions: list[dict]) -> int:
    """Insert a news item and any missing mentions.

    Returns 1 when the news item or at least one new mention is written, else 0.
    """
    stable_key = stable_article_key(art)
    existing_item = session.query(NewsItem).filter(NewsItem.url == stable_key).one_or_none()

    seen_company_ids = set()
    unique_mentions = []
    for mention in mentions:
        if mention["company_id"] not in seen_company_ids:
            seen_company_ids.add(mention["company_id"])
            unique_mentions.append(mention)
    mentions = unique_mentions

    sentiment_score, relevance_score = score_news_article(
        art["title"],
        art.get("summary"),
        mentions,
    )

    if existing_item is None:
        item = NewsItem(
            title=art["title"][:512],
            summary=art["summary"][:2000] if art["summary"] else None,
            url=stable_key[:1024],
            source_name=art["source_name"][:128] if art["source_name"] else None,
            provider=art["provider"],
            published_at=art["published_at"],
            sentiment_score=sentiment_score,
            relevance_score=relevance_score,
        )
        session.add(item)
        session.flush()

        for mention in mentions:
            session.add(
                NewsMention(
                    news_id=item.id,
                    company_id=mention["company_id"],
                    ticker=mention["ticker"],
                    is_primary_match=mention["is_primary_match"],
                    matched_keywords=mention["matched_keywords"],
                )
            )
        session.flush()
        return 1

    existing_item.title = art["title"][:512]
    if art["summary"] and not existing_item.summary:
        existing_item.summary = art["summary"][:2000]
    existing_item.sentiment_score = sentiment_score
    existing_item.relevance_score = relevance_score

    existing_mentions = (
        session.query(NewsMention).filter(NewsMention.news_id == existing_item.id).all()
    )
    existing_company_ids = {mention.company_id for mention in existing_mentions}

    written = 0
    for mention in mentions:
        if mention["company_id"] not in existing_company_ids:
            news_mention = NewsMention(
                news_id=existing_item.id,
                company_id=mention["company_id"],
                ticker=mention["ticker"],
                is_primary_match=mention["is_primary_match"],
                matched_keywords=mention["matched_keywords"],
            )
            session.add(news_mention)
            existing_company_ids.add(mention["company_id"])
            existing_mentions.append(news_mention)
            written += 1

    existing_item.sentiment_score, existing_item.relevance_score = score_news_article(
        existing_item.title,
        existing_item.summary,
        [_mention_dict(mention) for mention in existing_mentions],
    )
    return 1 if written > 0 else 0


def _mention_dict(mention) -> dict:
    if isinstance(mention, dict):
        return {
            "is_primary_match": mention.get("is_primary_match"),
            "matched_keywords": mention.get("matched_keywords"),
        }
    return {
        "is_primary_match": mention.is_primary_match,
        "matched_keywords": mention.matched_keywords,
    }
