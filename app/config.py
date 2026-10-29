from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven config (12-factor)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "mshauri"
    environment: str = "dev"
    # Set by CI/CD at build time (git SHA) so /health shows what is running.
    app_version: str = "dev"
    # No defaults for deployment data: code that needs it must check it is set.
    database_url: str | None = None

    clinic_timezone: str = "Africa/Nairobi"
    # Fixed at 30: the database CHECK constraints assume it. Startup fails otherwise.
    slot_minutes: int = 30
    min_lead_time_minutes: int = Field(default=60, ge=0)
    max_booking_horizon_days: int = Field(default=90, ge=1)

    # Identity provider. The issuer must equal the `iss` claim exactly (public hostname).
    keycloak_issuer: str | None = None
    keycloak_audience: str | None = None
    # Where the API fetches signing keys. Can differ from the issuer host (e.g. inside compose).
    jwks_url: str | None = None
    jwks_ttl_seconds: int = Field(default=600, ge=1)
    jwks_min_refetch_seconds: int = Field(default=30, ge=0)
    token_leeway_seconds: int = Field(default=30, ge=0)

    # Swagger UI is the reviewer's way in: Authorization Code with PKCE via a public client.
    docs_enabled: bool = True
    docs_oauth_client_id: str = "clinic-docs"

    @field_validator("clinic_timezone")
    @classmethod
    def _timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone: {value!r}") from exc
        return value

    @field_validator("slot_minutes")
    @classmethod
    def _slot_minutes_must_be_30(cls, value: int) -> int:
        if value != 30:
            raise ValueError("SLOT_MINUTES must be 30: the database CHECK constraints assume it")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
