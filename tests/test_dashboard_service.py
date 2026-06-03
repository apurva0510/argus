from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from argus.core.models import (
    Company,
    CompanyThemeExposure,
    DailyMetric,
    EarningsEvent,
    JobRun,
    NewsItem,
    PriceBar,
    SecFiling,
    Theme,
)
from argus.services.dashboard_service import (
    build_stale_reasons,
    filter_low_rsi,
    load_dashboard_data_from_engine,
    parse_optional_date,
    parse_optional_datetime,
    rank_biggest_drawdowns,
    rank_top_gainers,
    rank_top_losers,
    summarize_core_returns,
)


def test_dashboard_rankings_are_sorted_and_limited() -> None:
    metrics = pd.DataFrame(
        [
            {"symbol": "ETN", "name": "Eaton", "return_1d": 0.03, "drawdown_52w": -0.10, "rsi_14": 39.0},
            {"symbol": "VRT", "name": "Vertiv", "return_1d": 0.08, "drawdown_52w": -0.30, "rsi_14": 22.0},
            {"symbol": "CIEN", "name": "Ciena", "return_1d": -0.06, "drawdown_52w": -0.05, "rsi_14": 40.0},
            {"symbol": "PWR", "name": "Quanta", "return_1d": -0.02, "drawdown_52w": -0.45, "rsi_14": 41.0},
            {"symbol": "QQQ", "name": "QQQ", "return_1d": 0.10, "drawdown_52w": -0.01, "rsi_14": None},
            {"symbol": "ALAB", "name": "Astera", "return_1d": None, "drawdown_52w": None, "rsi_14": 18.0},
        ]
    )

    gainers = rank_top_gainers(metrics, limit=3)
    losers = rank_top_losers(metrics, limit=2)
    drawdowns = rank_biggest_drawdowns(metrics, limit=3)
    low_rsi = filter_low_rsi(metrics, threshold=40.0)

    assert gainers["symbol"].tolist() == ["QQQ", "VRT", "ETN"]
    assert losers["symbol"].tolist() == ["CIEN", "PWR"]
    assert drawdowns["symbol"].tolist() == ["PWR", "VRT", "ETN"]
    assert low_rsi["symbol"].tolist() == ["ALAB", "VRT", "ETN"]


def test_dashboard_helpers_handle_empty_or_missing_metric_columns() -> None:
    empty = pd.DataFrame()
    missing_columns = pd.DataFrame([{"symbol": "ETN", "name": "Eaton"}])

    assert rank_top_gainers(empty).empty
    assert rank_top_losers(missing_columns).empty
    assert rank_biggest_drawdowns(missing_columns).empty
    assert filter_low_rsi(missing_columns).empty
    assert summarize_core_returns(empty) == {
        "return_1d": None,
        "return_1w": None,
        "return_1m": None,
    }


def test_low_rsi_filter_excludes_threshold_and_missing_values() -> None:
    metrics = pd.DataFrame(
        [
            {"symbol": "A", "name": "A Co", "rsi_14": 39.9},
            {"symbol": "B", "name": "B Co", "rsi_14": 40.0},
            {"symbol": "C", "name": "C Co", "rsi_14": None},
            {"symbol": "D", "name": "D Co", "rsi_14": 20.0},
        ]
    )

    filtered = filter_low_rsi(metrics, threshold=40.0)

    assert filtered["symbol"].tolist() == ["D", "A"]


def test_core_return_summary_excludes_benchmarks_and_optional_aggressive_names() -> None:
    metrics = pd.DataFrame(
        [
            {"symbol": "ETN", "return_1d": 0.02, "return_1w": 0.04, "return_1m": 0.10},
            {"symbol": "VRT", "return_1d": 0.04, "return_1w": 0.08, "return_1m": 0.20},
            {"symbol": "QQQ", "return_1d": 0.50, "return_1w": 0.50, "return_1m": 0.50},
            {"symbol": "ALAB", "return_1d": 0.70, "return_1w": 0.70, "return_1m": 0.70},
        ]
    )

    summary = summarize_core_returns(metrics)

    assert summary["return_1d"] == pytest.approx(0.03)
    assert summary["return_1w"] == pytest.approx(0.06)
    assert summary["return_1m"] == pytest.approx(0.15)


