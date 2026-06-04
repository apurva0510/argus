import sys
from pathlib import Path

# Add project root to sys.path to allow absolute imports of 'app' and 'argus'
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import streamlit as st  # noqa: E402
from argus.core.auth import AUTH_COOKIE_NAME, AUTH_QUERY_PARAM, create_auth_token, validate_auth_token  # noqa: E402
from argus.core.settings import settings  # noqa: E402

st.set_page_config(page_title="Argus", page_icon="📊", layout="wide")


def _auth_secret() -> str:
    return settings.app_auth_secret or settings.app_password


def _query_param_value(name: str) -> str | None:
    value = getattr(st, "query_params", {}).get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value if isinstance(value, str) else None


def _cookie_is_authenticated() -> bool:
    token = st.context.cookies.get(AUTH_COOKIE_NAME)
    return validate_auth_token(token, _auth_secret())


def _query_token_is_authenticated() -> bool:
    token = _query_param_value(AUTH_QUERY_PARAM)
    if validate_auth_token(token, _auth_secret()):
        st.session_state["auth_token"] = token
        del st.query_params[AUTH_QUERY_PARAM]
        return True
    return False


def _issue_auth_token() -> None:
    token = create_auth_token(_auth_secret())
    st.session_state["auth_token"] = token

def render_login_screen():
    # Custom styling for premium dark glassmorphism card
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap');
        
        .stApp {
            background: linear-gradient(135deg, #0e1117 0%, #161b22 100%) !important;
            font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
        }
        
        /* Central Login Box container */
        div[data-testid="stVerticalBlock"] > div:has(.login-box-anchor) {
            max-width: 420px;
            margin: 100px auto 0 auto;
            background: rgba(22, 27, 34, 0.6);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(240, 246, 252, 0.1);
            border-radius: 16px;
            padding: 40px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4);
        }
        
        .login-title {
            font-size: 32px;
            font-weight: 600;
            margin-bottom: 8px;
            text-align: center;
            background: linear-gradient(90deg, #58a6ff, #bc8cff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .login-subtitle {
            color: #8b949e;
            font-size: 14px;
            margin-bottom: 24px;
            text-align: center;
        }
        </style>
        <div class="login-box-anchor"></div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 4, 1])
    with col2:
        st.markdown('<div class="login-title">Argus Platform</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-subtitle">Enter password to access the research dashboard</div>', unsafe_allow_html=True)
        
        with st.form("login_form", border=False, clear_on_submit=False):
            password_input = st.text_input(
                "Password", 
                type="password", 
                placeholder="••••••••",
                label_visibility="collapsed"
            )
            
            if st.form_submit_button("Unlock Dashboard", use_container_width=True):
                if password_input == settings.app_password:
                    st.session_state["password_correct"] = True
                    _issue_auth_token()
                    st.rerun()
                else:
                    st.error("❌ Incorrect password.")

if "password_correct" not in st.session_state:
    st.session_state["password_correct"] = False

# Check cookie authentication for cross-tab session persistence
if settings.app_password:
    if _query_token_is_authenticated() or _cookie_is_authenticated():
        st.session_state["password_correct"] = True
        if "auth_token" not in st.session_state:
            st.session_state["auth_token"] = create_auth_token(_auth_secret())

pages = [
    st.Page("pages/1_Dashboard.py", title="Dashboard"),
    st.Page("pages/2_Watchlists.py", title="Watchlists"),
    st.Page("pages/3_Company_Detail.py", title="Company Detail", url_path="Company_Detail"),
    st.Page("pages/4_Pullback_Finder.py", title="Pullback Finder"),
    st.Page("pages/5_News_Filings_Alerts.py", title="News Filings Alerts"),
]

navigation = st.navigation(pages)

if settings.app_password and not st.session_state["password_correct"]:
    # Hide sidebar for unauthenticated sessions
    st.markdown(
        "<style>[data-testid='stSidebar'] { display: none; }</style>",
        unsafe_allow_html=True,
    )
    render_login_screen()
else:
    navigation.run()
