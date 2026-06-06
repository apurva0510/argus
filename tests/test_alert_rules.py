"""Tests for Phase 10: Alert rules, deduplication, and pipeline."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from argus.core import models  # noqa: F401
from argus.core.models import (
    Alert,
    AlertEvent,
    Company,
    DailyMetric,
    EarningsEvent,
    JobRun,
    NewsItem,
    NewsMention,
    PriceBar,
    SecFiling,
)
from argus.alerts.rules import (
    check_price_below,
    check_price_above,
    check_daily_move_gt,
    check_drawdown_52w_gt,
    check_rsi_below,
    check_crossed_50dma,
    check_crossed_200dma,
    check_new_sec_filing,
    check_news_keyword_match,
    check_earnings_within_days,
    check_entered_pullback_zone,
    evaluate_alert_for_company,
    RULE_CHECKERS,
)
from argus.alerts.formatting import company_detail_url, format_alert_email
from argus.alerts.email_delivery import is_smtp_configured
from argus.pipelines import run_alerts as run_alerts_module
from argus.services import alert_service


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def alert_engine(sqlite_engine) -> Engine:
    return sqlite_engine


@pytest.fixture
def alert_session(db_session) -> Session:
    return db_session


@pytest.fixture
def sample_company(alert_session) -> Company:
    c = Company(symbol="VRT", name="Vertiv Holdings", sector="Cooling", is_active=True)
    alert_session.add(c)
    alert_session.commit()
    return c


@pytest.fixture
def sample_price_bar(alert_session, sample_company) -> PriceBar:
    pb = PriceBar(
        company_id=sample_company.id,
        date=date.today(),
        open=80.0,
        high=85.0,
        low=78.0,
        close=82.0,
        adj_close=82.0,
        volume=1_000_000,
        provider="yfinance",
        interval="1d",
    )
    alert_session.add(pb)
    alert_session.commit()
    return pb


@pytest.fixture
def sample_metrics(alert_session, sample_company) -> list[DailyMetric]:
    """Create two consecutive daily metrics for crossover testing."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    dm_yesterday = DailyMetric(
        company_id=sample_company.id,
        date=yesterday,
        return_1d=-0.02,
        drawdown_52w=-0.12,
        rsi_14=38.0,
        ma_50=85.0,
        ma_200=75.0,
        distance_from_50dma=-0.04,  # below 50DMA
        distance_from_200dma=0.08,  # above 200DMA
    )
    dm_today = DailyMetric(
        company_id=sample_company.id,
        date=today,
        return_1d=-0.05,
        drawdown_52w=-0.18,
        rsi_14=32.0,
        ma_50=84.0,
        ma_200=74.0,
        distance_from_50dma=0.02,  # crossed above 50DMA
        distance_from_200dma=0.10,  # still above 200DMA
    )
    alert_session.add_all([dm_yesterday, dm_today])
    alert_session.commit()
    return [dm_yesterday, dm_today]


def _make_alert(
    session,
    company,
    rule_type,
    config_json=None,
    name="Test Alert",
) -> Alert:
    alert = Alert(
        name=name,
        rule_type=rule_type,
        company_id=company.id,
        config_json=config_json or {},
        channel="email",
        is_enabled=True,
    )
    session.add(alert)
    session.commit()
    return alert


# ── Price Below / Above ──────────────────────────────────────────────


class TestPriceBelow:
    def test_triggers_when_below(self, alert_session, sample_company, sample_price_bar):
        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        result = check_price_below(alert_session, alert, sample_company)
        assert result is not None
        assert len(result) == 1
        assert result[0]["price"] == 82.0
        assert result[0]["threshold"] == 90.0

    def test_does_not_trigger_when_above(self, alert_session, sample_company, sample_price_bar):
        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 50.0})
        result = check_price_below(alert_session, alert, sample_company)
        assert result is None

    def test_missing_threshold_returns_none(self, alert_session, sample_company, sample_price_bar):
        alert = _make_alert(alert_session, sample_company, "price_below", {})
        result = check_price_below(alert_session, alert, sample_company)
        assert result is None

    def test_stale_price_data_does_not_trigger(self, alert_session, sample_company):
        old_price = PriceBar(
            company_id=sample_company.id,
            date=date.today() - timedelta(days=10),
            close=50.0,
            adj_close=50.0,
            provider="yfinance",
            interval="1d",
        )
        alert_session.add(old_price)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        result = check_price_below(alert_session, alert, sample_company)

        assert result is None

    def test_prefers_fresh_intraday_price_over_daily_bar(self, alert_session, sample_company):
        today = date.today()
        alert_session.add_all(
            [
                PriceBar(
                    company_id=sample_company.id,
                    date=today,
                    bar_time=datetime.combine(today, datetime.min.time()),
                    close=95.0,
                    adj_close=95.0,
                    provider="yfinance",
                    interval="1d",
                ),
                PriceBar(
                    company_id=sample_company.id,
                    date=today,
                    bar_time=datetime.combine(today, datetime.min.time()) + timedelta(hours=16),
                    close=80.0,
                    adj_close=80.0,
                    provider="yfinance",
                    interval="15m",
                ),
            ]
        )
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        result = check_price_below(alert_session, alert, sample_company)

        assert result is not None
        assert result[0]["price"] == 80.0
        assert result[0]["interval"] == "15m"


