from __future__ import annotations

from hashlib import sha256
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from argus.analytics.news_signals import score_news_article
from argus.core.models import Company, NewsItem, NewsMention


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

            mentions.append(
                {
                    "company_id": comp.id,
                    "ticker": comp.symbol,
                    "is_primary_match": ticker_in_title or name_in_title,
                    "matched_keywords": ", ".join(all_kws) if all_kws else None,
                }
            )

    seen_company_ids = set()
    unique_mentions = []
    for mention in mentions:
        if mention["company_id"] not in seen_company_ids:
            seen_company_ids.add(mention["company_id"])
            unique_mentions.append(mention)

    return unique_mentions


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
