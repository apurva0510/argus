import sys
import importlib
from unittest.mock import MagicMock, patch


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
    # Mock streamlit
    mock_st = MagicMock()
    mock_st.session_state = MockSessionState()
    mock_st.query_params = FakeQueryParams({"ticker": "MSFT"})

    # Mock get_company_options to return a list of symbols
    mock_get_company_options = MagicMock(return_value=["AAPL", "MSFT", "NVDA"])

    # Mock get_company_by_symbol to avoid actual DB query
    mock_get_company_by_symbol = MagicMock(
        return_value={
            "id": 1,
            "symbol": "MSFT",
            "name": "Microsoft Corporation",
            "exchange": "NASDAQ",
            "sector": "Technology",
            "industry": "Software",
            "country": "USA",
        }
    )

    # Patches for streamlit
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        # Force reload of Company Detail module so it uses our mocked streamlit
        if "app.pages.3_Company_Detail" in sys.modules:
            del sys.modules["app.pages.3_Company_Detail"]

        company_detail = importlib.import_module("app.pages.3_Company_Detail")

        # Mock dependencies on the imported module using monkeypatch
        monkeypatch.setattr(company_detail, "get_company_options", mock_get_company_options)
        monkeypatch.setattr(company_detail, "get_company_by_symbol", mock_get_company_by_symbol)
        monkeypatch.setattr(company_detail, "render_sidebar_navigation", MagicMock())
        monkeypatch.setattr(company_detail, "get_company_metrics", MagicMock(return_value={}))

        # --- First Page Load (with query param ticker=MSFT) ---
        # The selectbox will return MSFT
        mock_st.selectbox.return_value = "MSFT"

        # Run render_company_detail. Any exception after metric card loading is ignored
        try:
            company_detail.render_company_detail()
        except Exception:
            pass

        # Verify state was set to MSFT
        assert mock_st.session_state.get("selected_ticker") == "MSFT"
        assert mock_st.session_state.get("last_query_ticker") == "MSFT"
        assert mock_st.query_params.get("ticker") == "MSFT"

        # --- Second Page Load (User changed selectbox to AAPL, query param is still MSFT) ---
        # Streamlit sets key value in session state before script runs
        mock_st.session_state["ticker_selector_selectbox"] = "AAPL"
        mock_st.selectbox.return_value = "AAPL"

        try:
            company_detail.render_company_detail()
        except Exception:
            pass

        # Verify the selectbox choice AAPL was NOT overridden back to MSFT,
        # and instead the state and query param were successfully synced to AAPL.
        assert mock_st.session_state.get("selected_ticker") == "AAPL"
        assert mock_st.session_state.get("last_query_ticker") == "AAPL"
        assert mock_st.query_params.get("ticker") == "AAPL"


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