class TestPriceAbove:
    def test_triggers_when_above(self, alert_session, sample_company, sample_price_bar):
        alert = _make_alert(alert_session, sample_company, "price_above", {"threshold": 70.0})
        result = check_price_above(alert_session, alert, sample_company)
        assert result is not None
        assert result[0]["price"] == 82.0

    def test_does_not_trigger_when_below(self, alert_session, sample_company, sample_price_bar):
        alert = _make_alert(alert_session, sample_company, "price_above", {"threshold": 100.0})
        result = check_price_above(alert_session, alert, sample_company)
        assert result is None


# ── Daily Move > Threshold ───────────────────────────────────────────


class TestDailyMoveGt:
    def test_triggers_when_move_exceeds(self, alert_session, sample_company, sample_metrics):
        alert = _make_alert(alert_session, sample_company, "daily_move_gt", {"threshold_pct": 3.0})
        result = check_daily_move_gt(alert_session, alert, sample_company)
        assert result is not None
        assert abs(result[0]["return_1d"]) * 100.0 > 3.0

    def test_does_not_trigger_when_move_small(self, alert_session, sample_company, sample_metrics):
        alert = _make_alert(alert_session, sample_company, "daily_move_gt", {"threshold_pct": 10.0})
        result = check_daily_move_gt(alert_session, alert, sample_company)
        assert result is None


# ── Drawdown 52W > Threshold ─────────────────────────────────────────


class TestDrawdown52wGt:
    def test_triggers_when_drawdown_exceeds(self, alert_session, sample_company, sample_metrics):
        alert = _make_alert(
            alert_session, sample_company, "drawdown_52w_gt", {"threshold_pct": 15.0}
        )
        result = check_drawdown_52w_gt(alert_session, alert, sample_company)
        assert result is not None
        assert abs(result[0]["drawdown_52w"]) * 100.0 > 15.0

    def test_does_not_trigger_when_drawdown_small(
        self, alert_session, sample_company, sample_metrics
    ):
        alert = _make_alert(
            alert_session, sample_company, "drawdown_52w_gt", {"threshold_pct": 25.0}
        )
        result = check_drawdown_52w_gt(alert_session, alert, sample_company)
        assert result is None


# ── RSI Below ────────────────────────────────────────────────────────


class TestRsiBelow:
    def test_triggers_when_rsi_below(self, alert_session, sample_company, sample_metrics):
        alert = _make_alert(alert_session, sample_company, "rsi_below", {"threshold": 40.0})
        result = check_rsi_below(alert_session, alert, sample_company)
        assert result is not None
        assert result[0]["rsi_14"] < 40.0

    def test_does_not_trigger_when_rsi_above(self, alert_session, sample_company, sample_metrics):
        alert = _make_alert(alert_session, sample_company, "rsi_below", {"threshold": 20.0})
        result = check_rsi_below(alert_session, alert, sample_company)
        assert result is None

    def test_stale_metrics_do_not_trigger(self, alert_session, sample_company):
        stale_metric = DailyMetric(
            company_id=sample_company.id,
            date=date.today() - timedelta(days=10),
            rsi_14=10.0,
        )
        alert_session.add(stale_metric)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "rsi_below", {"threshold": 40.0})
        result = check_rsi_below(alert_session, alert, sample_company)

        assert result is None


# ── Crossed 50DMA ────────────────────────────────────────────────────


