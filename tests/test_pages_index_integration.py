from datetime import date, datetime, timedelta
import importlib
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest
from sqlalchemy.orm import Session
from argus.core.models import Company, PriceBar


def _seed_prices(session: Session, company_id: int, start_date: date, prices: list[float]) -> None:
    for offset, price in enumerate(prices):
        session.add(
            PriceBar(
                company_id=company_id,
                date=start_date + timedelta(days=offset),
                open=price,
                high=price,
                low=price,
                close=price,
                adj_close=price,
                volume=1000,
                provider="yfinance",
                interval="1d",
            )
        )


def _seed_intraday_prices(
    session: Session,
    company_id: int,
    start_time: datetime,
    prices: list[float],
) -> None:
    for offset, price in enumerate(prices):
        bar_time = start_time + timedelta(minutes=15 * offset)
        session.add(
            PriceBar(
                company_id=company_id,
                date=bar_time.date(),
                bar_time=bar_time,
                close=price,
                adj_close=price,
                volume=1000,
                provider="yfinance",
                interval="15m",
            )
        )


def test_dashboard_and_detail_pages_load_index_data(
    sqlite_engine, monkeypatch, db_session: Session
) -> None:
    # 1. Seed some companies and prices in the test DB
    c1 = Company(symbol="A", name="A", is_active=True, is_benchmark=False)
    c2 = Company(symbol="B", name="B", is_active=True, is_benchmark=False)
    db_session.add_all([c1, c2])
    db_session.flush()

    start_date = date(2026, 5, 1)
    # Seed prices
    _seed_prices(db_session, c1.id, start_date, [10.0, 11.0, 12.1])
    _seed_prices(db_session, c2.id, start_date, [20.0, 22.0, 24.2])
    db_session.commit()

    # 2. Monkeypatch settings.database_url to point to the test sqlite file
    # and monkeypatch page-level engine getters to yield our test engine
    monkeypatch.setattr("argus.core.settings.settings.database_url", str(sqlite_engine.url))
    monkeypatch.setattr("app.pages.1_Dashboard.get_dashboard_engine", lambda: sqlite_engine)

    # 3. Import and call the dashboard page cached loading function dynamically
    import importlib

    dashboard_module = importlib.import_module("app.pages.1_Dashboard")
    load_index_data = dashboard_module.load_index_data

    # Clear cache to be safe
    load_index_data.clear()

    res = load_index_data("All")
    assert "rel_df" in res
    assert res["constituent_count"] == 2
    assert not res["rel_df"].empty

    # Verify index levels rebase to 100 on start date
    rel_df = res["rel_df"]
    assert rel_df.iloc[0]["index_level"] == pytest.approx(100.0)
    assert rel_df.iloc[1]["index_level"] == pytest.approx(110.0)
    assert rel_df.iloc[2]["index_level"] == pytest.approx(121.0)

    # Verify contributor calculations return data
    assert not res["contrib_1m"].empty
    assert res["contrib_1m"].iloc[0]["symbol"] == "A"  # Alphabetical/weight return details

    # 4. Import and call the company detail page cached loading function dynamically
    detail_module = importlib.import_module("app.pages.3_Company_Detail")
    load_index_relative_returns = detail_module.load_index_relative_returns

    load_index_relative_returns.clear()

    rel_returns = load_index_relative_returns(start_date)
    assert not rel_returns.empty
    assert "index_ret" in rel_returns
    assert rel_returns.iloc[0]["index_ret"] == pytest.approx(0.0)
    assert rel_returns.iloc[1]["index_ret"] == pytest.approx(10.0)
    assert rel_returns.iloc[2]["index_ret"] == pytest.approx(21.0)


def test_dashboard_short_index_ranges_use_intraday_data(
    sqlite_engine,
    monkeypatch,
    db_session: Session,
) -> None:
    c1 = Company(symbol="A", name="A", is_active=True, is_benchmark=False)
    c2 = Company(symbol="B", name="B", is_active=True, is_benchmark=False)
    db_session.add_all([c1, c2])
    db_session.flush()
    start_time = datetime(2026, 6, 4, 14, 0)
    _seed_intraday_prices(db_session, c1.id, start_time, [10.0, 10.5])
    _seed_intraday_prices(db_session, c2.id, start_time, [20.0, 21.0])
    db_session.commit()

    monkeypatch.setattr("argus.core.settings.settings.database_url", str(sqlite_engine.url))
    monkeypatch.setattr("app.pages.1_Dashboard.get_dashboard_engine", lambda: sqlite_engine)
    dashboard_module = importlib.import_module("app.pages.1_Dashboard")
    dashboard_module.load_index_data.clear()

    res = dashboard_module.load_index_data("1D")

    assert res["interval"] == "15m"
    assert not res["rel_df"].empty
    assert pd.to_datetime(res["rel_df"]["date"]).max() == start_time + timedelta(minutes=15)
    assert res["rel_df"].iloc[-1]["index_level"] == pytest.approx(105.0)


