"""Sending one-time passwords by SMS."""

import logging
from typing import Protocol

import httpx

from mallt.core.config import Settings
from mallt.core.errors import AppError
from mallt.core.phone import mask_phone

log = logging.getLogger(__name__)

FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"


class SmsSender(Protocol):
    async def send_otp(self, phone: str, otp: str) -> None: ...


class ConsoleSms:
    """Development stand-in: logs the OTP instead of sending it (never outside dev)."""

    def __init__(self, settings: Settings) -> None:
        self.show_otp = settings.env == "dev"

    async def send_otp(self, phone: str, otp: str) -> None:
        if self.show_otp:
            log.warning("DEV OTP for %s is %s", mask_phone(phone), otp)


class Fast2Sms:
    """Fast2SMS ``otp`` route. The API key goes in a header so it never shows up in URLs/logs."""

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = api_key
        self.transport = transport

    async def send_otp(self, phone: str, otp: str) -> None:
        params = {"route": "otp", "variables_values": otp, "numbers": phone}
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                response = await client.get(
                    FAST2SMS_URL, params=params, headers={"authorization": self.api_key}
                )
            ok = response.status_code == 200 and response.json().get("return") is True
        except (httpx.HTTPError, ValueError) as exc:
            log.error("fast2sms request failed for %s: %s", mask_phone(phone), type(exc).__name__)
            raise AppError("sms_failed", "Could not send the code. Try again.", status=502) from exc
        if not ok:
            log.error("fast2sms rejected the request for %s", mask_phone(phone))
            raise AppError("sms_failed", "Could not send the code. Try again.", status=502)


def make_sms_sender(settings: Settings) -> SmsSender:
    if settings.sms_backend == "fast2sms":
        if not settings.fast2sms_api_key:
            raise RuntimeError("SMS_BACKEND=fast2sms needs FAST2SMS_API_KEY")
        return Fast2Sms(settings.fast2sms_api_key)
    return ConsoleSms(settings)