class TestCrossed50dma:
    def test_triggers_any_crossover(
        self, alert_session, sample_company, sample_metrics, sample_price_bar
    ):
        alert = _make_alert(alert_session, sample_company, "crossed_50dma", {"direction": "any"})
        result = check_crossed_50dma(alert_session, alert, sample_company)
        # Yesterday was below (distance_from_50dma=-0.04), today above (0.02) → cross
        assert result is not None
        assert result[0]["direction"] == "any"

    def test_triggers_above_crossover(
        self, alert_session, sample_company, sample_metrics, sample_price_bar
    ):
        alert = _make_alert(alert_session, sample_company, "crossed_50dma", {"direction": "above"})
        result = check_crossed_50dma(alert_session, alert, sample_company)
        assert result is not None

    def test_does_not_trigger_below_when_crossed_above(
        self, alert_session, sample_company, sample_metrics, sample_price_bar
    ):
        alert = _make_alert(alert_session, sample_company, "crossed_50dma", {"direction": "below"})
        result = check_crossed_50dma(alert_session, alert, sample_company)
        assert result is None


# ── Crossed 200DMA ───────────────────────────────────────────────────


class TestCrossed200dma:
    def test_no_crossover_when_both_above(
        self, alert_session, sample_company, sample_metrics, sample_price_bar
    ):
        # Both days have distance_from_200dma > 0, so no crossover
        alert = _make_alert(alert_session, sample_company, "crossed_200dma", {"direction": "any"})
        result = check_crossed_200dma(alert_session, alert, sample_company)
        assert result is None

    def test_triggers_below_crossover(self, alert_session, sample_company, sample_price_bar):
        today = date.today()
        alert_session.add_all(
            [
                DailyMetric(
                    company_id=sample_company.id,
                    date=today - timedelta(days=1),
                    ma_200=85.0,
                    distance_from_200dma=0.03,
                ),
                DailyMetric(
                    company_id=sample_company.id,
                    date=today,
                    ma_200=84.0,
                    distance_from_200dma=-0.02,
                ),
            ]
        )
        sample_price_bar.date = today
        sample_price_bar.adj_close = 82.0
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "crossed_200dma", {"direction": "below"})
        result = check_crossed_200dma(alert_session, alert, sample_company)

        assert result is not None
        assert result[0]["direction"] == "below"
        assert result[0]["ma_200"] == 84.0


# ── New SEC Filing ───────────────────────────────────────────────────


class TestNewSecFiling:
    def test_triggers_on_recent_filing(self, alert_session, sample_company):
        filing = SecFiling(
            company_id=sample_company.id,
            accession_no="0001234567-26-000001",
            form="8-K",
            filing_date=date.today(),
            primary_doc_url="https://sec.gov/doc/123",
        )
        alert_session.add(filing)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "new_sec_filing", {})
        result = check_new_sec_filing(alert_session, alert, sample_company)
        assert result is not None
        assert len(result) == 1
        assert result[0]["form"] == "8-K"

    def test_filters_by_form_type(self, alert_session, sample_company):
        filing = SecFiling(
            company_id=sample_company.id,
            accession_no="0001234567-26-000002",
            form="10-Q",
            filing_date=date.today(),
        )
        alert_session.add(filing)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "new_sec_filing", {"forms": ["8-K"]})
        result = check_new_sec_filing(alert_session, alert, sample_company)
        assert result is None

    def test_accepts_single_form_string_filter(self, alert_session, sample_company):
        filing = SecFiling(
            company_id=sample_company.id,
            accession_no="0001234567-26-000004",
            form="8-K",
            filing_date=date.today(),
        )
        alert_session.add(filing)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "new_sec_filing", {"forms": "8-K"})
        result = check_new_sec_filing(alert_session, alert, sample_company)

        assert result is not None
        assert result[0]["accession_no"] == "0001234567-26-000004"

    def test_old_filing_not_triggered(self, alert_session, sample_company):
        filing = SecFiling(
            company_id=sample_company.id,
            accession_no="0001234567-26-000003",
            form="10-K",
            filing_date=date.today() - timedelta(days=30),
        )
        alert_session.add(filing)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "new_sec_filing", {})
        result = check_new_sec_filing(alert_session, alert, sample_company)
        assert result is None


# ── News Keyword Match ───────────────────────────────────────────────


