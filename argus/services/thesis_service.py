from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func

from argus.analytics.valuation import valuation_metric_label
from argus.core.db import session_scope
from argus.core.models import (
    Company,
    CompanyThemeExposure,
    DailyMetric,
    FundamentalsSnapshot,
    InvestmentThesis,
    NewsItem,
    NewsMention,
    SecFiling,
    Theme,
    ValuationPeerSnapshot,
)


THESIS_STATUSES = {"intact", "monitoring", "weakening", "broken"}
THESIS_STALE_DAYS = 90


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.1f}%"


def _fmt_multiple(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}x"


def thesis_is_stale(last_reviewed_date: date | None, *, today: date | None = None) -> bool:
    if last_reviewed_date is None:
        return True
    today = today or date.today()
    return last_reviewed_date < today - timedelta(days=THESIS_STALE_DAYS)


def thesis_needs_regeneration(last_reviewed_date: date | None, *, today: date | None = None) -> bool:
    if last_reviewed_date is None:
        return True
    today = today or date.today()
    return last_reviewed_date < today


def generated_status_for_conviction(conviction_score: int) -> str:
    if conviction_score >= 4:
        return "intact"
    if conviction_score <= 2:
        return "weakening"
    return "monitoring"


def get_company_thesis(company_id: int) -> dict:
    with session_scope() as session:
        thesis = (
            session.query(InvestmentThesis)
            .filter(InvestmentThesis.company_id == company_id)
            .one_or_none()
        )
        if thesis is None:
            return {
                "company_id": company_id,
                "has_thesis": False,
                "bull_thesis": "",
                "bear_thesis": "",
                "key_kpis": "",
                "thesis_status": "monitoring",
                "conviction_score": 3,
                "last_reviewed_date": None,
                "is_stale": False,
            }
        return {
            "id": thesis.id,
            "company_id": thesis.company_id,
            "has_thesis": True,
            "bull_thesis": thesis.bull_thesis or "",
            "bear_thesis": thesis.bear_thesis or "",
            "key_kpis": thesis.key_kpis or "",
            "thesis_status": thesis.thesis_status,
            "conviction_score": thesis.conviction_score,
            "last_reviewed_date": thesis.last_reviewed_date,
            "is_stale": thesis_is_stale(thesis.last_reviewed_date),
        }


def upsert_company_thesis(
    company_id: int,
    *,
    bull_thesis: str,
    bear_thesis: str,
    key_kpis: str,
    thesis_status: str,
    conviction_score: int,
    last_reviewed_date: date | None,
) -> None:
    normalized_status = thesis_status.strip().lower()
    if normalized_status not in THESIS_STATUSES:
        raise ValueError(f"Invalid thesis_status: {thesis_status}")
    if conviction_score < 1 or conviction_score > 5:
        raise ValueError("conviction_score must be between 1 and 5")

    with session_scope() as session:
        thesis = (
            session.query(InvestmentThesis)
            .filter(InvestmentThesis.company_id == company_id)
            .one_or_none()
        )
        if thesis is None:
            thesis = InvestmentThesis(company_id=company_id)
            session.add(thesis)
        thesis.bull_thesis = bull_thesis.strip() or None
        thesis.bear_thesis = bear_thesis.strip() or None
        thesis.key_kpis = key_kpis.strip() or None
        thesis.thesis_status = normalized_status
        thesis.conviction_score = conviction_score
        thesis.last_reviewed_date = last_reviewed_date


