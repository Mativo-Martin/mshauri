from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven config (12-factor). Later steps add DB, Keycloak, clinic TZ."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "mshauri"
    environment: str = "dev"
    # Set by CI/CD at build time (git SHA) so /health shows what is running.
    app_version: str = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