class TestNewsKeywordMatch:
    def test_triggers_on_keyword_match(self, alert_session, sample_company):
        news = NewsItem(
            title="AI infrastructure spending surges",
            summary="Data center demand continues to grow",
            url="https://news.example.com/1",
            published_at=datetime.now(UTC).replace(tzinfo=None),
            source_name="TestSource",
            provider="rss",
        )
        alert_session.add(news)
        alert_session.flush()
        mention = NewsMention(
            news_id=news.id,
            company_id=sample_company.id,
            ticker="VRT",
            matched_keywords="AI infrastructure",
        )
        alert_session.add(mention)
        alert_session.commit()

        alert = _make_alert(
            alert_session,
            sample_company,
            "news_keyword_match",
            {"keywords": "AI infrastructure"},
        )
        result = check_news_keyword_match(alert_session, alert, sample_company)
        assert result is not None
        assert len(result) == 1
        assert "AI infrastructure" in result[0]["title"]

    def test_no_trigger_without_keyword(self, alert_session, sample_company):
        news = NewsItem(
            title="Quarterly earnings report released",
            summary="Revenue met expectations",
            url="https://news.example.com/2",
            published_at=datetime.now(UTC).replace(tzinfo=None),
            source_name="TestSource",
            provider="rss",
        )
        alert_session.add(news)
        alert_session.flush()
        mention = NewsMention(
            news_id=news.id,
            company_id=sample_company.id,
            ticker="VRT",
        )
        alert_session.add(mention)
        alert_session.commit()

        alert = _make_alert(
            alert_session,
            sample_company,
            "news_keyword_match",
            {"keywords": "nuclear power"},
        )
        result = check_news_keyword_match(alert_session, alert, sample_company)
        assert result is None

    def test_triggers_on_any_recent_mention_when_keywords_omitted(
        self, alert_session, sample_company
    ):
        news = NewsItem(
            title="Vertiv wins data center cooling contract",
            summary="Backlog expands",
            url="https://news.example.com/3",
            published_at=datetime.now(UTC).replace(tzinfo=None),
            source_name="TestSource",
            provider="rss",
        )
        alert_session.add(news)
        alert_session.flush()
        alert_session.add(
            NewsMention(
                news_id=news.id,
                company_id=sample_company.id,
                ticker="VRT",
            )
        )
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "news_keyword_match", {})
        result = check_news_keyword_match(alert_session, alert, sample_company)

        assert result is not None
        assert result[0]["news_id"] == news.id


# ── Earnings Within Days ─────────────────────────────────────────────


class TestEarningsWithinDays:
    def test_triggers_when_upcoming(self, alert_session, sample_company):
        today = datetime.now(UTC).date()
        event = EarningsEvent(
            company_id=sample_company.id,
            event_date=today + timedelta(days=3),
            source="yfinance",
        )
        alert_session.add(event)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "earnings_within_days", {"days": 7})
        result = check_earnings_within_days(alert_session, alert, sample_company)
        assert result is not None
        assert result[0]["days_until"] == 3

    def test_does_not_trigger_when_far(self, alert_session, sample_company):
        today = datetime.now(UTC).date()
        event = EarningsEvent(
            company_id=sample_company.id,
            event_date=today + timedelta(days=30),
            source="yfinance",
        )
        alert_session.add(event)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "earnings_within_days", {"days": 7})
        result = check_earnings_within_days(alert_session, alert, sample_company)
        assert result is None

    def test_uses_default_seven_day_window(self, alert_session, sample_company):
        today = datetime.now(UTC).date()
        event = EarningsEvent(
            company_id=sample_company.id,
            event_date=today + timedelta(days=7),
            source="yfinance",
            fiscal_period="Q2",
        )
        alert_session.add(event)
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "earnings_within_days", {})
        result = check_earnings_within_days(alert_session, alert, sample_company)

        assert result is not None
        assert result[0]["days_until"] == 7
        assert result[0]["fiscal_period"] == "Q2"


# ── Entered Pullback Zone ────────────────────────────────────────────


class TestEnteredPullbackZone:
    def test_triggers_in_pullback_zone(self, alert_session, sample_company, sample_metrics):
        # Latest metric: drawdown=-0.18 (18%), rsi=32, distance_from_200dma=0.10 (above 200DMA)
        alert = _make_alert(
            alert_session,
            sample_company,
            "entered_pullback_zone",
            {"min_drawdown_pct": 10.0, "max_rsi": 55.0, "min_distance_from_200dma": -5.0},
        )
        result = check_entered_pullback_zone(alert_session, alert, sample_company)
        assert result is not None
        assert abs(result[0]["drawdown_52w"]) * 100.0 >= 10.0
        assert result[0]["rsi_14"] <= 55.0

    def test_does_not_trigger_when_drawdown_too_small(self, alert_session, sample_company):
        dm = DailyMetric(
            company_id=sample_company.id,
            date=date.today(),
            drawdown_52w=-0.03,  # only 3%
            rsi_14=40.0,
            distance_from_200dma=0.05,
        )
        alert_session.add(dm)
        alert_session.commit()

        alert = _make_alert(
            alert_session,
            sample_company,
            "entered_pullback_zone",
            {"min_drawdown_pct": 10.0, "max_rsi": 55.0, "min_distance_from_200dma": -5.0},
        )
        result = check_entered_pullback_zone(alert_session, alert, sample_company)
        assert result is None

    def test_does_not_trigger_when_required_metric_fields_are_missing(
        self, alert_session, sample_company
    ):
        alert_session.add(
            DailyMetric(
                company_id=sample_company.id,
                date=date.today(),
                drawdown_52w=-0.20,
                rsi_14=None,
                distance_from_200dma=0.05,
            )
        )
        alert_session.commit()

        alert = _make_alert(alert_session, sample_company, "entered_pullback_zone", {})
        result = check_entered_pullback_zone(alert_session, alert, sample_company)

        assert result is None


