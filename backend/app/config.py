from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets come from the environment only."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    youcam_api_key: str = ""
    youcam_base_url: str = "https://yce-api-01.makeupar.com"
    youcam_timeout_s: float = 30.0
    youcam_max_retries: int = 3
    youcam_retry_base_s: float = 0.8
    # Docs suggest polling every ~10s when webhooks are not used; we start
    # faster and back off so short tasks return quickly.
    youcam_poll_initial_s: float = 2.0
    youcam_poll_max_s: float = 10.0
    youcam_poll_deadline_s: float = 240.0

    cors_origins: str = "http://localhost:3000"
    max_upload_mb: int = 10
    catalog_path: str = "data/catalog.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
