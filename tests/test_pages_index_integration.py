from datetime import date, timedelta
import pandas as pd
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


def test_dashboard_and_detail_pages_load_index_data(sqlite_engine, monkeypatch, db_session: Session) -> None:
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