def generate_company_thesis_draft(company_id: int) -> dict:
    """Generate a local, deterministic thesis draft from existing Argus data."""
    with session_scope() as session:
        company = session.get(Company, company_id)
        if company is None:
            raise ValueError(f"Company {company_id} not found")
        company_symbol = company.symbol
        company_sector = company.sector

        metric = (
            session.query(DailyMetric)
            .filter(DailyMetric.company_id == company_id)
            .order_by(DailyMetric.date.desc())
            .first()
        )
        fundamental = (
            session.query(FundamentalsSnapshot)
            .filter(FundamentalsSnapshot.company_id == company_id)
            .order_by(FundamentalsSnapshot.as_of_date.desc(), FundamentalsSnapshot.id.desc())
            .first()
        )
        valuations = (
            session.query(ValuationPeerSnapshot)
            .filter(
                ValuationPeerSnapshot.company_id == company_id,
                ValuationPeerSnapshot.peer_group_type == "sector",
            )
            .order_by(ValuationPeerSnapshot.as_of_date.desc())
            .all()
        )
        latest_valuation_date = max((row.as_of_date for row in valuations), default=None)
        latest_valuations = [
            row for row in valuations if latest_valuation_date is not None and row.as_of_date == latest_valuation_date
        ]
        stretched_metrics = [
            valuation_metric_label(row.metric_name)
            for row in latest_valuations
            if row.valuation_flag == "stretched"
        ]
        cheap_metrics = [
            valuation_metric_label(row.metric_name)
            for row in latest_valuations
            if row.valuation_flag == "cheap"
        ]
        theme_rows = (
            session.query(Theme.name, CompanyThemeExposure.exposure_score)
            .join(CompanyThemeExposure, CompanyThemeExposure.theme_id == Theme.id)
            .filter(CompanyThemeExposure.company_id == company_id)
            .order_by(CompanyThemeExposure.exposure_score.desc())
            .limit(3)
            .all()
        )
        since_news = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
        recent_news_count = (
            session.query(func.count(NewsMention.id))
            .join(NewsItem, NewsItem.id == NewsMention.news_id)
            .filter(NewsMention.company_id == company_id, NewsItem.published_at >= since_news)
            .scalar()
            or 0
        )
        since_filings = date.today() - timedelta(days=90)
        recent_filing_count = (
            session.query(func.count(SecFiling.id))
            .filter(SecFiling.company_id == company_id, SecFiling.filing_date >= since_filings)
            .scalar()
            or 0
        )
        relative_return_vs_qqq_3m = metric.relative_return_vs_qqq_3m if metric else None
        drawdown_52w = metric.drawdown_52w if metric else None
        distance_from_200dma = metric.distance_from_200dma if metric else None
        revenue_growth = fundamental.revenue_growth if fundamental else None
        ev_to_sales = fundamental.ev_to_sales if fundamental else None

    theme_text = (
        ", ".join(f"{name} ({score:.1f}/5)" for name, score in theme_rows)
        if theme_rows
        else company_sector or "tracked Argus theme"
    )
    bull_points = [
        f"{company_symbol} is mapped to {theme_text}, keeping it relevant to the Argus AI infrastructure watch universe.",
    ]
    if relative_return_vs_qqq_3m is not None:
        bull_points.append(f"3M relative return versus QQQ is {_fmt_pct(relative_return_vs_qqq_3m)}.")
    if revenue_growth is not None:
        bull_points.append(f"Revenue growth is {_fmt_pct(revenue_growth)}.")
    if cheap_metrics:
        bull_points.append(f"Sector-relative valuation screens cheap on {', '.join(cheap_metrics[:3])}.")
    if recent_news_count or recent_filing_count:
        bull_points.append(
            f"Recent catalyst coverage includes {recent_news_count} news item(s) and {recent_filing_count} SEC filing(s)."
        )

    bear_points = []
    if stretched_metrics:
        bear_points.append(f"Valuation screens stretched versus sector peers on {', '.join(stretched_metrics[:3])}.")
    if drawdown_52w is not None:
        bear_points.append(f"Current drawdown from the 52-week high is {_fmt_pct(drawdown_52w)}.")
    if distance_from_200dma is not None:
        bear_points.append(f"Distance from the 200DMA is {_fmt_pct(distance_from_200dma)}.")
    if ev_to_sales is not None:
        bear_points.append(f"EV/Sales is {_fmt_multiple(ev_to_sales)}, so multiple compression remains a risk.")
    if not bear_points:
        bear_points.append("Main risk is that current public data does not yet show a clear negative catalyst or valuation warning.")

    kpis = [
        "Revenue growth and margin trend",
        "EV/Sales and forward P/E versus sector peers",
        "3M relative return versus QQQ and NVDA",
        "52-week drawdown, RSI, and 200DMA distance",
        "Earnings dates, SEC filings, and high-relevance news catalysts",
    ]
    conviction = 3
    if cheap_metrics:
        conviction += 1
    if stretched_metrics:
        conviction -= 1
    if relative_return_vs_qqq_3m is not None and relative_return_vs_qqq_3m > 0.05:
        conviction += 1
    conviction = max(1, min(5, conviction))

    return {
        "bull_thesis": "\n".join(f"- {point}" for point in bull_points),
        "bear_thesis": "\n".join(f"- {point}" for point in bear_points),
        "key_kpis": "\n".join(f"- {kpi}" for kpi in kpis),
        "thesis_status": generated_status_for_conviction(conviction),
        "conviction_score": conviction,
        "last_reviewed_date": date.today(),
    }


def generate_and_save_company_thesis(company_id: int) -> dict:
    draft = generate_company_thesis_draft(company_id)
    upsert_company_thesis(company_id, **draft)
    return draft


def get_or_generate_company_thesis(company_id: int) -> dict:
    thesis = get_company_thesis(company_id)
    if thesis.get("has_thesis") and not thesis_needs_regeneration(thesis.get("last_reviewed_date")):
        return thesis
    generate_and_save_company_thesis(company_id)
    return get_company_thesis(company_id)


def generate_all_company_theses() -> dict[str, object]:
    with session_scope() as session:
        company_ids = [
            company_id
            for (company_id,) in session.query(Company.id)
            .filter(Company.is_active.is_(True))
            .order_by(Company.symbol)
            .all()
        ]

    failures: list[str] = []
    rows_written = 0
    for company_id in company_ids:
        try:
            generate_and_save_company_thesis(company_id)
            rows_written += 1
        except Exception as exc:
            failures.append(f"{company_id}: {exc}")

    return {
        "status": "failed" if failures and not rows_written else "partial_success" if failures else "success",
        "rows_read": len(company_ids),
        "rows_written": rows_written,
        "error_text": "; ".join(failures) or None,
    }
