import sys
from unittest.mock import MagicMock, patch, call
from urllib.parse import parse_qs, urlsplit

from argus.core.auth import AUTH_COOKIE_NAME, AUTH_QUERY_PARAM, create_auth_token
from app.auth_links import company_detail_url

def test_password_protection_bypass(monkeypatch):
    """If APP_PASSWORD is not set, check_password() returns True immediately and skips login UI."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "")
    
    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.query_params = {}
    
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
            
        import app.main  # noqa: F401
        
        # Verify navigation was initialized with all app pages
        mock_st.navigation.assert_called_once()
        
        # Check st.Page calls
        page_calls = mock_st.Page.call_args_list
        assert len(page_calls) == 8
        assert page_calls[0] == call("pages/1_Dashboard.py", title="Dashboard")
        assert page_calls[1] == call("pages/2_Watchlists.py", title="Watchlists")
        assert page_calls[2] == call("pages/3_Company_Detail.py", title="Company Detail", url_path="Company_Detail")
        assert page_calls[3] == call("pages/4_Pullback_Finder.py", title="Pullback Finder")
        assert page_calls[4] == call("pages/5_News_Filings.py", title="News & Filings")
        assert page_calls[5] == call("pages/6_Calendar_Alerts.py", title="Calendar & Alerts")
        assert page_calls[6] == call("pages/8_Index_Lab.py", title="Index Lab")
        assert page_calls[7] == call("pages/7_Admin_Data_Health.py", title="Admin / Data Health")


def test_password_protection_rejects_forged_cookie(monkeypatch):
    """A user-set app_password_auth=1 cookie must not bypass the password screen."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    monkeypatch.setattr("argus.core.settings.settings.app_auth_secret", "")

    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.query_params = {}
    mock_st.context.cookies.get.return_value = "1"
    mock_st.form_submit_button.return_value = False
    mock_st.text_input.return_value = ""
    mock_st.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    mock_navigation = MagicMock()
    mock_st.navigation.return_value = mock_navigation

    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]

        import app.main  # noqa: F401

        assert mock_st.session_state["password_correct"] is False
        mock_navigation.run.assert_not_called()


def test_password_protection_accepts_signed_cookie(monkeypatch):
    """A signed legacy cookie should still authenticate a new tab without re-entering the password."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    monkeypatch.setattr("argus.core.settings.settings.app_auth_secret", "")

    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.query_params = {}
    mock_st.context.cookies.get.return_value = create_auth_token("secure123")
    mock_navigation = MagicMock()
    mock_st.navigation.return_value = mock_navigation

    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]

        import app.main  # noqa: F401

        mock_st.context.cookies.get.assert_called_with(AUTH_COOKIE_NAME)
        assert mock_st.session_state["password_correct"] is True
        assert "auth_token" in mock_st.session_state
        mock_navigation.run.assert_called_once()


def test_password_protection_accepts_signed_query_token(monkeypatch):
    """A valid inbound query token authenticates once and is removed from the URL."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    monkeypatch.setattr("argus.core.settings.settings.app_auth_secret", "")

    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.query_params = {AUTH_QUERY_PARAM: create_auth_token("secure123")}
    mock_st.context.cookies.get.return_value = None
    mock_navigation = MagicMock()
    mock_st.navigation.return_value = mock_navigation

    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]

        import app.main  # noqa: F401

        assert mock_st.session_state["password_correct"] is True
        assert "auth_token" in mock_st.session_state
        assert AUTH_QUERY_PARAM not in mock_st.query_params
        mock_navigation.run.assert_called_once()


def test_authenticated_company_link_opens_new_session_without_password(monkeypatch):
    """An internal link transports auth to a new tab, which then removes it from the URL."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    monkeypatch.setattr("argus.core.settings.settings.app_auth_secret", "")

    source_token = create_auth_token("secure123")
    monkeypatch.setattr("app.auth_links.st.session_state", {"auth_token": source_token})
    link_params = parse_qs(urlsplit(company_detail_url("NVDA")).query)

    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.query_params = {
        "ticker": link_params["ticker"][0],
        AUTH_QUERY_PARAM: link_params[AUTH_QUERY_PARAM][0],
    }
    mock_st.context.cookies.get.return_value = None
    mock_navigation = MagicMock()
    mock_st.navigation.return_value = mock_navigation

    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]

        import app.main  # noqa: F401

        assert mock_st.session_state["password_correct"] is True
        assert mock_st.session_state["auth_token"] == source_token
        assert mock_st.query_params == {"ticker": "NVDA"}
        mock_navigation.run.assert_called_once()


def test_password_protection_active_correct(monkeypatch):
    """If APP_PASSWORD is set and correct password is provided, session state is updated and app reruns."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    
    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.query_params = {}
    mock_st.form_submit_button.return_value = True
    mock_st.text_input.return_value = "secure123"
    
    # Mock st.columns to return a 3-tuple of MagicMocks to allow unpacking
    mock_cols = (MagicMock(), MagicMock(), MagicMock())
    mock_st.columns.return_value = mock_cols
    
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
            
        import app.main  # noqa: F401
        
        # Verify navigation registered all app pages to prevent 404
        mock_st.navigation.assert_called_once()
        page_calls = mock_st.Page.call_args_list
        assert len(page_calls) == 8
        
        # Check login logic set correct state
        assert mock_st.session_state["password_correct"] is True
        assert AUTH_QUERY_PARAM not in mock_st.query_params
        assert "auth_token" in mock_st.session_state
        mock_st.rerun.assert_called_once()

def test_password_protection_active_incorrect(monkeypatch):
    """If APP_PASSWORD is set and incorrect password is provided, error message is shown."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    
    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.query_params = {}
    mock_st.form_submit_button.return_value = True
    mock_st.text_input.return_value = "wrong_password"
    
    # Mock st.columns to return a 3-tuple of MagicMocks to allow unpacking
    mock_cols = (MagicMock(), MagicMock(), MagicMock())
    mock_st.columns.return_value = mock_cols
    
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
            
        import app.main  # noqa: F401
        
        # Verify navigation registered all app pages
        mock_st.navigation.assert_called_once()
        page_calls = mock_st.Page.call_args_list
        assert len(page_calls) == 8
        
        # Check error was handled
        assert mock_st.session_state.get("password_correct") is not True
        mock_st.error.assert_called_once_with("❌ Incorrect password.")