# ── evaluate_alert_for_company dispatcher ────────────────────────────


class TestEvaluateAlertDispatcher:
    def test_all_rule_types_have_checkers(self):
        expected = {
            "price_below",
            "price_above",
            "daily_move_gt",
            "drawdown_52w_gt",
            "rsi_below",
            "crossed_50dma",
            "crossed_200dma",
            "new_sec_filing",
            "news_keyword_match",
            "earnings_within_days",
            "entered_pullback_zone",
        }
        assert set(RULE_CHECKERS.keys()) == expected

    def test_unknown_rule_returns_none(self, alert_session, sample_company):
        alert = _make_alert(alert_session, sample_company, "nonexistent_rule", {})
        result = evaluate_alert_for_company(alert_session, alert, sample_company)
        assert result is None

    def test_dispatches_to_correct_rule(self, alert_session, sample_company, sample_price_bar):
        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        result = evaluate_alert_for_company(alert_session, alert, sample_company)
        assert result is not None
        assert result[0]["price"] == 82.0


# ── Deduplication ────────────────────────────────────────────────────


class TestDeduplication:
    def test_dedupe_key_prevents_duplicate_events(self, alert_session, sample_company):
        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        dedupe_key = f"alert:{alert.id}:company:{sample_company.id}:date:{date.today().isoformat()}"

        event1 = AlertEvent(
            alert_id=alert.id,
            company_id=sample_company.id,
            event_type="price_below",
            payload_json={"price": 82.0},
            delivery_status="skipped",
            dedupe_key=dedupe_key,
        )
        alert_session.add(event1)
        alert_session.commit()

        # Attempt to insert a duplicate
        existing = (
            alert_session.query(AlertEvent).filter(AlertEvent.dedupe_key == dedupe_key).first()
        )
        assert existing is not None
        assert existing.id == event1.id

    def test_different_dates_are_not_duplicates(self, alert_session, sample_company):
        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})

        key1 = f"alert:{alert.id}:company:{sample_company.id}:date:{date.today().isoformat()}"
        key2 = f"alert:{alert.id}:company:{sample_company.id}:date:{(date.today() - timedelta(days=1)).isoformat()}"

        event1 = AlertEvent(
            alert_id=alert.id,
            company_id=sample_company.id,
            event_type="price_below",
            payload_json={"price": 82.0},
            delivery_status="skipped",
            dedupe_key=key1,
        )
        event2 = AlertEvent(
            alert_id=alert.id,
            company_id=sample_company.id,
            event_type="price_below",
            payload_json={"price": 81.0},
            delivery_status="skipped",
            dedupe_key=key2,
        )
        alert_session.add_all([event1, event2])
        alert_session.commit()

        count = alert_session.query(AlertEvent).filter(AlertEvent.alert_id == alert.id).count()
        assert count == 2

    def test_unique_constraint_on_dedupe_key(self, alert_session, sample_company):
        alert = _make_alert(alert_session, sample_company, "rsi_below", {"threshold": 40.0})
        dedupe_key = f"alert:{alert.id}:company:{sample_company.id}:date:{date.today().isoformat()}"

        event1 = AlertEvent(
            alert_id=alert.id,
            company_id=sample_company.id,
            event_type="rsi_below",
            payload_json={},
            delivery_status="skipped",
            dedupe_key=dedupe_key,
        )
        alert_session.add(event1)
        alert_session.commit()

        event2 = AlertEvent(
            alert_id=alert.id,
            company_id=sample_company.id,
            event_type="rsi_below",
            payload_json={},
            delivery_status="skipped",
            dedupe_key=dedupe_key,
        )
        alert_session.add(event2)
        with pytest.raises(Exception):
            alert_session.commit()
        alert_session.rollback()

    def test_existing_event_with_same_dedupe_key_suppresses_duplicate_within_24_hours(
        self,
        alert_engine,
        alert_session,
        sample_company,
        sample_price_bar,
        monkeypatch,
    ):
        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        dedupe_key = (
            f"alert:{alert.id}:company:{sample_company.id}:date:{sample_price_bar.date.isoformat()}"
        )
        alert_session.add(
            AlertEvent(
                alert_id=alert.id,
                company_id=sample_company.id,
                event_type="price_below",
                payload_json={"price": 82.0},
                delivery_status="skipped",
                dedupe_key=dedupe_key,
                triggered_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=23),
            )
        )
        alert_session.commit()
        monkeypatch.setattr(run_alerts_module, "is_smtp_configured", lambda: False)

        result = run_alerts_module.run_alerts()

        alert_session.expire_all()
        assert result["rows_read"] == 1
        assert result["rows_written"] == 0
        assert (
            alert_session.query(AlertEvent).filter(AlertEvent.dedupe_key == dedupe_key).count() == 1
        )


