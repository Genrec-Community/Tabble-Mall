from typing import Annotated

from pydantic import BaseModel, StringConstraints

Key = Annotated[str, StringConstraints(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9_\-=]+$")]


class PushKeys(BaseModel):
    p256dh: Key
    auth: Key


class PushSubscriptionIn(BaseModel):
    """What the browser's PushManager.subscribe() returns (subscription.toJSON())."""

    endpoint: Annotated[str, StringConstraints(pattern=r"^https://", max_length=1000)]
    keys: PushKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: Annotated[str, StringConstraints(max_length=1000)]


class NotifyConfigOut(BaseModel):
    """Public: what the browser needs to offer notifications."""

    push_public_key: str | None  # VAPID application server key; None = push is off
    whatsapp_available: bool


class NotifyPrefsOut(BaseModel):
    whatsapp: bool
    push_devices: int


class NotifyPrefsUpdate(BaseModel):
    whatsapp: bool