def test_core_return_summary_returns_none_when_only_benchmarks_or_missing_values() -> None:
    metrics = pd.DataFrame(
        [
            {"symbol": "QQQ", "return_1d": 0.50, "return_1w": 0.50, "return_1m": 0.50},
            {"symbol": "NVDA", "return_1d": 0.60, "return_1w": 0.60, "return_1m": 0.60},
            {"symbol": "ETN", "return_1d": None, "return_1w": None, "return_1m": None},
        ]
    )

    assert summarize_core_returns(metrics) == {
        "return_1d": None,
        "return_1w": None,
        "return_1m": None,
    }


def test_stale_reasons_cover_missing_fresh_and_stale_dates() -> None:
    today = date(2026, 5, 30)

    assert build_stale_reasons(today, today, today=today) == []
    assert build_stale_reasons(None, None, today=today) == [
        "No price data found.",
        "No metrics data found.",
    ]
    assert build_stale_reasons(
        today - timedelta(days=4),
        today - timedelta(days=5),
        today=today,
        stale_days_threshold=3,
    ) == [
        "Prices are stale (latest date: 2026-05-26).",
        "Metrics are stale (latest date: 2026-05-25).",
    ]


def test_stale_reasons_treat_threshold_day_as_fresh() -> None:
    today = date(2026, 5, 30)

    assert build_stale_reasons(
        today - timedelta(days=3),
        today - timedelta(days=3),
        today=today,
        stale_days_threshold=3,
    ) == []


def test_parse_optional_date_and_datetime_handle_missing_values() -> None:
    assert parse_optional_date(None) is None
    assert parse_optional_date(float("nan")) is None
    assert parse_optional_date("2026-05-29") == date(2026, 5, 29)

    parsed = parse_optional_datetime("2026-05-29 20:01:00")

    assert parsed is not None
    assert parsed.isoformat() == "2026-05-29T20:01:00+00:00"
    assert parse_optional_datetime(None) is None


def test_load_dashboard_data_handles_empty_database(sqlite_engine) -> None:
    data = load_dashboard_data_from_engine(sqlite_engine)

    assert data["latest_dates"]["latest_price_date"] is None
    assert data["latest_dates"]["latest_metrics_date"] is None
    assert data["latest_metrics"].empty
    assert data["active_company_count"] == 0
    assert data["index_constituent_count"] == 0
    assert data["index_symbol_count"] == 0
    assert data["news_count"] == 0
    assert data["filings_count"] == 0
    assert data["earnings_count"] == 0
    assert data["recent_news"].empty
    assert data["recent_filings"].empty
    assert data["upcoming_earnings"].empty