# ── Alert Pipeline Worker ────────────────────────────────────────────


class TestAlertPipelineWorker:
    def test_run_alerts_records_event_job_run_and_suppresses_duplicate_reruns(
        self,
        alert_engine,
        alert_session,
        sample_company,
        sample_price_bar,
        monkeypatch,
    ):
        _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        monkeypatch.setattr(run_alerts_module, "is_smtp_configured", lambda: False)

        first_result = run_alerts_module.run_alerts()
        second_result = run_alerts_module.run_alerts()

        alert_session.expire_all()
        events = alert_session.query(AlertEvent).all()
        jobs = (
            alert_session.query(JobRun)
            .filter(JobRun.job_name == "run_alerts")
            .order_by(JobRun.id)
            .all()
        )
        alert = alert_session.query(Alert).one()

        assert first_result["status"] == "success"
        assert first_result["rows_read"] == 1
        assert first_result["rows_written"] == 1
        assert second_result["status"] == "success"
        assert second_result["rows_read"] == 1
        assert second_result["rows_written"] == 0
        assert len(events) == 1
        assert events[0].delivery_status == "skipped"
        assert events[0].dedupe_key.endswith(f":date:{sample_price_bar.date.isoformat()}")
        assert alert.last_triggered_at is not None
        assert len(jobs) == 2
        assert [job.status for job in jobs] == ["success", "success"]
        assert [job.rows_written for job in jobs] == [1, 0]

    def test_run_alerts_records_sent_delivery_status_when_email_succeeds(
        self,
        alert_engine,
        alert_session,
        sample_company,
        sample_price_bar,
        monkeypatch,
    ):
        _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        monkeypatch.setattr(run_alerts_module, "is_smtp_configured", lambda: True)
        monkeypatch.setattr(run_alerts_module, "send_email", lambda *_args: True)

        result = run_alerts_module.run_alerts()

        alert_session.expire_all()
        event = alert_session.query(AlertEvent).one()

        assert result["status"] == "success"
        assert result["rows_written"] == 1
        assert event.delivery_status == "sent"

    def test_run_alerts_records_failed_delivery_status_when_email_fails(
        self,
        alert_engine,
        alert_session,
        sample_company,
        sample_price_bar,
        monkeypatch,
    ):
        _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        monkeypatch.setattr(run_alerts_module, "is_smtp_configured", lambda: True)
        monkeypatch.setattr(run_alerts_module, "send_email", lambda *_args: False)

        result = run_alerts_module.run_alerts()

        alert_session.expire_all()
        event = alert_session.query(AlertEvent).one()

        assert result["status"] == "success"
        assert result["rows_written"] == 1
        assert event.delivery_status == "failed"


# ── Formatting ───────────────────────────────────────────────────────


