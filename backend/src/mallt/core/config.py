from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["dev", "test", "prod"] = "dev"

    database_url: str = "postgresql+asyncpg://postgres:test@localhost:5432/postgres"
    # Optional: without Redis, OTPs/rate limits fall back to Postgres and jobs run inline.
    redis_url: str | None = None

    jwt_secret: str = "dev-only-insecure-jwt-secret-change-me-0123456789"  # noqa: S105
    jwt_issuer: str = "mallt"
    access_ttl_s: int = 900
    staff_refresh_ttl_s: int = 43_200
    customer_refresh_ttl_s: int = 2_592_000
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]

    sms_backend: Literal["console", "fast2sms"] = "console"
    fast2sms_api_key: str = ""
    google_client_id: str = ""
    otp_pepper: str = "dev-only-insecure-otp-pepper-change-me-0123456789"
    # Makes OTPs predictable for end-to-end tests. Only honoured when env == "test".
    e2e_fixed_otp: str | None = None

    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "mallt-dev"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_public_base_url: str = ""

    @model_validator(mode="after")
    def _prod_must_be_safe(self) -> "Settings":
        if self.env != "prod":
            return self
        defaults = {
            name: Settings.model_fields[name].default for name in ("jwt_secret", "otp_pepper")
        }
        for name, default in defaults.items():
            value = getattr(self, name)
            if value == default or len(value) < 32:
                raise ValueError(
                    f"{name} must be a unique secret of at least 32 characters in prod"
                )
        if not self.cookie_secure:
            raise ValueError("cookie_secure must be true in prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
