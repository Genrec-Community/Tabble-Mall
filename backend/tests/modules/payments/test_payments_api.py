"""Split payments end to end over HTTP: pay-then-confirm checkout, transfers, refunds with
reversal, payout accounts, the webhook and the admin overview."""

import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.rbac import Scope
from mallt.modules.payments.enums import TaskStatus
from mallt.modules.payments.models import LedgerEntry, PaymentTask, PayoutAccount
from mallt.modules.payments.provider import FakePaymentProvider, PaymentState
from tests.factories import make_staff
from tests.helpers import staff_headers
from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import CART, Menu, line

CHECKOUT = "/api/v1/malls/phoenix-pune/checkout"
ACCOUNT = {
    "account_name": "Burger Hub LLP",
    "email": "owner@burgerhub.in",
    "pan": "abcde1234f",
    "business_description": "Burgers and shakes at Phoenix Pune",
    "ifsc": "hdfc0001234",
    "account_number": "50100012345678",
}


@pytest.fixture
def gateway(payments: FakePaymentProvider) -> FakePaymentProvider:
    """The fake behaving like Zoho: pay in the browser, stores need payout accounts."""
    payments.instant = False
    payments.requires_payout_accounts = True
    return payments


def payout_url(world: World, *, other: bool = False) -> str:
    return f"/api/v1/stores/{(world.other_store if other else world.store).id}/payout-account"


async def onboard(client: httpx.AsyncClient, world: World) -> None:
    for other, h in ((False, world.owner), (True, world.other_store_owner)):
        r = await client.put(payout_url(world, other=other), json=ACCOUNT, headers=h)
        assert r.status_code == 200, r.text


async def start_checkout(client: httpx.AsyncClient, h: dict, menu: Menu, key: str = "k1") -> dict:
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=h)
    await client.post(f"{CART}/lines", json=line(menu.chai, qty=2), headers=h)
    r = await client.post(CHECKOUT, json={}, headers={**h, "Idempotency-Key": key})
    assert r.status_code == 201, r.text
    return r.json()


def session_of(gateway: FakePaymentProvider) -> str:
    return next(iter(gateway._sessions))


# ---------- payout accounts ----------


async def test_payout_account_is_masked_and_permissioned(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession, gateway: FakePaymentProvider
) -> None:
    missing = await client.get(payout_url(world), headers=world.owner)
    assert missing.status_code == 404 and missing.json()["code"] == "no_payout_account"
    r = await client.put(payout_url(world), json=ACCOUNT, headers=world.owner)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "active" and out["pan_masked"] == "••••234F"
    assert out["bank_masked"] == "••••5678" and out["ifsc"] == "HDFC0001234"
    row = (await db_session.execute(select(PayoutAccount))).scalar_one()
    stored = json.dumps({c.name: str(getattr(row, c.name)) for c in PayoutAccount.__table__.c})
    assert "50100012345678" not in stored and "ABCDE1234F" not in stored
    # active accounts cannot be swapped by the store
    again = await client.put(payout_url(world), json=ACCOUNT, headers=world.owner)
    assert again.status_code == 409
    assert (
        await client.post(f"{payout_url(world)}/refresh", headers=world.owner)
    ).status_code == 200
    # store staff and org managers cannot see bank details; org owners can
    assert (await client.get(payout_url(world), headers=world.staff)).status_code == 403
    assert (await client.get(payout_url(world), headers=world.org_owner)).status_code == 200


async def test_payout_account_is_invisible_across_tenants(
    client: httpx.AsyncClient, world: World
) -> None:
    r = await client.put(payout_url(world), json=ACCOUNT, headers=world.outsider)
    assert r.status_code == 404
    assert (await client.get(payout_url(world), headers=world.outsider)).status_code == 404
    # a store owner in the same mall still cannot touch another store's account
    assert (await client.get(payout_url(world), headers=world.other_store_owner)).status_code in (
        403,
        404,
    )


async def test_payout_account_validates_bank_details(
    client: httpx.AsyncClient, world: World
) -> None:
    bad = await client.put(payout_url(world), json={**ACCOUNT, "pan": "123"}, headers=world.owner)
    assert bad.status_code == 422
    bad = await client.put(
        payout_url(world), json={**ACCOUNT, "ifsc": "HDFC1"}, headers=world.owner
    )
    assert bad.status_code == 422


# ---------- checkout ----------


async def test_stores_without_payout_accounts_cannot_take_orders(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World, gateway: FakePaymentProvider
) -> None:
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    r = await client.post(CHECKOUT, json={}, headers={**alice, "Idempotency-Key": "k"})
    assert r.status_code == 409 and r.json()["code"] == "store_not_payable"
    assert r.json()["store_ids"] == [str(world.store.id)]