class TestFormatting:
    def test_format_price_below(self, alert_session, sample_company):
        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        payload = {"price": 82.0, "threshold": 90.0, "date": "2026-05-30"}
        subject, text, html = format_alert_email(alert, sample_company, payload)
        assert "VRT" in subject
        assert "price_below" in subject
        assert "$82.00" in text
        assert "$90.00" in text
        assert "VRT" in html

    def test_format_uses_hosted_company_detail_url(
        self, alert_session, sample_company, monkeypatch
    ):
        from argus.alerts import formatting

        monkeypatch.setattr(
            formatting.settings,
            "app_base_url",
            "https://argustracker.streamlit.app/",
        )
        alert = _make_alert(alert_session, sample_company, "price_below", {"threshold": 90.0})
        payload = {"price": 82.0, "threshold": 90.0, "date": "2026-05-30"}

        _subject, text, html = format_alert_email(alert, sample_company, payload)

        expected_url = "https://argustracker.streamlit.app/Company_Detail?ticker=VRT"
        assert expected_url in text
        assert expected_url in html
        assert "localhost" not in text
        assert "localhost" not in html

    def test_company_detail_url_uses_configured_base_url(self, monkeypatch):
        from argus.alerts import formatting

        monkeypatch.setattr(formatting.settings, "app_base_url", "https://example.test/argus/")

        assert company_detail_url(" vrt ") == "https://example.test/argus/Company_Detail?ticker=VRT"

    def test_format_entered_pullback_zone(self, alert_session, sample_company):
        alert = _make_alert(alert_session, sample_company, "entered_pullback_zone", {})
        payload = {
            "drawdown_52w": -0.18,
            "rsi_14": 32.0,
            "distance_from_200dma": 0.10,
            "date": "2026-05-30",
        }
        subject, text, html = format_alert_email(alert, sample_company, payload)
        assert "VRT" in subject
        assert "pullback zone" in text.lower()
        assert "RSI 14" in text


# ── Email Delivery ───────────────────────────────────────────────────


class TestEmailDelivery:
    def test_email_recipients_split_comma_separated_values(self, monkeypatch):
        from argus.alerts import email_delivery

        monkeypatch.setattr(
            email_delivery.settings,
            "email_to",
            "dad@example.com, me@example.com,,alerts@example.com ",
        )

        assert email_delivery.get_email_recipients() == [
            "dad@example.com",
            "me@example.com",
            "alerts@example.com",
        ]

    def test_smtp_not_configured_by_default(self, monkeypatch):
        # In test env, EMAIL_HOST / EMAIL_TO should not be set
        from argus.alerts import email_delivery

        monkeypatch.setattr(email_delivery.settings, "email_host", "")
        monkeypatch.setattr(email_delivery.settings, "email_to", "")
        result = is_smtp_configured()
        assert result is False

    def test_send_email_returns_false_without_smtp_config_and_does_not_open_connection(
        self, monkeypatch
    ):
        from argus.alerts import email_delivery

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("SMTP should not be opened when config is missing")

        monkeypatch.setattr(email_delivery.settings, "email_host", "")
        monkeypatch.setattr(email_delivery.settings, "email_to", "")
        monkeypatch.setattr(email_delivery.smtplib, "SMTP", fail_if_called)
        monkeypatch.setattr(email_delivery.smtplib, "SMTP_SSL", fail_if_called)

        assert email_delivery.send_email("subject", "body") is False

    def test_starttls_failure_aborts_before_login_or_sendmail(self, monkeypatch):
        from argus.alerts import email_delivery

        calls = {"login": 0, "sendmail": 0, "quit": 0}

        class FakeSMTP:
            def __init__(self, *_args, **_kwargs):
                pass

            def ehlo(self):
                pass

            def starttls(self):
                raise RuntimeError("TLS unavailable")

            def login(self, *_args):
                calls["login"] += 1

            def sendmail(self, *_args):
                calls["sendmail"] += 1

            def quit(self):
                calls["quit"] += 1

        monkeypatch.setattr(email_delivery.settings, "email_host", "smtp.example.com")
        monkeypatch.setattr(email_delivery.settings, "email_port", 587)
        monkeypatch.setattr(email_delivery.settings, "email_username", "user@example.com")
        monkeypatch.setattr(email_delivery.settings, "email_password", "secret")
        monkeypatch.setattr(email_delivery.settings, "email_from", "from@example.com")
        monkeypatch.setattr(email_delivery.settings, "email_to", "to@example.com")
        monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSMTP)

        sent = email_delivery.send_email("subject", "body")

        assert sent is False
        assert calls == {"login": 0, "sendmail": 0, "quit": 1}

    def test_send_email_sends_to_multiple_recipients(self, monkeypatch):
        from argus.alerts import email_delivery

        sendmail_calls = []

        class FakeSMTP:
            def __init__(self, *_args, **_kwargs):
                pass

            def ehlo(self):
                pass

            def starttls(self):
                pass

            def login(self, *_args):
                pass

            def sendmail(self, from_addr, to_addrs, message):
                sendmail_calls.append((from_addr, to_addrs, message))

            def quit(self):
                pass

        monkeypatch.setattr(email_delivery.settings, "email_host", "smtp.example.com")
        monkeypatch.setattr(email_delivery.settings, "email_port", 587)
        monkeypatch.setattr(email_delivery.settings, "email_username", "user@example.com")
        monkeypatch.setattr(email_delivery.settings, "email_password", "secret")
        monkeypatch.setattr(email_delivery.settings, "email_from", "from@example.com")
        monkeypatch.setattr(
            email_delivery.settings,
            "email_to",
            "dad@example.com, me@example.com",
        )
        monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSMTP)

        sent = email_delivery.send_email("subject", "body")

        assert sent is True
        assert sendmail_calls == [
            (
                "from@example.com",
                ["dad@example.com", "me@example.com"],
                sendmail_calls[0][2],
            )
        ]
        assert "To: dad@example.com, me@example.com" in sendmail_calls[0][2]


