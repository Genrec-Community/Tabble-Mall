"""Telling customers about their orders outside the order page: Web Push to the installed app
(free) and WhatsApp (off until a provider is chosen). Ordering never waits on this: messages are
queued in the order's transaction and sent after commit, with retries from the sweeper."""

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.core.db import defer_after_commit
from mallt.core.phone import mask_phone
from mallt.modules.iam.users import IamCustomers
from mallt.modules.notify.models import Notification
from mallt.modules.notify.repository import NotifyRepository
from mallt.modules.notify.schemas import (
    NotifyConfigOut,
    NotifyPrefsOut,
    PushSubscriptionIn,
)
from mallt.modules.notify.webpush import Vapid, encrypt
from mallt.modules.notify.whatsapp import TEMPLATES, WhatsAppError, WhatsAppProvider
from mallt.modules.platform.service import FeatureService

log = logging.getLogger(__name__)

Kick = Callable[[], Awaitable[None]]
MAX_ATTEMPTS = 5
PUSH_TTL_S = 3600


@dataclass(frozen=True)
class Channels:
    """What the app was started with (see main.py)."""

    settings: Settings
    whatsapp: WhatsAppProvider
    http: httpx.AsyncBaseTransport | None = None

    def vapid(self) -> Vapid | None:
        s = self.settings
        if not (s.vapid_private_key and s.vapid_public_key):
            return None
        return Vapid(s.vapid_private_key, s.vapid_public_key, s.vapid_subject)


def message(kind: str, data: dict[str, Any]) -> tuple[str, str]:
    """(title, body) of a push notification. Never the pickup code."""
    store = str(data.get("store") or "Your order")
    if kind == "confirmed":
        return (
            "Order placed",
            f"{data.get('stores') or store} got your order. We'll tell you when it's ready.",
        )
    if kind == "ready":
        counter = data.get("counter")
        where = f" at {counter}" if counter else ""
        return f"{store}: ready to collect", f"Show your pickup code{where}."
    if kind == "receipt":
        return f"Collected from {store}", "Enjoy your food! Tap to rate it."
    if kind == "cancelled":
        return f"{store} could not take your order", "Your money is on its way back."
    return "MallT", store