async def test_pay_then_confirm_splits_to_each_store(
    client: httpx.AsyncClient,
    alice: dict,
    bob: dict,
    menu: Menu,
    world: World,
    gateway: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    await onboard(client, world)
    order = await start_checkout(client, alice, menu)
    assert order["status"] == "placed" and order["total_paise"] == 12000 + 2 * 3000
    assert order["payment"]["provider"] == "fake" and order["payment"]["pay_by"]
    assert all(s["status"] == "pending_payment" and s["pickup_code"] == "" for s in order["stores"])
    # stores do not see unpaid orders, and the cart is kept until payment
    listing = await client.get(f"/api/v1/stores/{world.store.id}/orders", headers=world.owner)
    assert listing.json()["items"] == []
    assert len((await client.get(CART, headers=alice)).json()["stores"]) == 2

    paid = gateway.pay(session_of(gateway))
    url = f"/api/v1/orders/{order['id']}/payment"
    assert (
        await client.post(url, json={"payment_id": paid.payment_ref}, headers=bob)
    ).status_code == 404
    r = await client.post(url, json={"payment_id": paid.payment_ref}, headers=alice)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "paid" and done["payment"] is None
    assert all(s["status"] == "paid" and len(s["pickup_code"]) == 4 for s in done["stores"])
    assert (await client.get(CART, headers=alice)).json()["stores"] == []
    # each store got its whole share minus its own 0.5% gateway fee, straight away
    assert sorted(t[0] for t in gateway.transfers) == [5970, 11940]
    accounts = {
        a.store_id: a.account_ref
        for a in (await db_session.execute(select(PayoutAccount))).scalars()
    }
    assert {t[1] for t in gateway.transfers} == set(accounts.values())
    # confirming again is harmless
    again = await client.post(url, json={"payment_id": paid.payment_ref}, headers=alice)
    assert again.status_code == 200 and len(gateway.transfers) == 2
    kinds = [
        k
        for (k,) in (
            await db_session.execute(select(LedgerEntry.kind).order_by(LedgerEntry.id))
        ).all()
    ]
    assert (
        kinds.count("charge") == 1
        and kinds.count("gateway_fee") == 2
        and "commission" not in kinds  # MallT takes nothing
        and kinds.count("transfer") == 2
    )


async def test_confirm_rejects_someone_elses_payment(
    client: httpx.AsyncClient,
    alice: dict,
    bob: dict,
    menu: Menu,
    world: World,
    gateway: FakePaymentProvider,
) -> None:
    await onboard(client, world)
    mine = await start_checkout(client, alice, menu)
    await start_checkout(client, bob, menu)
    bobs_session = [s for s, (_, ref) in gateway._sessions.items() if ref != mine["id"]][0]
    bobs_payment = gateway.pay(bobs_session)
    r = await client.post(
        f"/api/v1/orders/{mine['id']}/payment",
        json={"payment_id": bobs_payment.payment_ref},
        headers=alice,
    )
    assert r.status_code == 400 and r.json()["code"] == "payment_mismatch"
    failed = gateway.pay(session_of(gateway), state=PaymentState.FAILED)
    r = await client.post(
        f"/api/v1/orders/{mine['id']}/payment",
        json={"payment_id": failed.payment_ref},
        headers=alice,
    )
    assert r.status_code == 402


async def test_reject_after_split_reverses_then_refunds_only_that_store(
    client: httpx.AsyncClient,
    alice: dict,
    menu: Menu,
    world: World,
    gateway: FakePaymentProvider,
) -> None:
    await onboard(client, world)
    order = await start_checkout(client, alice, menu)
    paid = gateway.pay(session_of(gateway))
    await client.post(
        f"/api/v1/orders/{order['id']}/payment",
        json={"payment_id": paid.payment_ref},
        headers=alice,
    )
    burger = next(s for s in order["stores"] if s["store_slug"] == "burger-hub")
    r = await client.post(
        f"/api/v1/stores/{world.store.id}/orders/{burger['id']}/reject",
        json={"reason": "out of buns"},
        headers=world.owner,
    )
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert gateway.reversals == [(11940, gateway.reversals[0][1])]
    assert gateway.refunds == [(12000, f"so:{burger['id']}")]
    assert len(gateway.transfers) == 2  # the chai store keeps its share


async def test_fee_on_a_refunded_order_is_held_from_the_stores_next_payout(
    client: httpx.AsyncClient,
    alice: dict,
    menu: Menu,
    world: World,
    gateway: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    await onboard(client, world)
    first = await start_checkout(client, alice, menu)
    paid = gateway.pay(session_of(gateway))
    await client.post(
        f"/api/v1/orders/{first['id']}/payment",
        json={"payment_id": paid.payment_ref},
        headers=alice,
    )
    burger = next(s for s in first["stores"] if s["store_slug"] == "burger-hub")
    await client.post(
        f"/api/v1/stores/{world.store.id}/orders/{burger['id']}/reject",
        json={"reason": "closed"},
        headers=world.owner,
    )
    assert gateway.refunds == [(12000, f"so:{burger['id']}")]  # the customer gets it all back
    # next order: the burger store's 60 paise fee from the refunded order is held back
    gateway.transfers.clear()
    second = await start_checkout(client, alice, menu, key="k2")
    session = [s for s, (_, ref) in gateway._sessions.items() if ref == second["id"]][0]
    paid = gateway.pay(session)
    await client.post(
        f"/api/v1/orders/{second['id']}/payment",
        json={"payment_id": paid.payment_ref},
        headers=alice,
    )
    assert sorted(t[0] for t in gateway.transfers) == [5970, 11940 - 60]
    owed = (
        (
            await db_session.execute(
                select(LedgerEntry.amount_paise).where(
                    LedgerEntry.kind == "fee_owed", LedgerEntry.store_id == world.store.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(owed) == [-60, 60] and sum(owed) == 0


async def test_flaky_provider_is_retried_without_paying_twice(
    client: httpx.AsyncClient,
    app: FastAPI,
    alice: dict,
    menu: Menu,
    world: World,
    gateway: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    from mallt.modules.payments.runner import run_money_tasks

    await onboard(client, world)
    order = await start_checkout(client, alice, menu)
    paid = gateway.pay(session_of(gateway))
    gateway.flaky_next = True  # the first transfer times out
    await client.post(
        f"/api/v1/orders/{order['id']}/payment",
        json={"payment_id": paid.payment_ref},
        headers=alice,
    )
    tasks = (await db_session.execute(select(PaymentTask).order_by(PaymentTask.id))).scalars().all()
    assert [t.status for t in tasks] == [TaskStatus.PENDING, TaskStatus.PENDING]
    assert tasks[0].attempts == 1 and tasks[0].last_error == "timeout"
    assert len(gateway.transfers) == 0  # tasks of one order run in order: the second waits
    await db_session.execute(text("UPDATE payment_tasks SET next_attempt_at = now()"))
    assert await run_money_tasks(app) == 2
    db_session.expire_all()
    tasks = (await db_session.execute(select(PaymentTask).order_by(PaymentTask.id))).scalars().all()
    assert all(t.status is TaskStatus.DONE for t in tasks)
    assert len(gateway.transfers) == 2


async def test_unpaid_orders_are_given_up_and_late_payments_refunded(
    client: httpx.AsyncClient,
    app: FastAPI,
    alice: dict,
    menu: Menu,
    world: World,
    gateway: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    from mallt.modules.orders.service import OrderService
    from mallt.modules.payments.runner import run_money_tasks

    await onboard(client, world)
    order = await start_checkout(client, alice, menu)
    await db_session.execute(
        text("UPDATE customer_orders SET pay_by = now() - interval '1 minute'")
    )
    svc = OrderService(db_session, app.state.kv, app.state.bus, gateway)
    assert await svc.sweep_unpaid() == 1
    got = (await client.get(f"/api/v1/orders/{order['id']}", headers=alice)).json()
    assert got["status"] == "payment_failed" and got["payment"] is None
    assert {s["status"] for s in got["stores"]} == {"payment_failed"}
    # the customer's money arrives anyway: it is returned, never kept
    paid = gateway.pay(session_of(gateway))
    await svc.on_provider_payment(paid)
    await run_money_tasks(app)
    assert sorted(r[0] for r in gateway.refunds) == [6000, 12000]
    assert gateway.transfers == []


async def test_sweeper_settles_an_order_paid_without_a_confirm(
    client: httpx.AsyncClient,
    app: FastAPI,
    alice: dict,
    menu: Menu,
    world: World,
    gateway: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    from mallt.modules.orders.service import OrderService

    await onboard(client, world)
    order = await start_checkout(client, alice, menu)
    gateway.pay(session_of(gateway))  # the browser closed before confirming
    await db_session.execute(
        text("UPDATE customer_orders SET pay_by = now() - interval '1 minute'")
    )
    svc = OrderService(db_session, app.state.kv, app.state.bus, gateway)
    await svc.sweep_unpaid()
    got = (await client.get(f"/api/v1/orders/{order['id']}", headers=alice)).json()
    assert got["status"] == "paid"


# ---------- webhook ----------


def signed(body: bytes, key: str = "whsec") -> dict[str, str]:
    stamp = str(int(time.time()))
    v = hmac.new(key.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Zoho-Webhook-Signature": f"t={stamp},v={v}", "Content-Type": "application/json"}


@pytest.fixture
def zoho_app(app: FastAPI, settings: object) -> FastAPI:
    import httpx as _httpx

    from mallt.modules.payments.zoho import ZohoPaymentProvider

    app.state.settings = app.state.settings.model_copy(update={"zoho_webhook_signing_key": "whsec"})
    app.state.payments = ZohoPaymentProvider(
        account_id="1",
        client_id="c",
        client_secret="s",
        refresh_token="r",
        api_key="k",
        kv=app.state.kv,
        http=_httpx.AsyncClient(
            transport=_httpx.MockTransport(lambda _: _httpx.Response(500, json={}))
        ),
    )
    return app


WEBHOOK = "/api/v1/payments/zoho/webhook"


async def test_webhook_needs_zoho_and_a_valid_signature(
    client: httpx.AsyncClient, zoho_app: FastAPI
) -> None:
    body = json.dumps({"event_id": "e1", "event_type": "payment.failed"}).encode()
    assert (await client.post(WEBHOOK, content=body)).status_code == 401
    assert (
        await client.post(WEBHOOK, content=body, headers=signed(body, "nope"))
    ).status_code == 401
    ok = await client.post(WEBHOOK, content=body, headers=signed(body))
    assert ok.status_code == 200 and ok.json() == {"ok": True}


async def test_webhook_is_off_for_the_fake_provider(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    body = b"{}"
    assert (await client.post(WEBHOOK, content=body, headers=signed(body))).status_code == 404


async def test_webhook_settles_a_payment_once(
    client: httpx.AsyncClient,
    zoho_app: FastAPI,
    alice: dict,
    menu: Menu,
    world: World,
    db_session: AsyncSession,
) -> None:
    from mallt.modules.orders.models import CustomerOrder, StoreOrder
    from mallt.modules.payments.enums import PayoutStatus

    for store in (world.store, world.other_store):
        db_session.add(
            PayoutAccount(
                organization_id=store.organization_id,
                mall_id=store.mall_id,
                store_id=store.id,
                provider="zoho",
                account_ref=f"ca_{store.slug}",
                account_name="x",
                email="x@y.in",
                pan_last4="234F",
                bank_last4="5678",
                ifsc="HDFC0001234",
                mcc="5814",
                status=PayoutStatus.ACTIVE,
            )
        )
    await db_session.flush()
    # Zoho's API is "down" in this app, so place the order directly as checkout would have.
    zoho_app.state.payments.start = _fake_start  # type: ignore[method-assign]
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    r = await client.post(CHECKOUT, json={}, headers={**alice, "Idempotency-Key": "w"})
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    assert r.json()["payment"]["zoho"]["payments_session_id"] == "sess-1"
    event = {
        "event_id": "evt-1",
        "event_type": "payment.succeeded",
        "event_object": {
            "payment": {
                "payment_id": "4242",
                "payments_session_id": "sess-1",
                "reference_number": oid,
                "amount": "120.00",
                "status": "succeeded",
            }
        },
    }
    body = json.dumps(event).encode()
    for _ in range(2):  # delivered twice
        assert (await client.post(WEBHOOK, content=body, headers=signed(body))).status_code == 200
    order = (
        await db_session.execute(select(CustomerOrder).where(CustomerOrder.id == oid))
    ).scalar_one()
    await db_session.refresh(order)
    assert order.status == "paid" and order.payment_ref == "4242"
    statuses = (await db_session.execute(select(StoreOrder.status))).scalars().all()
    assert statuses == ["paid"]
    charges = (
        (await db_session.execute(select(LedgerEntry).where(LedgerEntry.kind == "charge")))
        .scalars()
        .all()
    )
    assert len(charges) == 1
    # the transfer to the store was attempted (Zoho is down here) and is waiting to retry
    task = (await db_session.execute(select(PaymentTask))).scalar_one()
    await db_session.refresh(task)
    assert task.status is TaskStatus.PENDING and task.account_ref == "ca_burger-hub"
    assert task.amount_paise == 11940


async def _fake_start(*, amount_paise: int, reference: str, description: str):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime, timedelta

    from mallt.modules.payments.provider import StartResult

    return StartResult(
        True, session_ref="sess-1", expires_at=datetime.now(UTC) + timedelta(minutes=15)
    )


# ---------- admin ----------


async def test_admin_overview_is_platform_only(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    import pyotp

    secret = pyotp.random_base32()
    await make_staff(db_session, "root", [("platform_admin", Scope.platform())], totp_secret=secret)
    root = await staff_headers(client, "root", totp_secret=secret)
    await client.put(payout_url(world), json=ACCOUNT, headers=world.owner)
    r = await client.get("/api/v1/admin/payments", headers=root)
    assert r.status_code == 200 and len(r.json()["accounts"]) == 1
    assert (await client.get("/api/v1/admin/payments", headers=world.org_owner)).status_code == 403
