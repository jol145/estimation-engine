from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://estimation:estimation@localhost:5432/estimation"
    sync_database_url: str = "postgresql+psycopg2://estimation:estimation@localhost:5432/estimation"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    calculation_ttl_seconds: int = 86400
    heartbeat_timeout_seconds: int = 60
    max_items_per_calculation: int = 500
    max_payload_size_bytes: int = 1_048_576
    max_concurrent_jobs: int = 4
    max_concurrent_provider_requests: int = 10
    price_provider_timeout_seconds: float = 3.0
    max_job_retries: int = 2
    api_keys: str = ""

    @property
    def api_keys_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]


settings = Settings()