def test_dashboard_short_index_ranges_exclude_non_market_intraday_bars(
    sqlite_engine,
    monkeypatch,
    db_session: Session,
) -> None:
    c1 = Company(symbol="A", name="A", is_active=True, is_benchmark=False)
    c2 = Company(symbol="B", name="B", is_active=True, is_benchmark=False)
    db_session.add_all([c1, c2])
    db_session.flush()
    points = [
        (datetime(2026, 6, 4, 12, 0), 10.0, 20.0),  # premarket
        (datetime(2026, 6, 4, 14, 0), 10.0, 20.0),
        (datetime(2026, 6, 4, 14, 15), 10.5, 21.0),
        (datetime(2026, 6, 4, 20, 15), 15.0, 30.0),  # after-hours
    ]
    for bar_time, c1_price, c2_price in points:
        for company_id, price in ((c1.id, c1_price), (c2.id, c2_price)):
            db_session.add(
                PriceBar(
                    company_id=company_id,
                    date=bar_time.date(),
                    bar_time=bar_time,
                    close=price,
                    adj_close=price,
                    volume=1000,
                    provider="yfinance",
                    interval="15m",
                )
            )
    db_session.commit()

    monkeypatch.setattr("argus.core.settings.settings.database_url", str(sqlite_engine.url))
    monkeypatch.setattr("app.pages.1_Dashboard.get_dashboard_engine", lambda: sqlite_engine)
    dashboard_module = importlib.import_module("app.pages.1_Dashboard")
    dashboard_module.load_index_data.clear()

    res = dashboard_module.load_index_data("5D")

    assert pd.to_datetime(res["rel_df"]["date"]).tolist() == [
        pd.Timestamp(datetime(2026, 6, 4, 14, 0)),
        pd.Timestamp(datetime(2026, 6, 4, 14, 15)),
    ]
    assert res["rel_df"].iloc[-1]["index_level"] == pytest.approx(105.0)


def test_dashboard_1d_range_uses_latest_market_session_only(
    sqlite_engine,
    monkeypatch,
    db_session: Session,
) -> None:
    c1 = Company(symbol="A", name="A", is_active=True, is_benchmark=False)
    c2 = Company(symbol="B", name="B", is_active=True, is_benchmark=False)
    db_session.add_all([c1, c2])
    db_session.flush()
    previous_session = datetime(2026, 6, 3, 14, 0)
    latest_session = datetime(2026, 6, 4, 14, 0)
    _seed_intraday_prices(db_session, c1.id, previous_session, [8.0, 9.0])
    _seed_intraday_prices(db_session, c2.id, previous_session, [16.0, 18.0])
    _seed_intraday_prices(db_session, c1.id, latest_session, [10.0, 10.5])
    _seed_intraday_prices(db_session, c2.id, latest_session, [20.0, 21.0])
    db_session.commit()

    monkeypatch.setattr("argus.core.settings.settings.database_url", str(sqlite_engine.url))
    monkeypatch.setattr("app.pages.1_Dashboard.get_dashboard_engine", lambda: sqlite_engine)
    dashboard_module = importlib.import_module("app.pages.1_Dashboard")
    dashboard_module.load_index_data.clear()

    res = dashboard_module.load_index_data("1D")

    dates = pd.to_datetime(res["rel_df"]["date"]).tolist()
    assert dates == [latest_session, latest_session + timedelta(minutes=15)]
    assert res["rel_df"].iloc[0]["index_level"] == pytest.approx(100.0)
    assert res["rel_df"].iloc[-1]["index_level"] == pytest.approx(105.0)