class NotifyService:
    def __init__(
        self, session: AsyncSession, channels: Channels | None = None, kick: Kick | None = None
    ) -> None:
        self.session = session
        self.repo = NotifyRepository(session)
        self.channels = channels
        self.kick = kick
        self.features = FeatureService(session)
        self.customers = IamCustomers(session)
        self._kicked = False

    # ---- customers ----

    def config(self, pwa_on: bool, whatsapp_on: bool) -> NotifyConfigOut:
        vapid = self.channels.vapid() if self.channels else None
        return NotifyConfigOut(
            push_public_key=vapid.public_key if vapid and pwa_on else None,
            whatsapp_available=bool(
                whatsapp_on and self.channels and self.channels.whatsapp.enabled
            ),
        )

    async def public_config(self) -> NotifyConfigOut:
        flags = await self.features.all()
        return self.config(flags.get("pwa", True), flags.get("whatsapp", False))

    async def subscribe(self, customer_id: uuid.UUID, data: PushSubscriptionIn) -> None:
        await self.features.require("pwa")
        await self.repo.upsert_subscription(
            customer_id, data.endpoint, data.keys.p256dh, data.keys.auth
        )

    async def unsubscribe(self, customer_id: uuid.UUID, endpoint: str) -> None:
        await self.repo.delete_subscription(endpoint, customer_id)

    async def prefs(self, customer_id: uuid.UUID) -> NotifyPrefsOut:
        row = await self.repo.prefs(customer_id)
        return NotifyPrefsOut(
            whatsapp=bool(row and row.whatsapp),
            push_devices=len(await self.repo.subscriptions(customer_id)),
        )

    async def set_prefs(self, customer_id: uuid.UUID, whatsapp: bool) -> NotifyPrefsOut:
        await self.repo.set_prefs(customer_id, whatsapp)
        return await self.prefs(customer_id)

    # ---- for the orders module ----

    def queue(self, customer_id: uuid.UUID, kind: str, data: dict[str, Any]) -> None:
        """Queue a message about an order (inside the caller's transaction)."""
        self.repo.add(Notification(customer_id=customer_id, kind=kind, data=data))
        if self.kick is not None and not self._kicked:
            self._kicked = True
            defer_after_commit(self.session, self.kick)

    # ---- the sender ----

    async def process_next(self) -> bool:
        """Send the next due message. Returns False when nothing is due. The caller commits."""
        job = await self.repo.next_due()
        if job is None:
            return False
        job.attempts += 1
        try:
            await self._send(job)
        except _Retry as exc:
            if job.attempts < MAX_ATTEMPTS:
                job.last_error = str(exc)[:300]
                job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=30 * 2**job.attempts)
            else:
                job.status, job.last_error = "failed", str(exc)[:300]
        else:
            job.status, job.last_error = "done", None
        await self.session.flush()
        return True

    async def _send(self, job: Notification) -> None:
        if self.channels is None:
            return
        flags = await self.features.all()
        errors: list[str] = []
        if flags.get("pwa", True):
            errors += await self._push(job)
        if flags.get("whatsapp", False) and self.channels.whatsapp.enabled:
            errors += await self._whatsapp(job)
        if errors:
            raise _Retry("; ".join(errors))

    async def _push(self, job: Notification) -> list[str]:
        assert self.channels is not None  # noqa: S101
        vapid = self.channels.vapid()
        if vapid is None:
            return []
        title, body = message(job.kind, job.data)
        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "url": job.data.get("url") or "/account/orders",
                "tag": job.data.get("tag") or job.kind,
            }
        ).encode()
        errors = []
        sent: list[str] = list(job.data.get("_pushed") or [])
        for sub in await self.repo.subscriptions(job.customer_id):
            if sub.endpoint in sent:  # a retry never sends twice to the same device
                continue
            try:
                body_bytes = encrypt(payload, sub.p256dh, sub.auth)
                headers = {
                    **vapid.headers(sub.endpoint),
                    "Content-Encoding": "aes128gcm",
                    "Content-Type": "application/octet-stream",
                    "TTL": str(PUSH_TTL_S),
                    "Urgency": "high",
                }
                async with httpx.AsyncClient(timeout=10, transport=self.channels.http) as client:
                    r = await client.post(sub.endpoint, content=body_bytes, headers=headers)
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"push {type(exc).__name__}")
                continue
            if r.status_code in (404, 410):  # the browser unsubscribed: forget it
                await self.repo.delete_subscription(sub.endpoint)
            elif r.status_code >= 400:
                errors.append(f"push http {r.status_code}")
            else:
                sent.append(sub.endpoint)
        job.data = {**job.data, "_pushed": sent}
        return errors

    async def _whatsapp(self, job: Notification) -> list[str]:
        assert self.channels is not None  # noqa: S101
        if job.data.get("_whatsapp") or job.kind not in TEMPLATES:
            return []
        prefs = await self.repo.prefs(job.customer_id)
        if not prefs or not prefs.whatsapp:
            return []
        phone = await self.customers.own_phone(job.customer_id)
        if not phone:
            return []
        template, fields = TEMPLATES[job.kind]
        params = [str(job.data.get(f) or "-") for f in fields]
        try:
            await self.channels.whatsapp.send(phone, template, params)
        except WhatsAppError as exc:
            log.warning("whatsapp %s to %s failed: %s", template, mask_phone(phone), exc)
            if exc.retryable:
                return [f"whatsapp {exc}"]
            return []
        job.data = {**job.data, "_whatsapp": True}
        return []


class _Retry(Exception):
    pass


async def run_notifications(app: Any, limit: int = 25) -> int:
    done = 0
    channels: Channels = app.state.notify
    while done < limit:
        async with app.state.session_factory() as session:
            worked = await NotifyService(session, channels).process_next()
            await session.commit()
        if not worked:
            break
        done += 1
    return done


def notify_kick(app: Any) -> Kick:
    async def kick() -> None:
        try:
            await run_notifications(app)
        except Exception:  # never let a phone problem surface in a request
            log.exception("sending notifications failed")

    return kick