def test_load_dashboard_data_uses_latest_metrics_date_counts_and_sorts(
    db_session, sqlite_engine
) -> None:
    etn = Company(symbol="ETN", name="Eaton", is_active=True)
    vrt = Company(symbol="VRT", name="Vertiv", is_active=True)
    qqq = Company(symbol="QQQ", name="QQQ", is_active=True, is_benchmark=True)
    pwr = Company(symbol="PWR", name="Quanta", is_active=True)
    inactive = Company(symbol="OLD", name="Inactive", is_active=False)
    db_session.add_all([etn, vrt, qqq, pwr, inactive])
    db_session.flush()
    ai_theme = Theme(code="ai_infrastructure", name="AI Infrastructure")
    emerging_theme = Theme(code="emerging_compute", name="Emerging Compute")
    power_theme = Theme(
        code="power_grid",
        name="Power and Grid",
        parent_theme_id=ai_theme.id,
    )
    quantum_theme = Theme(
        code="quantum_computing",
        name="Quantum Computing",
        parent_theme_id=emerging_theme.id,
    )
    ionq = Company(symbol="IONQ", name="IonQ", is_active=True)
    db_session.add_all([ai_theme, emerging_theme, power_theme, quantum_theme, ionq])
    db_session.flush()
    power_theme.parent_theme_id = ai_theme.id
    quantum_theme.parent_theme_id = emerging_theme.id

    older_date = date(2026, 5, 28)
    latest_date = date(2026, 5, 29)
    db_session.add_all(
        [
            CompanyThemeExposure(company_id=etn.id, theme_id=power_theme.id, exposure_score=4.0),
            CompanyThemeExposure(company_id=ionq.id, theme_id=quantum_theme.id, exposure_score=5.0),
            DailyMetric(company_id=etn.id, date=older_date, return_1d=-0.99),
            DailyMetric(
                company_id=etn.id,
                date=latest_date,
                return_1d=0.02,
                return_1w=0.04,
                return_1m=0.08,
                rsi_14=39.0,
                drawdown_52w=-0.10,
            ),
            DailyMetric(
                company_id=vrt.id,
                date=latest_date,
                return_1d=-0.03,
                return_1w=0.01,
                return_1m=0.05,
                rsi_14=22.0,
                drawdown_52w=-0.30,
            ),
            DailyMetric(
                company_id=qqq.id,
                date=latest_date,
                return_1d=0.50,
                return_1w=0.50,
                return_1m=0.50,
                rsi_14=None,
                drawdown_52w=-0.01,
            ),
            DailyMetric(
                company_id=pwr.id,
                date=latest_date,
                return_1d=-0.06,
                return_1w=-0.02,
                return_1m=-0.03,
                rsi_14=41.0,
                drawdown_52w=-0.45,
            ),
            PriceBar(company_id=etn.id, date=latest_date, adj_close=100.0, provider="yfinance", interval="1d"),
            PriceBar(
                company_id=vrt.id,
                date=date.today(),
                bar_time=datetime(2026, 5, 29, 16, 0),
                adj_close=101.0,
                provider="yfinance",
                interval="15m",
            ),
            JobRun(
                job_name="refresh_prices",
                started_at=datetime(2026, 5, 29, 20, 0),
                finished_at=datetime(2026, 5, 29, 20, 1),
                status="success",
            ),
            JobRun(
                job_name="compute_daily_metrics",
                started_at=datetime(2026, 5, 29, 20, 2),
                finished_at=datetime(2026, 5, 29, 20, 3),
                status="success",
            ),
            NewsItem(title="Power demand update", url="https://example.com/news"),
            SecFiling(company_id=etn.id, accession_no="0001", form="8-K"),
            EarningsEvent(company_id=etn.id, event_date=date.today() + timedelta(days=7)),
        ]
    )
    db_session.commit()

    data = load_dashboard_data_from_engine(sqlite_engine)
    metrics = data["latest_metrics"]

    assert data["active_company_count"] == 5
    assert data["index_constituent_count"] == 3
    assert data["index_symbol_count"] == 5
    assert data["news_count"] == 1
    assert data["filings_count"] == 1
    assert data["earnings_count"] == 1
    assert data["latest_dates"]["latest_price_date"] == "2026-05-29"
    assert data["latest_dates"]["latest_intraday_price_time"] == "2026-05-29 16:00:00.000000"
    assert data["latest_dates"]["latest_metrics_date"] == "2026-05-29"
    assert data["latest_dates"]["last_price_refresh_at"] == "2026-05-29 20:01:00.000000"
    assert data["latest_dates"]["last_metrics_refresh_at"] == "2026-05-29 20:03:00.000000"
    assert set(metrics["symbol"]) == {"ETN", "VRT", "QQQ", "PWR"}
    assert -0.99 not in metrics["return_1d"].tolist()

    assert rank_top_gainers(metrics, limit=2)["symbol"].tolist() == ["QQQ", "ETN"]
    assert rank_top_losers(metrics, limit=2)["symbol"].tolist() == ["PWR", "VRT"]
    assert rank_biggest_drawdowns(metrics, limit=2)["symbol"].tolist() == ["PWR", "VRT"]
    assert filter_low_rsi(metrics, threshold=40.0)["symbol"].tolist() == ["VRT", "ETN"]
    assert data["recent_news"]["title"].tolist() == ["Power demand update"]
    assert data["recent_filings"]["symbol"].tolist() == ["ETN"]
    assert data["upcoming_earnings"]["symbol"].tolist() == ["ETN"]
    assert data["intraday_stale_tickers_count"] == 4
    theme_counts = data["theme_counts"].set_index(["theme_family", "theme"])["company_count"].to_dict()
    assert theme_counts[("AI Infrastructure", "Power and Grid")] == 1
    assert theme_counts[("Emerging Compute", "Quantum Computing")] == 1


