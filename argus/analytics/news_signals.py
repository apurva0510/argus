from __future__ import annotations

from dataclasses import dataclass
import math
import re
from datetime import datetime

SENTIMENT_METHOD = "keyword_financial_v1"
NEGATION_TERMS = {"not", "no", "without", "less"}


@dataclass(frozen=True)
class SentimentTerm:
    term: str
    category: str
    weight: float


POSITIVE_TERMS = (
    SentimentTerm("raises guidance", "earnings", 2.0),
    SentimentTerm("raised guidance", "earnings", 2.0),
    SentimentTerm("beats estimates", "earnings", 1.5),
    SentimentTerm("beat estimates", "earnings", 1.5),
    SentimentTerm("margin expansion", "financial_quality", 1.3),
    SentimentTerm("strong demand", "demand", 1.5),
    SentimentTerm("backlog growth", "demand", 1.4),
    SentimentTerm("capacity expansion", "demand", 1.2),
    SentimentTerm("price target raised", "analyst", 1.4),
    SentimentTerm("price target increase", "analyst", 1.4),
    SentimentTerm("initiates buy", "analyst", 1.3),
    SentimentTerm("wins contract", "contracts", 1.5),
    SentimentTerm("won contract", "contracts", 1.5),
    SentimentTerm("multi-year deal", "contracts", 1.4),
    SentimentTerm("partnership", "contracts", 1.0),
    SentimentTerm("accelerate", "demand", 0.8),
    SentimentTerm("accelerates", "demand", 0.8),
    SentimentTerm("beat", "earnings", 0.8),
    SentimentTerm("beats", "earnings", 0.8),
    SentimentTerm("boost", "financial_quality", 0.8),
    SentimentTerm("contract", "contracts", 0.7),
    SentimentTerm("demand", "demand", 0.6),
    SentimentTerm("expands", "demand", 0.7),
    SentimentTerm("expansion", "demand", 0.7),
    SentimentTerm("growth", "financial_quality", 0.7),
    SentimentTerm("investment", "financial_quality", 0.7),
    SentimentTerm("raises", "earnings", 0.7),
    SentimentTerm("record", "financial_quality", 0.7),
    SentimentTerm("upgrade", "analyst", 1.0),
    SentimentTerm("upgrades", "analyst", 1.0),
    SentimentTerm("wins", "contracts", 0.8),
)

NEGATIVE_TERMS = (
    SentimentTerm("cuts guidance", "earnings", -2.0),
    SentimentTerm("cut guidance", "earnings", -2.0),
    SentimentTerm("misses estimates", "earnings", -1.5),
    SentimentTerm("missed estimates", "earnings", -1.5),
    SentimentTerm("margin pressure", "financial_quality", -1.4),
    SentimentTerm("weak demand", "demand", -1.5),
    SentimentTerm("supply constraint", "operations", -1.2),
    SentimentTerm("price target cut", "analyst", -1.4),
    SentimentTerm("price target lowered", "analyst", -1.4),
    SentimentTerm("sec investigation", "legal", -2.0),
    SentimentTerm("cancel", "operations", -0.9),
    SentimentTerm("cancels", "operations", -0.9),
    SentimentTerm("cut", "earnings", -0.7),
    SentimentTerm("cuts", "earnings", -0.7),
    SentimentTerm("delay", "operations", -0.9),
    SentimentTerm("delays", "operations", -0.9),
    SentimentTerm("downgrade", "analyst", -1.0),
    SentimentTerm("downgrades", "analyst", -1.0),
    SentimentTerm("falls", "financial_quality", -0.7),
    SentimentTerm("investigation", "legal", -1.0),
    SentimentTerm("lawsuit", "legal", -1.0),
    SentimentTerm("miss", "earnings", -0.8),
    SentimentTerm("misses", "earnings", -0.8),
    SentimentTerm("outage", "operations", -1.1),
    SentimentTerm("probe", "legal", -1.0),
    SentimentTerm("slowdown", "demand", -1.0),
    SentimentTerm("weak", "demand", -0.8),
)

SOURCE_OVERRIDES = {
    "reuters": 1.0,
    "associated press": 1.0,
    "ap news": 1.0,
    "investor relations": 0.8,
    "yahoo finance": 0.7,
    "google news": 0.7,
    "marketwatch": 0.7,
    "barron's": 0.7,
    "barrons": 0.7,
    "motley fool": 0.5,
    "seeking alpha": 0.5,
}


