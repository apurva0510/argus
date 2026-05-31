from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import logging
from sqlalchemy.orm import Session
from argus.core.models import (
    Company,
    DailyMetric,
    PriceBar,
    SecFiling,
    NewsItem,
    NewsMention,
    EarningsEvent,
    Alert,
)

logger = logging.getLogger(__name__)
MAX_MARKET_DATA_AGE_DAYS = 3


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _is_fresh_market_date(value: date | None) -> bool:
    if value is None:
        return False
    return (_utc_today() - value).days <= MAX_MARKET_DATA_AGE_DAYS


def _latest_fresh_price_bar(session: Session, company: Company) -> PriceBar | None:
    price_bar = (
        session.query(PriceBar)
        .filter(
            PriceBar.company_id == company.id,
            PriceBar.provider == "yfinance",
            PriceBar.interval == "1d",
        )
        .order_by(PriceBar.date.desc())
        .first()
    )
    if not price_bar or price_bar.adj_close is None:
        return None
    if not _is_fresh_market_date(price_bar.date):
        logger.info(
            "Skipping alert evaluation for %s because latest price date is stale: %s",
            company.symbol,
            price_bar.date,
        )
        return None
    return price_bar


def _latest_fresh_daily_metric(session: Session, company: Company) -> DailyMetric | None:
    metric = (
        session.query(DailyMetric)
        .filter(DailyMetric.company_id == company.id)
        .order_by(DailyMetric.date.desc())
        .first()
    )
    if not metric:
        return None
    if not _is_fresh_market_date(metric.date):
        logger.info(
            "Skipping alert evaluation for %s because latest metric date is stale: %s",
            company.symbol,
            metric.date,
        )
        return None
    return metric


