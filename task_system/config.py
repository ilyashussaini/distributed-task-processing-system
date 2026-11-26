from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )

    app_env: Literal["development", "production"] = "development"
    api_token: SecretStr | None = None
    public_origin: str | None = None
    read_rate_per_minute: int = Field(default=0, ge=0)
    write_rate_per_minute: int = Field(default=0, ge=0)
    retention_days: int = Field(default=30, ge=1, le=3650)

    database_url: SecretStr | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "tasks"
    postgres_password: SecretStr = SecretStr("local-dev-password")
    postgres_db: str = "tasks"

    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    redis_password: SecretStr | None = None
    redis_stream: str = "task-system:jobs"
    max_attempts: int = Field(default=3, ge=1, le=20)
    attempt_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    enable_recovery_demo: bool = False
    retry_base_seconds: float = Field(default=2, gt=0, allow_inf_nan=False)
    retry_max_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    lease_seconds: float = Field(default=30, ge=1, allow_inf_nan=False)
    redispatch_seconds: float = Field(default=15, ge=1, allow_inf_nan=False)
    poll_ms: int = Field(default=500, ge=10, le=2000)
    dispatch_batch_size: int = Field(default=50, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_backoff(self) -> "Settings":
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("RETRY_MAX_SECONDS must be at least RETRY_BASE_SECONDS")
        return self

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.app_env != "production":
            return self
        token = self.api_token.get_secret_value() if self.api_token else ""
        if len(token) < 32 or not all(33 <= ord(character) <= 126 for character in token):
            raise ValueError("Production requires a printable ASCII API token of at least 32 characters")
        if self.postgres_password.get_secret_value() == "local-dev-password" or not self.postgres_password:
            raise ValueError("Production requires a configured PostgreSQL password")
        if not self.redis_password:
            raise ValueError("Production requires a configured Redis password")
        if not self.read_rate_per_minute or not self.write_rate_per_minute:
            raise ValueError("Production requires positive API read and write rate limits")
        origin = urlsplit(self.public_origin or "")
        if (origin.scheme != "https" or not origin.hostname or origin.username is not None
                or origin.path or origin.query or origin.fragment):
            raise ValueError("Production requires an HTTPS PUBLIC_ORIGIN with no path")
        return self

    @property
    def redis_connection(self) -> tuple[str, str | None]:
        password = self.redis_password.get_secret_value() if self.redis_password else None
        return self.redis_url.get_secret_value(), password

    @property
    def db_url(self) -> str | URL:
        if self.database_url:
            return self.database_url.get_secret_value()
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
