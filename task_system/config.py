from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "tasks"
    postgres_password: str = "local-dev-password"
    postgres_db: str = "tasks"

    redis_url: str = "redis://127.0.0.1:6379/0"
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

    @property
    def db_url(self) -> str | URL:
        return self.database_url or URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