def test_load_dashboard_data_handles_price_data_without_metrics(db_session, sqlite_engine) -> None:
    company = Company(symbol="ETN", name="Eaton", is_active=True)
    db_session.add(company)
    db_session.flush()
    db_session.add(
        PriceBar(
            company_id=company.id,
            date=date(2026, 5, 29),
            adj_close=100.0,
            provider="yfinance",
            interval="1d",
        )
    )
    db_session.commit()

    data = load_dashboard_data_from_engine(sqlite_engine)

    assert data["latest_dates"]["latest_price_date"] == "2026-05-29"
    assert data["latest_dates"]["latest_metrics_date"] is None
    assert data["latest_metrics"].empty
    assert data["active_company_count"] == 1
    assert data["index_constituent_count"] == 1
    assert data["index_symbol_count"] == 1


def test_load_dashboard_data_uses_latest_metric_per_company(db_session, sqlite_engine) -> None:
    etn = Company(symbol="ETN", name="Eaton", is_active=True)
    vrt = Company(symbol="VRT", name="Vertiv", is_active=True)
    db_session.add_all([etn, vrt])
    db_session.flush()
    db_session.add_all(
        [
            DailyMetric(company_id=etn.id, date=date(2026, 5, 30), return_1d=0.03),
            DailyMetric(company_id=vrt.id, date=date(2026, 5, 29), return_1d=-0.02),
        ]
    )
    db_session.commit()

    data = load_dashboard_data_from_engine(sqlite_engine)
    metrics = data["latest_metrics"]

    assert data["latest_dates"]["latest_metrics_date"] == "2026-05-30"
    assert set(metrics["symbol"]) == {"ETN", "VRT"}
    assert metrics.set_index("symbol").loc["VRT", "date"] == "2026-05-29"


def test_get_dashboard_overview(sqlite_engine, monkeypatch, db_session) -> None:
    from sqlalchemy.orm import Session, sessionmaker
    from argus.core import db as db_module
    from argus.services.dashboard_service import get_dashboard_overview
    
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False, class_=Session),
    )
    
    # 1. Create seeded rows in database
    c1 = Company(symbol="XYZ", name="XYZ Corp", is_active=True)
    c2 = Company(symbol="ABC", name="ABC Corp", is_active=False)
    db_session.add_all([c1, c2])
    db_session.flush()
    
    db_session.add(
        PriceBar(
            company_id=c1.id,
            date=date(2026, 5, 29),
            close=100.0,
            adj_close=100.0,
            provider="yfinance",
            interval="1d"
        )
    )
    db_session.commit()
    
    # 2. Run overview function and verify counts
    overview = get_dashboard_overview()
    assert overview["tracked_companies"] == 1
    assert overview["high_priority_count"] == 0
    assert overview["owned_count"] == 0
    assert overview["price_bar_count"] == 1
    assert overview["metrics_count"] == 0
    assert overview["news_count"] == 0
    assert overview["filings_count"] == 0
