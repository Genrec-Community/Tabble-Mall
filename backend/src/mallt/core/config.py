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
    # Abuse ceilings, not fairness limits: a mall's customers share one public IP address.
    otp_send_per_ip_hourly: int = 300
    # Caps what a flood of fake numbers can cost in SMS credits.
    otp_send_global_daily: int = 20_000
    # Makes OTPs predictable for end-to-end tests. Only honoured when env == "test".
    e2e_fixed_otp: str | None = None

    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "mallt-dev"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_public_base_url: str = ""

    # Payments. "fake" pays instantly (dev/tests); "zoho" is Zoho Payments with Split.
    payments_provider: Literal["fake", "zoho"] = "fake"
    # Gateway fee each store bears on its own share of an order, in basis points (50 = 0.50%).
    gateway_fee_bps: int = 50
    zoho_account_id: str = ""
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_api_key: str = ""  # the widget's public API key (Settings > Developer Space)
    zoho_webhook_signing_key: str = ""
    zoho_sandbox: bool = True

    # The customer site, for links in notifications (no trailing slash).
    public_site_url: str = "http://localhost:8080"

    # Web Push (installable app). Generate a pair with `python -m mallt.cli vapid-keys`.
    # Empty = push notifications are off (the app still installs and works offline).
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "https://tabble-mall.vercel.app"

    # WhatsApp: "off" (default), "log" (dev: logs what it would send) or "meta" (Cloud API).
    whatsapp_provider: Literal["off", "log", "meta"] = "off"
    whatsapp_meta_token: str = ""
    whatsapp_meta_phone_number_id: str = ""
    whatsapp_template_language: str = "en"

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
        if self.sms_backend != "fast2sms":
            raise ValueError("sms_backend must be fast2sms in prod (OTPs would never be sent)")
        if self.payments_provider == "zoho":
            zoho = (
                "zoho_account_id",
                "zoho_client_id",
                "zoho_client_secret",
                "zoho_refresh_token",
                "zoho_api_key",
                "zoho_webhook_signing_key",
            )
            if missing := [name for name in zoho if not getattr(self, name)]:
                raise ValueError(f"payments_provider=zoho needs {', '.join(missing)}")
        if any("localhost" in o or "127.0.0.1" in o for o in self.cors_origins):
            raise ValueError("cors_origins must not include localhost in prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
