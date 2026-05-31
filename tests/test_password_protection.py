import sys
from unittest.mock import MagicMock, patch, call

from argus.core.auth import AUTH_COOKIE_NAME, create_auth_token

def test_password_protection_bypass(monkeypatch):
    """If APP_PASSWORD is not set, check_password() returns True immediately and skips login UI."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "")
    
    mock_st = MagicMock()
    mock_st.session_state = {}
    
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
            
        import app.main  # noqa: F401
        
        # Verify navigation was initialized with the 5 dashboard pages
        mock_st.navigation.assert_called_once()
        
        # Check st.Page calls
        page_calls = mock_st.Page.call_args_list
        assert len(page_calls) == 5
        assert page_calls[0] == call("pages/1_Dashboard.py", title="Dashboard")
        assert page_calls[1] == call("pages/2_Watchlists.py", title="Watchlists")
        assert page_calls[2] == call("pages/3_Company_Detail.py", title="Company Detail", url_path="Company_Detail")
        assert page_calls[3] == call("pages/4_Pullback_Finder.py", title="Pullback Finder")
        assert page_calls[4] == call("pages/5_News_Filings_Alerts.py", title="News Filings Alerts")


def test_password_protection_rejects_forged_cookie(monkeypatch):
    """A user-set app_password_auth=1 cookie must not bypass the password screen."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    monkeypatch.setattr("argus.core.settings.settings.app_auth_secret", "")

    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.context.cookies.get.return_value = "1"
    mock_st.button.return_value = False
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
    """A signed cookie should authenticate a new tab without re-entering the password."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    monkeypatch.setattr("argus.core.settings.settings.app_auth_secret", "")

    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.context.cookies.get.return_value = create_auth_token("secure123")
    mock_navigation = MagicMock()
    mock_st.navigation.return_value = mock_navigation

    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]

        import app.main  # noqa: F401

        mock_st.context.cookies.get.assert_called_with(AUTH_COOKIE_NAME)
        assert mock_st.session_state["password_correct"] is True
        mock_navigation.run.assert_called_once()
        mock_st.iframe.assert_called()
        assert "data:text/html" in mock_st.iframe.call_args.args[0]

def test_password_protection_active_correct(monkeypatch):
    """If APP_PASSWORD is set and correct password is provided, session state is updated and app reruns."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    
    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.button.return_value = True
    mock_st.text_input.return_value = "secure123"
    
    # Mock st.columns to return a 3-tuple of MagicMocks to allow unpacking
    mock_cols = (MagicMock(), MagicMock(), MagicMock())
    mock_st.columns.return_value = mock_cols
    
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
            
        import app.main  # noqa: F401
        
        # Verify navigation registered all 5 pages to prevent 404
        mock_st.navigation.assert_called_once()
        page_calls = mock_st.Page.call_args_list
        assert len(page_calls) == 5
        
        # Check login logic set correct state
        assert mock_st.session_state["password_correct"] is True
        mock_st.rerun.assert_called_once()

def test_password_protection_active_incorrect(monkeypatch):
    """If APP_PASSWORD is set and incorrect password is provided, error message is shown."""
    monkeypatch.setattr("argus.core.settings.settings.app_password", "secure123")
    
    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.button.return_value = True
    mock_st.text_input.return_value = "wrong_password"
    
    # Mock st.columns to return a 3-tuple of MagicMocks to allow unpacking
    mock_cols = (MagicMock(), MagicMock(), MagicMock())
    mock_st.columns.return_value = mock_cols
    
    with patch.dict("sys.modules", {"streamlit": mock_st}):
        if "app.main" in sys.modules:
            del sys.modules["app.main"]
            
        import app.main  # noqa: F401
        
        # Verify navigation registered all 5 pages
        mock_st.navigation.assert_called_once()
        page_calls = mock_st.Page.call_args_list
        assert len(page_calls) == 5
        
        # Check error was handled
        assert mock_st.session_state.get("password_correct") is not True
        mock_st.error.assert_called_once_with("❌ Incorrect password.")
