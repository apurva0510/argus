from __future__ import annotations

import math
import re
from datetime import datetime

POSITIVE_TERMS = {
    "accelerate",
    "accelerates",
    "beat",
    "beats",
    "boost",
    "contract",
    "demand",
    "expands",
    "expansion",
    "growth",
    "investment",
    "partnership",
    "raises",
    "record",
    "upgrade",
    "wins",
}

NEGATIVE_TERMS = {
    "cancel",
    "cancels",
    "cut",
    "cuts",
    "delay",
    "delays",
    "downgrade",
    "falls",
    "investigation",
    "lawsuit",
    "miss",
    "misses",
    "outage",
    "probe",
    "slowdown",
    "weak",
}


def score_news_article(
    title: str,
    summary: str | None,
    mentions: list[dict],
) -> tuple[float | None, float | None]:
    text = f"{title or ''} {summary or ''}".lower()
    positive_count = _count_terms(text, POSITIVE_TERMS)
    negative_count = _count_terms(text, NEGATIVE_TERMS)

    sentiment_score = None
    if positive_count or negative_count:
        sentiment_score = (positive_count - negative_count) / (positive_count + negative_count)

    relevance_score = article_relevance(mentions)
    return sentiment_score, relevance_score


def mention_relevance(mention: dict) -> float:
    return article_relevance([mention]) or 0.0


def article_relevance(mentions: list[dict]) -> float | None:
    if not mentions:
        return None

    best = 0.0
    for mention in mentions:
        score = 0.4
        if mention.get("is_primary_match"):
            score += 0.35
        matched_keywords = mention.get("matched_keywords") or ""
        keyword_count = len([kw for kw in matched_keywords.split(",") if kw.strip()])
        score += min(0.25, keyword_count * 0.05)
        best = max(best, score)
    return min(1.0, best)


def recency_weight(published_at: datetime | None, as_of: datetime, *, half_life_days: float = 3.0) -> float:
    if published_at is None:
        return 0.25
    age_days = max(0.0, (as_of - published_at).total_seconds() / 86400.0)
    if half_life_days <= 0:
        return 1.0 if age_days == 0 else 0.0
    return float(math.exp(-math.log(2.0) * age_days / half_life_days))


def _count_terms(text: str, terms: set[str]) -> int:
    return sum(1 for term in terms if re.search(r"\b" + re.escape(term) + r"\b", text))
