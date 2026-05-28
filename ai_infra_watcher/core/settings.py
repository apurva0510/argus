from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_password: str = Field(default="change-me", alias="APP_PASSWORD")
    database_url: str = Field(default=f"sqlite:///{DATA_DIR / 'app.db'}", alias="DATABASE_URL")
    sec_user_agent: str = Field(
        default="AIInfraWatcher/0.1 (user@example.com)",
        alias="SEC_USER_AGENT",
    )


settings = Settings()
