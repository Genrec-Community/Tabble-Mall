"""WhatsApp messages behind one small interface. Off by default (owner, 2026-11-24): turn it on
by choosing a provider (WHATSAPP_PROVIDER) and switching the "whatsapp" feature on.

Only Meta's own WhatsApp Cloud API is wired up; WhatsApp needs pre-approved message templates,
named in TEMPLATES below, each taking the parameters listed."""

import logging
from typing import Protocol

import httpx

from mallt.core.config import Settings
from mallt.core.phone import mask_phone

log = logging.getLogger(__name__)

# kind -> (template name, what its {{1}}, {{2}}... are)
TEMPLATES: dict[str, tuple[str, tuple[str, ...]]] = {
    # The pickup code is never sent: the link opens the order page, which shows it.
    "confirmed": ("mallt_order_confirmed", ("stores", "total", "link")),
    "ready": ("mallt_order_ready", ("store", "counter", "link")),
    "receipt": ("mallt_order_receipt", ("store", "total")),
    "cancelled": ("mallt_order_cancelled", ("store", "refund")),
}


class WhatsAppError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class WhatsAppProvider(Protocol):
    name: str

    @property
    def enabled(self) -> bool: ...

    async def send(self, phone: str, template: str, params: list[str]) -> None: ...


class NoWhatsApp:
    name = "off"
    enabled = False

    async def send(self, phone: str, template: str, params: list[str]) -> None:
        return None


class LogWhatsApp:
    """Development stand-in: logs what would be sent (masked number)."""

    name = "log"
    enabled = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, list[str]]] = []

    async def send(self, phone: str, template: str, params: list[str]) -> None:
        self.sent.append((phone, template, params))
        log.info("whatsapp %s to %s: %s", template, mask_phone(phone), params)


class MetaWhatsApp:
    """WhatsApp Cloud API (graph.facebook.com). The token is a header, never in a URL or log."""

    name = "meta"
    enabled = True

    def __init__(
        self,
        token: str,
        phone_number_id: str,
        *,
        api_version: str = "v21.0",
        language: str = "en",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.token = token
        self.url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self.language = language
        self.transport = transport

    async def send(self, phone: str, template: str, params: list[str]) -> None:
        body = {
            "messaging_product": "whatsapp",
            "to": f"91{phone}" if len(phone) == 10 else phone,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": self.language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": p} for p in params],
                    }
                ],
            },
        }
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                r = await client.post(
                    self.url, json=body, headers={"Authorization": f"Bearer {self.token}"}
                )
        except httpx.HTTPError as exc:
            raise WhatsAppError(type(exc).__name__, retryable=True) from exc
        if r.status_code >= 500 or r.status_code == 429:
            raise WhatsAppError(f"http {r.status_code}", retryable=True)
        if r.status_code >= 400:
            raise WhatsAppError(f"http {r.status_code}", retryable=False)


def make_whatsapp(settings: Settings) -> WhatsAppProvider:
    if settings.whatsapp_provider == "meta":
        if not (settings.whatsapp_meta_token and settings.whatsapp_meta_phone_number_id):
            raise RuntimeError(
                "WHATSAPP_PROVIDER=meta needs WHATSAPP_META_TOKEN and WHATSAPP_META_PHONE_NUMBER_ID"
            )
        return MetaWhatsApp(
            settings.whatsapp_meta_token,
            settings.whatsapp_meta_phone_number_id,
            language=settings.whatsapp_template_language,
        )
    if settings.whatsapp_provider == "log":
        return LogWhatsApp()
    return NoWhatsApp()
