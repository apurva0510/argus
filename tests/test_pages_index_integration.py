from datetime import date, timedelta
from pathlib import Path

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