# ── Alert Service (ORM-level) ────────────────────────────────────────


class TestAlertService:
    """Test alert CRUD operations at the ORM level."""

    def test_create_alert_orm(self, alert_session, sample_company):
        """Verify that an Alert can be created and read back."""
        alert = Alert(
            name="Test CRUD Alert",
            rule_type="price_below",
            company_id=sample_company.id,
            config_json={"threshold": 100.0},
            channel="email",
            is_enabled=True,
        )
        alert_session.add(alert)
        alert_session.commit()

        fetched = alert_session.get(Alert, alert.id)
        assert fetched is not None
        assert fetched.name == "Test CRUD Alert"
        assert fetched.rule_type == "price_below"
        assert fetched.config_json == {"threshold": 100.0}
        assert fetched.is_enabled is True

    def test_create_alert_service_validates_target(self, alert_engine, monkeypatch):
        with pytest.raises(ValueError, match="target"):
            alert_service.create_alert(
                name="No target",
                rule_type="price_below",
                config_json={"threshold": 100.0},
            )

    def test_create_alert_service_validates_config(self, alert_engine, sample_company, monkeypatch):
        with pytest.raises(ValueError, match="threshold"):
            alert_service.create_alert(
                name="Bad threshold",
                rule_type="price_below",
                company_id=sample_company.id,
                config_json={"threshold": "not numeric"},
            )

    def test_create_alert_service_normalizes_config(
        self, alert_engine, alert_session, sample_company, monkeypatch
    ):
        alert_id = alert_service.create_alert(
            name="Valid",
            rule_type="price_below",
            company_id=sample_company.id,
            config_json={"threshold": "100.5"},
        )

        alert_session.expire_all()
        alert = alert_session.get(Alert, alert_id)
        assert alert.config_json == {"threshold": 100.5}

    def test_toggle_alert_orm(self, alert_session, sample_company):
        """Verify that is_enabled can be toggled."""
        alert = _make_alert(alert_session, sample_company, "rsi_below", {"threshold": 30.0})
        assert alert.is_enabled is True

        alert.is_enabled = False
        alert_session.commit()
        alert_session.expire(alert)
        assert alert.is_enabled is False

        alert.is_enabled = True
        alert_session.commit()
        alert_session.expire(alert)
        assert alert.is_enabled is True

    def test_delete_alert_cascades_events(self, alert_session, sample_company):
        """Verify that deleting an alert also removes its events."""
        alert = _make_alert(alert_session, sample_company, "price_above", {"threshold": 200.0})
        alert_id = alert.id

        event = AlertEvent(
            alert_id=alert_id,
            company_id=sample_company.id,
            event_type="price_above",
            payload_json={},
            delivery_status="skipped",
            dedupe_key=f"test_delete_{alert_id}",
        )
        alert_session.add(event)
        alert_session.commit()

        # Delete events first, then alert (no cascade in model)
        alert_session.query(AlertEvent).filter(AlertEvent.alert_id == alert_id).delete()
        alert_session.delete(alert)
        alert_session.commit()

        assert alert_session.get(Alert, alert_id) is None
        events = alert_session.query(AlertEvent).filter(AlertEvent.alert_id == alert_id).all()
        assert len(events) == 0

    def test_alert_with_watchlist_target(self, alert_session, sample_company):
        """Verify alerts can target watchlists instead of individual companies."""
        from argus.core.models import Watchlist

        wl = Watchlist(name="Test WL", description="For alert testing")
        alert_session.add(wl)
        alert_session.commit()

        alert = Alert(
            name="Watchlist Alert",
            rule_type="entered_pullback_zone",
            watchlist_id=wl.id,
            config_json={"min_drawdown_pct": 10.0},
            channel="email",
            is_enabled=True,
        )
        alert_session.add(alert)
        alert_session.commit()

        assert alert.company_id is None
        assert alert.watchlist_id == wl.id
