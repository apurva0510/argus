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


settings = Settings()
