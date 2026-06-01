import sys
from pathlib import Path

# Add project root to sys.path to allow absolute imports of 'app' and 'argus'
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import streamlit as st  # noqa: E402
from argus.core.auth import AUTH_COOKIE_NAME, create_auth_token, validate_auth_token  # noqa: E402
from argus.core.settings import settings  # noqa: E402

st.set_page_config(page_title="Argus", page_icon="📊", layout="wide")


def _auth_secret() -> str:
    return settings.app_auth_secret or settings.app_password


def _set_auth_cookie() -> None:
    token = create_auth_token(_auth_secret())
    script = f"""
    <script>
    let cookie = "{AUTH_COOKIE_NAME}={token}; path=/; max-age=86400; SameSite=Lax";
    if (window.location.protocol === "https:") {{
        cookie += "; Secure";
    }}
    document.cookie = cookie;
    </script>
    """
    st.html(script, unsafe_allow_javascript=True)


def _cookie_is_authenticated() -> bool:
    token = st.context.cookies.get(AUTH_COOKIE_NAME)
    return validate_auth_token(token, _auth_secret())

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
        
        password_input = st.text_input(
            "Password", 
            type="password", 
            placeholder="••••••••",
            label_visibility="collapsed"
        )
        
        if st.button("Unlock Dashboard", use_container_width=True):
            if password_input == settings.app_password:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("❌ Incorrect password.")

if "password_correct" not in st.session_state:
    st.session_state["password_correct"] = False

# Check cookie authentication for cross-tab session persistence
if settings.app_password:
    if _cookie_is_authenticated():
        st.session_state["password_correct"] = True

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

    # Set client-side cookie to authorize subsequent tabs/windows
    if settings.app_password:
        _set_auth_cookie()
