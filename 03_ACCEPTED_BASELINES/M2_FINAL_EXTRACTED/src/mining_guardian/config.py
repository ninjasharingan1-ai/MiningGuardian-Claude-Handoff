from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    srbminer_api_host: str = "127.0.0.1"
    srbminer_api_port: int = Field(default=21550, ge=1, le=65535)
    srbminer_api_path: str = "/"
    srbminer_api_timeout_seconds: float = Field(default=5.0, gt=0)
    gpu_index: int = Field(default=0, ge=0)
    observe_interval_seconds: float = Field(default=10.0, gt=0)
    freshness_fresh_max_age_seconds: float = Field(default=30.0, ge=0)
    freshness_recent_max_age_seconds: float = Field(default=120.0, ge=0)
    database_path: str = "./mining_guardian.db"
    payout_coin: str | None = None
    log_level: str = "info"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


def get_settings() -> Settings:
    return Settings()


def get_database_url(settings: Settings) -> str:
    db_path = Path(settings.database_path).expanduser().absolute()
    return f"sqlite:///{db_path.as_posix()}"
