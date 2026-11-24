import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.modules.notify.models import Notification, PushSubscription
from mallt.modules.notify.service import Channels, NotifyService
from mallt.modules.notify.webpush import b64url, generate_keys
from mallt.modules.notify.whatsapp import LogWhatsApp, MetaWhatsApp, WhatsAppError
from mallt.modules.payments.provider import FakePaymentProvider
from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import CART, PHONE_A, Menu, line

CHECKOUT = "/api/v1/malls/phoenix-pune/checkout"
SUB = {
    "endpoint": "https://push.example/send/abc",
    # a real P-256 point is needed to encrypt; set per test
    "keys": {"p256dh": "", "auth": b64url(b"0123456789abcdef")},
}


def p256dh() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64url(raw)


def channels(settings: Settings, handler, whatsapp=None) -> Channels:  # type: ignore[no-untyped-def]
    private, public = generate_keys()
    s = settings.model_copy(update={"vapid_private_key": private, "vapid_public_key": public})
    return Channels(s, whatsapp or LogWhatsApp(), httpx.MockTransport(handler))


async def send_all(db_session: AsyncSession, ch: Channels) -> int:
    n = 0
    while await NotifyService(db_session, ch).process_next():
        n += 1
    return n


async def test_config_shows_the_push_key_only_when_configured(
    client: httpx.AsyncClient, app: FastAPI, settings: Settings
) -> None:
    off = (await client.get("/api/v1/notify/config")).json()
    assert off == {"push_public_key": None, "whatsapp_available": False}
    app.state.notify = channels(settings, lambda r: httpx.Response(201))
    on = (await client.get("/api/v1/notify/config")).json()
    assert on["push_public_key"] == app.state.notify.settings.vapid_public_key


async def test_ready_order_is_pushed_to_the_customers_devices(
    client: httpx.AsyncClient,
    app: FastAPI,
    settings: Settings,
    world: World,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(201)

    app.state.notify = channels(settings, handler)  # sent right after each commit
    sub = {**SUB, "keys": {**SUB["keys"], "p256dh": p256dh()}}
    assert (await client.post("/api/v1/notify/push", json=sub, headers=alice)).status_code == 204
    prefs = (await client.get("/api/v1/notify/prefs", headers=alice)).json()
    assert prefs == {"whatsapp": False, "push_devices": 1}

    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    order = (await client.post(CHECKOUT, json={}, headers={**alice, "Idempotency-Key": "n"})).json()
    so = order["stores"][0]
    base = f"/api/v1/stores/{world.store.id}/orders/{so['id']}"
    for step in ("accept", "preparing", "ready"):
        await client.post(f"{base}/{step}", headers=world.owner)
    rows = list((await db_session.execute(select(Notification))).scalars())
    assert [(n.kind, n.status) for n in rows] == [("confirmed", "done"), ("ready", "done")]
    assert len(sent) == 2 and sent[0].headers["content-encoding"] == "aes128gcm"
    assert sent[0].headers["authorization"].startswith("vapid t=")
    # nothing goes twice
    assert await send_all(db_session, app.state.notify) == 0
    # the pickup code is never in what we queue
    data = [n.data for n in (await db_session.execute(select(Notification))).scalars()]
    assert so["pickup_code"] not in str(data)


async def test_a_gone_subscription_is_forgotten(
    client: httpx.AsyncClient, settings: Settings, alice: dict, db_session: AsyncSession
) -> None:
    ch = channels(settings, lambda r: httpx.Response(410))
    sub = {**SUB, "keys": {**SUB["keys"], "p256dh": p256dh()}}
    await client.post("/api/v1/notify/push", json=sub, headers=alice)
    me = await db_session.scalar(select(PushSubscription.customer_id))
    assert me is not None
    NotifyService(db_session).queue(me, "ready", {"store": "Burger Hub"})
    await send_all(db_session, ch)
    assert await db_session.scalar(select(PushSubscription.id)) is None


async def test_whatsapp_goes_only_when_switched_on_and_the_customer_agreed(
    client: httpx.AsyncClient, settings: Settings, alice: dict, db_session: AsyncSession
) -> None:
    wa = LogWhatsApp()
    ch = channels(settings, lambda r: httpx.Response(201), whatsapp=wa)
    await client.get("/api/v1/notify/prefs", headers=alice)
    me = (await client.get("/api/v1/auth/customer/me", headers=alice)).json()["id"]
    NotifyService(db_session).queue(me, "ready", {"store": "Burger Hub", "link": "https://x/o"})
    await send_all(db_session, ch)
    assert wa.sent == []  # whatsapp feature is off by default
    await db_session.execute(
        text(
            "INSERT INTO platform_features (key, enabled, updated_at) VALUES ('whatsapp', true, now())"
        )
    )
    NotifyService(db_session).queue(me, "ready", {"store": "Burger Hub", "link": "https://x/o"})
    await send_all(db_session, ch)
    assert wa.sent == []  # the customer has not opted in
    r = await client.put("/api/v1/notify/prefs", json={"whatsapp": True}, headers=alice)
    assert r.json()["whatsapp"] is True
    NotifyService(db_session).queue(me, "ready", {"store": "Burger Hub", "link": "https://x/o"})
    await send_all(db_session, ch)
    assert wa.sent == [(PHONE_A, "mallt_order_ready", ["Burger Hub", "-", "https://x/o"])]


async def test_meta_whatsapp_sends_a_template_with_the_token_in_a_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid"}]})

    meta = MetaWhatsApp("tok", "123", transport=httpx.MockTransport(handler))
    await meta.send("9876543210", "mallt_order_ready", ["Burger Hub"])
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert b'"to":"919876543210"' in seen[0].content and "tok" not in str(seen[0].url)

    bad = MetaWhatsApp("tok", "1", transport=httpx.MockTransport(lambda r: httpx.Response(400)))
    try:
        await bad.send("9876543210", "x", [])
    except WhatsAppError as exc:
        assert not exc.retryable
    else:
        raise AssertionError("expected an error")
