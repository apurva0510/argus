import importlib
from unittest.mock import MagicMock


class FakeQueryParams:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def __contains__(self, key):
        return key in self.values

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value

    def __delitem__(self, key):
        del self.values[key]


class MockSessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError(key)


def test_company_detail_selectbox_query_param_sync(monkeypatch):
    company_detail = importlib.import_module("app.pages.3_Company_Detail")
    mock_st = MagicMock()
    mock_st.session_state = MockSessionState()
    mock_st.query_params = FakeQueryParams({"ticker": "MSFT"})
    monkeypatch.setattr(company_detail, "st", mock_st)
    symbols = ["AAPL", "MSFT", "NVDA"]

    mock_st.selectbox.return_value = "MSFT"
    assert company_detail.select_company_ticker(symbols) == "MSFT"
    assert mock_st.session_state["selected_ticker"] == "MSFT"
    assert mock_st.query_params["ticker"] == "MSFT"

    mock_st.session_state["ticker_selector_selectbox"] = "AAPL"
    mock_st.selectbox.return_value = "AAPL"
    assert company_detail.select_company_ticker(symbols) == "AAPL"
    assert mock_st.session_state["selected_ticker"] == "AAPL"
    assert mock_st.session_state["last_query_ticker"] == "AAPL"
    assert mock_st.query_params["ticker"] == "AAPL"


def test_load_company_upcoming_events(sqlite_engine, db_session, monkeypatch):
    import importlib

    company_detail = importlib.import_module("app.pages.3_Company_Detail")
    from datetime import date
    from argus.core.models import Company, EarningsEvent, CatalystEvent

    # Seed using ORM models
    company = Company(symbol="AAPL", name="Apple Inc.", sector="Tech", is_active=True)
    db_session.add(company)
    db_session.flush()  # Populates company.id

    earnings = EarningsEvent(
        company_id=company.id,
        event_date=date(2026, 7, 1),
        fiscal_period="Q3",
        eps_estimate=1.50,
        revenue_estimate=80000000000.0,
        source="yfinance",
    )
    db_session.add(earnings)

    catalyst = CatalystEvent(
        company_id=company.id,
        event_type="earnings",
        date=date(2026, 7, 1),
        source_key="aapl_earning_20260701",
    )
    db_session.add(catalyst)

    db_session.commit()

    # Mock get_configured_app_engine to return our test sqlite_engine
    monkeypatch.setattr(company_detail, "get_configured_app_engine", lambda: sqlite_engine)

    # Call the load function
    result = company_detail.load_company_upcoming_events(
        company_id=company.id, today=date(2026, 6, 25)
    )

    # Assert results are loaded and mapped correctly
    assert "earnings" in result
    assert "catalysts" in result
    assert "filings" not in result

    earnings_df = result["earnings"]
    catalysts_df = result["catalysts"]

    assert len(earnings_df) == 1
    assert earnings_df.iloc[0]["fiscal_period"] == "Q3"
    assert earnings_df.iloc[0]["eps_estimate"] == 1.50
    assert earnings_df.iloc[0]["revenue_estimate"] == 80000000000.0

    assert len(catalysts_df) == 1
    assert catalysts_df.iloc[0]["event_type"] == "earnings"