def score_news_article(
    title: str,
    summary: str | None,
    mentions: list[dict],
) -> tuple[float | None, float | None]:
    sentiment_score = analyze_news_sentiment(title, summary)["score"]
    relevance_score = article_relevance(mentions)
    return sentiment_score, relevance_score


def build_sentiment_explanation(
    title: str,
    summary: str | None,
    *,
    provider: str | None,
    source_name: str | None,
) -> dict[str, object]:
    analysis = analyze_news_sentiment(title, summary)
    return {
        "method": SENTIMENT_METHOD,
        "score": analysis["score"],
        "positive_matches": analysis["positive_matches"],
        "negative_matches": analysis["negative_matches"],
        "categories": analysis["categories"],
        "provider": provider,
        "source_name": source_name,
        "source_weight": source_weight(provider=provider, source_name=source_name),
    }


def analyze_news_sentiment(title: str, summary: str | None) -> dict[str, object]:
    text = f"{title or ''} {summary or ''}".lower()
    candidates = _sentiment_candidates(text)
    selected = _select_non_overlapping_matches(candidates)

    positive_matches = [_match_payload(match) for match in selected if match["weight"] > 0]
    negative_matches = [_match_payload(match) for match in selected if match["weight"] < 0]
    categories = sorted({str(match["category"]) for match in selected})
    total_abs = sum(abs(float(match["weight"])) for match in selected)
    score = None
    if total_abs > 0:
        raw_score = sum(float(match["weight"]) for match in selected) / total_abs
        score = max(-1.0, min(1.0, raw_score))

    return {
        "score": score,
        "positive_matches": positive_matches,
        "negative_matches": negative_matches,
        "categories": categories,
    }


def source_weight(*, provider: str | None, source_name: str | None) -> float:
    provider_norm = (provider or "").strip().lower()
    source_norm = (source_name or "").strip().lower()

    if provider_norm == "ir_feed":
        return 0.8
    if provider_norm and provider_norm != "rss":
        return 0.7

    for source_key, weight in SOURCE_OVERRIDES.items():
        if source_key in source_norm:
            return weight

    return 0.7


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


def recency_weight(
    published_at: datetime | None, as_of: datetime, *, half_life_days: float = 3.0
) -> float:
    if published_at is None:
        return 0.25
    age_days = max(0.0, (as_of - published_at).total_seconds() / 86400.0)
    if half_life_days <= 0:
        return 1.0 if age_days == 0 else 0.0
    return float(math.exp(-math.log(2.0) * age_days / half_life_days))


def _sentiment_candidates(text: str) -> list[dict[str, object]]:
    candidates = []
    for term in (*POSITIVE_TERMS, *NEGATIVE_TERMS):
        pattern = r"\b" + re.escape(term.term) + r"\b"
        for match in re.finditer(pattern, text):
            if _is_negated(text, match.start()):
                continue
            candidates.append(
                {
                    "term": term.term,
                    "category": term.category,
                    "weight": term.weight,
                    "start": match.start(),
                    "end": match.end(),
                    "token_count": len(term.term.split()),
                }
            )
    return candidates


def _select_non_overlapping_matches(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    used_spans: list[tuple[int, int]] = []
    ordered = sorted(
        candidates,
        key=lambda item: (
            -int(item["token_count"]),
            -abs(float(item["weight"])),
            int(item["start"]),
        ),
    )
    for candidate in ordered:
        span = (int(candidate["start"]), int(candidate["end"]))
        if any(_spans_overlap(span, used_span) for used_span in used_spans):
            continue
        selected.append(candidate)
        used_spans.append(span)
    return sorted(selected, key=lambda item: int(item["start"]))


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _is_negated(text: str, match_start: int) -> bool:
    preceding_text = text[:match_start]
    tokens = re.findall(r"\b[a-z]+\b", preceding_text)[-3:]
    return any(token in NEGATION_TERMS for token in tokens)


def _match_payload(match: dict[str, object]) -> dict[str, object]:
    return {
        "term": match["term"],
        "category": match["category"],
        "weight": match["weight"],
    }
