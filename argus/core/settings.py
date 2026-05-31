from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
# Ensure data directory exists so SQLite can create the DB file during tests/CI
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_password: str = Field(default="", alias="APP_PASSWORD")
    app_auth_secret: str = Field(default="", alias="APP_AUTH_SECRET")
    database_url: str = Field(default=f"sqlite:///{DATA_DIR / 'app.db'}", alias="DATABASE_URL")
    database_password: str = Field(default="", alias="DATABASE_PASSWORD")
    sec_user_agent: str = Field(default="", alias="SEC_USER_AGENT")
    email_host: str = Field(default="", alias="EMAIL_HOST")
    email_port: int = Field(default=587, alias="EMAIL_PORT")
    email_username: str = Field(default="", alias="EMAIL_USERNAME")
    email_password: str = Field(default="", alias="EMAIL_PASSWORD")
    email_from: str = Field(default="", alias="EMAIL_FROM")
    email_to: str = Field(default="", alias="EMAIL_TO")
    news_request_delay_seconds: float = Field(default=2.0, alias="NEWS_REQUEST_DELAY_SECONDS")
    news_refresh_min_hours: float = Field(default=3.0, alias="NEWS_REFRESH_MIN_HOURS")
    finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")
    twelve_data_api_key: str = Field(default="", alias="TWELVE_DATA_API_KEY")
    alpha_vantage_api_key: str = Field(default="", alias="ALPHA_VANTAGE_API_KEY")
    market_data_provider: str = Field(default="yfinance", alias="MARKET_DATA_PROVIDER")



settings = Settings()

# Try reading from Streamlit secrets if running inside Streamlit context
try:
    import streamlit as st
    if hasattr(st, "secrets"):
        for secret_key, setting_name in (
            ("APP_PASSWORD", "app_password"),
            ("APP_AUTH_SECRET", "app_auth_secret"),
            ("DATABASE_URL", "database_url"),
            ("DATABASE_PASSWORD", "database_password"),
            ("SEC_USER_AGENT", "sec_user_agent"),
            ("EMAIL_HOST", "email_host"),
            ("EMAIL_USERNAME", "email_username"),
            ("EMAIL_PASSWORD", "email_password"),
            ("EMAIL_FROM", "email_from"),
            ("EMAIL_TO", "email_to"),
        ):
            if secret_key in st.secrets:
                setattr(settings, setting_name, st.secrets[secret_key])
except Exception:
    pass

if settings.database_password and settings.database_url:
    encoded_password = quote(settings.database_password, safe="")
    for placeholder in ("[YOUR-PASSWORD]", "<PASSWORD>", "__DB_PASSWORD__"):
        settings.database_url = settings.database_url.replace(placeholder, encoded_password)

# Normalize database URL (map postgres:// or postgresql:// to postgresql+psycopg:// for psycopg v3)
if settings.database_url:
    if settings.database_url.startswith("postgres://"):
        settings.database_url = settings.database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif settings.database_url.startswith("postgresql://"):
        settings.database_url = settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