def test_dashboard_5d_range_uses_latest_five_market_sessions(
    sqlite_engine,
    monkeypatch,
    db_session: Session,
) -> None:
    c1 = Company(symbol="A", name="A", is_active=True, is_benchmark=False)
    c2 = Company(symbol="B", name="B", is_active=True, is_benchmark=False)
    db_session.add_all([c1, c2])
    db_session.flush()
    session_starts = [
        datetime(2026, 6, 1, 14, 0),
        datetime(2026, 6, 2, 14, 0),
        datetime(2026, 6, 3, 14, 0),
        datetime(2026, 6, 4, 14, 0),
        datetime(2026, 6, 5, 14, 0),
        datetime(2026, 6, 8, 14, 0),
    ]
    for idx, session_start in enumerate(session_starts):
        _seed_intraday_prices(db_session, c1.id, session_start, [100.0 + idx])
        _seed_intraday_prices(db_session, c2.id, session_start, [200.0 + (idx * 2)])
    db_session.commit()

    monkeypatch.setattr("argus.core.settings.settings.database_url", str(sqlite_engine.url))
    monkeypatch.setattr("app.pages.1_Dashboard.get_dashboard_engine", lambda: sqlite_engine)
    dashboard_module = importlib.import_module("app.pages.1_Dashboard")
    dashboard_module.load_index_data.clear()

    res = dashboard_module.load_index_data("5D")

    dates = pd.to_datetime(res["rel_df"]["date"]).tolist()
    assert dates == session_starts[1:]
    assert res["rel_df"].iloc[0]["index_level"] == pytest.approx(100.0)


def test_latest_market_sessions_filters_off_hours_before_selecting_sessions() -> None:
    from argus.analytics.market_hours import filter_latest_market_sessions

    frame = pd.DataFrame(
        {
            "date": [
                datetime(2026, 6, 4, 12, 0),  # premarket
                datetime(2026, 6, 4, 14, 0),
                datetime(2026, 6, 4, 20, 15),  # after-hours
                datetime(2026, 6, 5, 14, 0),
            ],
            "adj_close": [90.0, 100.0, 150.0, 101.0],
        }
    )

    filtered = filter_latest_market_sessions(frame, 2)

    assert pd.to_datetime(filtered["date"]).tolist() == [
        pd.Timestamp(datetime(2026, 6, 4, 14, 0)),
        pd.Timestamp(datetime(2026, 6, 5, 14, 0)),
    ]
    assert filtered["adj_close"].tolist() == [100.0, 101.0]