def check_price_below(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    threshold = config.get("threshold")
    if threshold is None:
        logger.warning("Alert %s (price_below) missing 'threshold' in config", alert.id)
        return None

    pb = _latest_fresh_price_bar(session, company)
    if not pb:
        return None

    if pb.adj_close < float(threshold):
        return [
            {
                "price": pb.adj_close,
                "threshold": float(threshold),
                "date": pb.date.isoformat(),
            }
        ]
    return None


def check_price_above(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    threshold = config.get("threshold")
    if threshold is None:
        logger.warning("Alert %s (price_above) missing 'threshold' in config", alert.id)
        return None

    pb = _latest_fresh_price_bar(session, company)
    if not pb:
        return None

    if pb.adj_close > float(threshold):
        return [
            {
                "price": pb.adj_close,
                "threshold": float(threshold),
                "date": pb.date.isoformat(),
            }
        ]
    return None


def check_daily_move_gt(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    threshold_pct = config.get("threshold_pct")
    if threshold_pct is None:
        logger.warning("Alert %s (daily_move_gt) missing 'threshold_pct' in config", alert.id)
        return None

    dm = _latest_fresh_daily_metric(session, company)
    if not dm or dm.return_1d is None:
        return None

    move_pct = abs(dm.return_1d) * 100.0
    if move_pct > float(threshold_pct):
        return [
            {
                "return_1d": dm.return_1d,
                "threshold_pct": float(threshold_pct),
                "date": dm.date.isoformat(),
            }
        ]
    return None


def check_drawdown_52w_gt(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    threshold_pct = config.get("threshold_pct")
    if threshold_pct is None:
        logger.warning("Alert %s (drawdown_52w_gt) missing 'threshold_pct' in config", alert.id)
        return None

    dm = _latest_fresh_daily_metric(session, company)
    if not dm or dm.drawdown_52w is None:
        return None

    drawdown_pct = abs(dm.drawdown_52w) * 100.0
    if drawdown_pct > float(threshold_pct):
        return [
            {
                "drawdown_52w": dm.drawdown_52w,
                "threshold_pct": float(threshold_pct),
                "date": dm.date.isoformat(),
            }
        ]
    return None


def check_rsi_below(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    threshold = config.get("threshold")
    if threshold is None:
        logger.warning("Alert %s (rsi_below) missing 'threshold' in config", alert.id)
        return None

    dm = _latest_fresh_daily_metric(session, company)
    if not dm or dm.rsi_14 is None:
        return None

    if dm.rsi_14 < float(threshold):
        return [
            {
                "rsi_14": dm.rsi_14,
                "threshold": float(threshold),
                "date": dm.date.isoformat(),
            }
        ]
    return None


def check_crossed_50dma(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    direction = config.get("direction", "any").lower()

    dms = (
        session.query(DailyMetric)
        .filter(DailyMetric.company_id == company.id)
        .order_by(DailyMetric.date.desc())
        .limit(2)
        .all()
    )
    if len(dms) < 2:
        return None

    # dms[0] is latest, dms[1] is prior
    latest, prior = dms[0], dms[1]
    if not _is_fresh_market_date(latest.date):
        logger.info(
            "Skipping alert evaluation for %s because latest metric date is stale: %s",
            company.symbol,
            latest.date,
        )
        return None
    if (
        latest.distance_from_50dma is None
        or prior.distance_from_50dma is None
        or latest.ma_50 is None
    ):
        return None

    # Get latest price
    pb = (
        session.query(PriceBar)
        .filter(
            PriceBar.company_id == company.id,
            PriceBar.provider == "yfinance",
            PriceBar.interval == "1d",
            PriceBar.date == latest.date,
        )
        .first()
    )
    price = pb.adj_close if pb else None
    if price is None:
        return None

    triggered = False
    if direction == "above":
        triggered = prior.distance_from_50dma < 0 and latest.distance_from_50dma >= 0
    elif direction == "below":
        triggered = prior.distance_from_50dma >= 0 and latest.distance_from_50dma < 0
    else:  # any
        triggered = (prior.distance_from_50dma >= 0) != (latest.distance_from_50dma >= 0)

    if triggered:
        return [
            {
                "price": price,
                "ma_50": latest.ma_50,
                "direction": direction,
                "date": latest.date.isoformat(),
            }
        ]
    return None


def check_crossed_200dma(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    direction = config.get("direction", "any").lower()

    dms = (
        session.query(DailyMetric)
        .filter(DailyMetric.company_id == company.id)
        .order_by(DailyMetric.date.desc())
        .limit(2)
        .all()
    )
    if len(dms) < 2:
        return None

    # dms[0] is latest, dms[1] is prior
    latest, prior = dms[0], dms[1]
    if not _is_fresh_market_date(latest.date):
        logger.info(
            "Skipping alert evaluation for %s because latest metric date is stale: %s",
            company.symbol,
            latest.date,
        )
        return None
    if (
        latest.distance_from_200dma is None
        or prior.distance_from_200dma is None
        or latest.ma_200 is None
    ):
        return None

    # Get latest price
    pb = (
        session.query(PriceBar)
        .filter(
            PriceBar.company_id == company.id,
            PriceBar.provider == "yfinance",
            PriceBar.interval == "1d",
            PriceBar.date == latest.date,
        )
        .first()
    )
    price = pb.adj_close if pb else None
    if price is None:
        return None

    triggered = False
    if direction == "above":
        triggered = prior.distance_from_200dma < 0 and latest.distance_from_200dma >= 0
    elif direction == "below":
        triggered = prior.distance_from_200dma >= 0 and latest.distance_from_200dma < 0
    else:  # any
        triggered = (prior.distance_from_200dma >= 0) != (latest.distance_from_200dma >= 0)

    if triggered:
        return [
            {
                "price": price,
                "ma_200": latest.ma_200,
                "direction": direction,
                "date": latest.date.isoformat(),
            }
        ]
    return None


def check_new_sec_filing(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    forms = config.get("forms")  # Optional list of form strings
    if forms and isinstance(forms, str):
        # Allow single string
        forms = [forms]

    # Filter filings for this company in the last 7 days
    since_date = _utc_today() - timedelta(days=7)
    filings = (
        session.query(SecFiling)
        .filter(SecFiling.company_id == company.id, SecFiling.filing_date >= since_date)
        .all()
    )

    triggers = []
    for f in filings:
        if not forms or f.form in forms:
            triggers.append(
                {
                    "accession_no": f.accession_no,
                    "form": f.form,
                    "filing_date": f.filing_date.isoformat() if f.filing_date else None,
                    "primary_doc_url": f.primary_doc_url,
                }
            )

    return triggers if triggers else None


def check_news_keyword_match(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    keywords = config.get("keywords")
    if keywords and isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",")]

    # Get news mentions in the last 7 days
    since_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    mentions = (
        session.query(NewsMention, NewsItem)
        .join(NewsItem, NewsItem.id == NewsMention.news_id)
        .filter(NewsMention.company_id == company.id, NewsItem.published_at >= since_time)
        .all()
    )

    triggers = []
    for mention, item in mentions:
        match = False
        if not keywords:
            # If no keywords specified, alert on any mention
            match = True
        else:
            title = (item.title or "").lower()
            summary = (item.summary or "").lower()
            kw_str = (mention.matched_keywords or "").lower()
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in title or kw_lower in summary or kw_lower in kw_str:
                    match = True
                    break

        if match:
            triggers.append(
                {
                    "news_id": item.id,
                    "title": item.title,
                    "url": item.url,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                }
            )

    return triggers if triggers else None


def check_earnings_within_days(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    days = config.get("days", 7)
    if days is None:
        days = 7

    today = _utc_today()
    end_date = today + timedelta(days=int(days))

    events = (
        session.query(EarningsEvent)
        .filter(
            EarningsEvent.company_id == company.id,
            EarningsEvent.event_date >= today,
            EarningsEvent.event_date <= end_date,
        )
        .all()
    )

    triggers = []
    for e in events:
        days_until = (e.event_date - today).days
        triggers.append(
            {
                "event_id": e.id,
                "event_date": e.event_date.isoformat(),
                "days_until": days_until,
                "fiscal_period": e.fiscal_period,
            }
        )

    return triggers if triggers else None


def check_entered_pullback_zone(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    config = alert.config_json or {}
    min_drawdown_pct = float(config.get("min_drawdown_pct", 10.0))
    max_rsi = float(config.get("max_rsi", 55.0))
    min_distance_from_200dma_pct = float(config.get("min_distance_from_200dma", -5.0))

    dm = _latest_fresh_daily_metric(session, company)
    if not dm:
        return None

    if dm.drawdown_52w is None or dm.rsi_14 is None or dm.distance_from_200dma is None:
        return None

    drawdown_pct = abs(dm.drawdown_52w) * 100.0
    rsi = dm.rsi_14
    distance_pct = dm.distance_from_200dma * 100.0

    if (
        drawdown_pct >= min_drawdown_pct
        and rsi <= max_rsi
        and distance_pct >= min_distance_from_200dma_pct
    ):
        return [
            {
                "drawdown_52w": dm.drawdown_52w,
                "rsi_14": rsi,
                "distance_from_200dma": dm.distance_from_200dma,
                "date": dm.date.isoformat(),
            }
        ]
    return None


RULE_CHECKERS = {
    "price_below": check_price_below,
    "price_above": check_price_above,
    "daily_move_gt": check_daily_move_gt,
    "drawdown_52w_gt": check_drawdown_52w_gt,
    "rsi_below": check_rsi_below,
    "crossed_50dma": check_crossed_50dma,
    "crossed_200dma": check_crossed_200dma,
    "new_sec_filing": check_new_sec_filing,
    "news_keyword_match": check_news_keyword_match,
    "earnings_within_days": check_earnings_within_days,
    "entered_pullback_zone": check_entered_pullback_zone,
}


def evaluate_alert_for_company(session: Session, alert: Alert, company: Company) -> list[dict] | None:
    checker = RULE_CHECKERS.get(alert.rule_type)
    if not checker:
        logger.error("Unknown alert rule type: %s", alert.rule_type)
        return None
    try:
        return checker(session, alert, company)
    except Exception:
        logger.exception(
            "Error evaluating alert %s for company %s", alert.id, company.symbol
        )
        return None
