from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven config (12-factor). Later steps add Keycloak and clinic settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "mshauri"
    environment: str = "dev"
    # Set by CI/CD at build time (git SHA) so /health shows what is running.
    app_version: str = "dev"
    # No default: a URL is deployment data. Code that needs the DB must check it is set.
    database_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