def test_company_detail_short_ranges_use_market_sessions() -> None:
    detail_module = importlib.import_module("app.pages.3_Company_Detail")
    frame = pd.DataFrame(
        {
            "date": [
                datetime(2026, 6, 1, 14, 0),
                datetime(2026, 6, 2, 14, 0),
                datetime(2026, 6, 3, 14, 0),
                datetime(2026, 6, 4, 14, 0),
                datetime(2026, 6, 5, 14, 0),
                datetime(2026, 6, 8, 14, 0),
            ],
            "adj_close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        }
    )

    one_day, one_day_start = detail_module._filter_price_timeframe(frame, "1D", "15m")
    five_day, five_day_start = detail_module._filter_price_timeframe(frame, "5D", "15m")

    assert pd.to_datetime(one_day["date"]).tolist() == [pd.Timestamp(datetime(2026, 6, 8, 14, 0))]
    assert one_day_start == datetime(2026, 6, 8, 14, 0)
    assert pd.to_datetime(five_day["date"]).tolist() == [
        pd.Timestamp(datetime(2026, 6, 2, 14, 0)),
        pd.Timestamp(datetime(2026, 6, 3, 14, 0)),
        pd.Timestamp(datetime(2026, 6, 4, 14, 0)),
        pd.Timestamp(datetime(2026, 6, 5, 14, 0)),
        pd.Timestamp(datetime(2026, 6, 8, 14, 0)),
    ]
    assert five_day_start == datetime(2026, 6, 2, 14, 0)


def test_company_detail_short_ranges_return_empty_when_all_rows_are_off_hours() -> None:
    detail_module = importlib.import_module("app.pages.3_Company_Detail")
    frame = pd.DataFrame(
        {
            "date": [
                datetime(2026, 6, 8, 12, 0),
                datetime(2026, 6, 8, 20, 15),
            ],
            "adj_close": [100.0, 101.0],
        }
    )

    filtered, start_date = detail_module._filter_price_timeframe(frame, "1D", "15m")

    assert filtered.empty
    assert start_date is None


def test_intraday_chart_helpers_compress_non_market_time() -> None:
    dashboard_module = importlib.import_module("app.pages.1_Dashboard")
    detail_module = importlib.import_module("app.pages.3_Company_Detail")

    dashboard_fig = go.Figure()
    detail_fig = go.Figure()
    daily_fig = go.Figure()

    dashboard_module.apply_intraday_xaxis(dashboard_fig, "15m")
    detail_module.apply_intraday_xaxis(detail_fig, "15m")
    detail_module.apply_intraday_xaxis(daily_fig, "1d")

    assert dashboard_fig.layout.xaxis.type == "category"
    assert detail_fig.layout.xaxis.type == "category"
    assert daily_fig.layout.xaxis.type is None


def test_dashboard_index_contributors_link_to_company_detail_and_show_30m_stale_label() -> None:
    dashboard_source = (
        Path(__file__).resolve().parents[1] / "app" / "pages" / "1_Dashboard.py"
    ).read_text(encoding="utf-8")

    assert "company_detail_url" in dashboard_source
    assert (
        'st.column_config.LinkColumn("Ticker", display_text=r"ticker=([^&]+)")' in dashboard_source
    )
    assert "**Missing/Stale 30m Tickers**" in dashboard_source
    assert "**Missing/Stale 15m Tickers**" not in dashboard_source


def test_dashboard_links_all_visible_ticker_surfaces() -> None:
    import importlib

    dashboard_module = importlib.import_module("app.pages.1_Dashboard")

    assert dashboard_module._split_tickers("ETN,VRT") == ["ETN", "VRT"]
    assert dashboard_module._ticker_markdown("NVDA") == "[NVDA](/Company_Detail?ticker=NVDA)"


def test_company_detail_52w_range_avoids_markdown_math_parsing() -> None:
    detail_module = importlib.import_module("app.pages.3_Company_Detail")

    assert detail_module._fmt_price_range(4.05, 16.85) == "&#36;4.05 - &#36;16.85"
    assert detail_module._fmt_price_range(None, 16.85) == "n/a"


def test_company_detail_latest_price_ignores_stale_intraday_data() -> None:
    detail_module = importlib.import_module("app.pages.3_Company_Detail")

    daily = pd.DataFrame(
        [{"date": date(2026, 6, 4), "adj_close": 155.0}]
    )
    intraday = pd.DataFrame(
        [{"date": datetime(2026, 6, 3, 20, 0), "adj_close": 150.0}]
    )

    assert detail_module._latest_price_from_history(daily, intraday) == 155.0


def test_company_detail_latest_price_uses_current_intraday_data() -> None:
    detail_module = importlib.import_module("app.pages.3_Company_Detail")

    daily = pd.DataFrame(
        [{"date": date(2026, 6, 4), "adj_close": 155.0}]
    )
    intraday = pd.DataFrame(
        [{"date": datetime(2026, 6, 4, 18, 0), "adj_close": 158.0}]
    )

    assert detail_module._latest_price_from_history(daily, intraday) == 158.0


def test_dashboard_recent_news_renders_multiple_ticker_links_in_dataframe(monkeypatch) -> None:
    import importlib
    import pandas as pd

    dashboard_module = importlib.import_module("app.pages.1_Dashboard")
    captured_df = []

    class MockSt:
        class column_config:
            @staticmethod
            def LinkColumn(label, **kwargs):
                return {"label": label, **kwargs}

        @staticmethod
        def dataframe(df, **kwargs):
            captured_df.append(df)

        @staticmethod
        def info(msg):
            pass

    monkeypatch.setattr("app.pages.1_Dashboard.st", MockSt)

    dashboard_module._render_recent_news(
        pd.DataFrame(
            [
                {
                    "published_at": "2026-06-01T12:00:00",
                    "title": "Power grid update",
                    "source_name": "RSS",
                    "tickers": "ETN,VRT",
                    "url": "https://example.com/story",
                }
            ]
        )
    )

    assert len(captured_df) == 1
    news_out = captured_df[0]
    assert news_out["Ticker"].tolist() == [
        "/Company_Detail?ticker=ETN",
        "/Company_Detail?ticker=VRT",
    ]
    assert news_out["Headline"].tolist() == ["Power grid update", "Power grid update"]
    assert news_out.columns.tolist() == ["Published", "Headline", "Source", "Ticker", "Link"]


def test_dashboard_theme_coverage_renders_before_empty_metrics_return() -> None:
    dashboard_source = (
        Path(__file__).resolve().parents[1] / "app" / "pages" / "1_Dashboard.py"
    ).read_text(encoding="utf-8")
    empty_message = "Earnings events will appear here after earnings ingestion is implemented."
    empty_return = 'st.info("Earnings events will appear here after earnings ingestion is implemented.")\n        _render_theme_counts(data.get("theme_counts"))\n        return'

    assert empty_message in dashboard_source
    assert empty_return in dashboard_source


def test_dashboard_uses_separate_active_and_index_constituent_counts() -> None:
    dashboard_source = (
        Path(__file__).resolve().parents[1] / "app" / "pages" / "1_Dashboard.py"
    ).read_text(encoding="utf-8")

    assert "data['active_company_count']" in dashboard_source
    assert 'data.get("index_constituent_count")' in dashboard_source
    assert 'render_plain_metric_card("Tracked Symbols", data.get("index_symbol_count"))' not in dashboard_source


def test_company_detail_formatters() -> None:
    import importlib

    detail_module = importlib.import_module("app.pages.3_Company_Detail")
    _fmt_pct_colored = detail_module._fmt_pct_colored
    _fmt_large_num = detail_module._fmt_large_num
    _fmt_multiple = detail_module._fmt_multiple

    # Test _fmt_pct_colored
    assert _fmt_pct_colored(None) == "n/a"
    assert "color: #3fb950" in _fmt_pct_colored(0.1234)
    assert "+12.34%" in _fmt_pct_colored(0.1234)
    assert "color: #f85149" in _fmt_pct_colored(-0.0567)
    assert "-5.67%" in _fmt_pct_colored(-0.0567)
    assert "color: #8b949e" in _fmt_pct_colored(0.0)
    assert "0.00%" in _fmt_pct_colored(0.0)

    # Test _fmt_multiple
    assert _fmt_multiple(None) == "n/a"
    assert _fmt_multiple(15.234) == "15.23"
    assert _fmt_multiple(-5.0) == "-5.00"

    # Test _fmt_large_num
    assert _fmt_large_num(None) == "n/a"
    assert _fmt_large_num(1.5e12) == "$1.50T"
    assert _fmt_large_num(2.75e9) == "$2.75B"
    assert _fmt_large_num(300e6) == "$300.00M"
    assert _fmt_large_num(12345.678) == "$12,345.68"
    assert _fmt_large_num(-1.5e12) == "-$1.50T"
    assert _fmt_large_num(-2.75e9) == "-$2.75B"
    assert _fmt_large_num(-300e6) == "-$300.00M"
    assert _fmt_large_num(-12345.678) == "-$12,345.68"


def test_dashboard_upcoming_earnings_none_filled(monkeypatch) -> None:
    import importlib
    import pandas as pd

    dashboard_module = importlib.import_module("app.pages.1_Dashboard")
    _render_upcoming_earnings = dashboard_module._render_upcoming_earnings

    # We mock st.dataframe and st.info to capture the input
    captured_df = []

    class MockSt:
        class column_config:
            @staticmethod
            def LinkColumn(label, **kwargs):
                return {"label": label, **kwargs}

        @staticmethod
        def dataframe(df, **kwargs):
            captured_df.append(df)

        @staticmethod
        def info(msg):
            pass

    monkeypatch.setattr("app.pages.1_Dashboard.st", MockSt)

    # Create test input DataFrame
    test_df = pd.DataFrame(
        [
            {
                "event_date": "2026-06-15",
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "fiscal_period": None,
                "source": "yfinance",
            },
            {
                "event_date": "2026-07-20",
                "symbol": "MSFT",
                "name": "Microsoft Corp.",
                "fiscal_period": "",
                "source": "yfinance",
            },
        ]
    )

    _render_upcoming_earnings(test_df)

    assert len(captured_df) == 1
    df_out = captured_df[0]
    assert df_out.iloc[0]["Fiscal Period"] == "n/a"
    assert df_out.iloc[1]["Fiscal Period"] == "n/a"
    assert df_out.iloc[0]["Ticker"] == "/Company_Detail?ticker=AAPL"
    assert df_out.iloc[1]["Ticker"] == "/Company_Detail?ticker=MSFT"
