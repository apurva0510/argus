from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_password: str = Field(default="", alias="APP_PASSWORD")
    database_url: str = Field(default=f"sqlite:///{DATA_DIR / 'app.db'}", alias="DATABASE_URL")
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
