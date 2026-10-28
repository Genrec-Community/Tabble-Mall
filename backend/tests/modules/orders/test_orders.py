import httpx
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.orders.models import OrderEvent, Payment, StoreOrder
from mallt.modules.payments.provider import FakePaymentProvider
from tests.modules.catalog.conftest import World, product_body
from tests.modules.orders.conftest import CART, Menu, line

CHECKOUT = "/api/v1/malls/phoenix-pune/checkout"


def idem(key: str = "k1") -> dict[str, str]:
    return {"Idempotency-Key": key}


async def fill_cart(client: httpx.AsyncClient, h: dict[str, str], menu: Menu) -> None:
    await client.post(
        f"{CART}/lines", json=line(menu.burger, 1, qty=2, options=[0], note="spicy"), headers=h
    )
    await client.post(f"{CART}/lines", json=line(menu.chai), headers=h)


async def checkout(
    client: httpx.AsyncClient, h: dict[str, str], key: str = "k1", **body: object
) -> httpx.Response:
    return await client.post(CHECKOUT, json=body, headers={**h, **idem(key)})


def store_url(w: World, path: str = "", *, other: bool = False) -> str:
    return f"/api/v1/stores/{(w.other_store if other else w.store).id}/orders{path}"


# ---------- checkout ----------


async def test_checkout_splits_into_store_orders_and_pays_once(
    client: httpx.AsyncClient, alice: dict, menu: Menu, payments: FakePaymentProvider
) -> None:
    await fill_cart(client, alice, menu)
    r = await checkout(client, alice, note="please be quick")
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["status"] == "paid" and order["total_paise"] == 2 * 20000 + 3000
    stores = {s["store_slug"]: s for s in order["stores"]}
    assert set(stores) == {"burger-hub", "chai-point"}
    burger = stores["burger-hub"]
    assert burger["status"] == "paid" and burger["order_no"] == 1
    assert len(burger["pickup_code"]) == 4 and burger["pickup_code"].isdigit()
    assert (
        burger["total_paise"] == 40000
        and burger["lines"][0]["options"][0]["name"] == "Extra cheese"
    )
    assert burger["tax_paise"] == 1905  # 5% GST contained in 40,000 (rounded)
    assert payments.charges == [(43000, payments.charges[0][1])]
    # the cart was consumed
    assert (await client.get(CART, headers=alice)).json()["stores"] == []


async def test_commission_is_recorded_per_store_order(
    client: httpx.AsyncClient,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    await fill_cart(client, alice, menu)
    await checkout(client, alice)
    rows = (await db_session.execute(select(StoreOrder))).scalars().all()
    assert sorted(r.commission_paise for r in rows) == [150, 2000]  # 5% of 3,000 and 40,000
    assert all(r.commission_bps == 500 for r in rows)


async def test_checkout_is_idempotent(
    client: httpx.AsyncClient, alice: dict, menu: Menu, payments: FakePaymentProvider
) -> None:
    await fill_cart(client, alice, menu)
    first = await checkout(client, alice, "same")
    second = await checkout(client, alice, "same")
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]
    assert len(payments.charges) == 1


async def test_checkout_needs_a_key_and_a_non_empty_valid_cart(
    client: httpx.AsyncClient, alice: dict, menu: Menu
) -> None:
    assert (await client.post(CHECKOUT, json={}, headers=alice)).status_code == 400
    empty = await checkout(client, alice)
    assert empty.status_code == 400 and empty.json()["code"] == "empty_cart"


async def test_failed_payment_leaves_no_orders_and_keeps_the_cart(
    client: httpx.AsyncClient,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    await fill_cart(client, alice, menu)
    payments.fail_next = True
    r = await checkout(client, alice)
    assert r.status_code == 402 and r.json()["code"] == "payment_failed"
    assert (await db_session.execute(select(func.count()).select_from(StoreOrder))).scalar() == 0
    assert len((await client.get(CART, headers=alice)).json()["stores"]) == 2
    retry = await checkout(client, alice, "k2")
    assert retry.status_code == 201


async def test_checkout_refuses_a_cart_with_problems(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    await fill_cart(client, alice, menu)
    await client.patch(
        f"/api/v1/stores/{world.other_store.id}/products/{menu.chai['id']}/availability",
        json={"is_available": False},
        headers=world.other_store_owner,
    )
    r = await checkout(client, alice)
    assert r.status_code == 409 and r.json()["code"] == "cart_has_problems"


async def test_counted_stock_is_held_released_and_never_oversold(
    client: httpx.AsyncClient, alice: dict, bob: dict, world: World, payments: FakePaymentProvider
) -> None:
    p = (
        await client.post(
            f"/api/v1/stores/{world.store.id}/products",
            json=product_body(
                name="Samosa",
                stock_mode="counted",
                variants=[{"name": "Plate", "price_paise": 2000, "stock_count": 3}],
                option_groups=[],
            ),
            headers=world.owner,
        )
    ).json()
    two = line(p, qty=2)
    for h in (alice, bob):
        assert (await client.post(f"{CART}/lines", json=two, headers=h)).status_code == 201
    assert (await checkout(client, alice, "a")).status_code == 201
    second = await checkout(client, bob, "b")
    assert second.status_code == 409 and second.json()["code"] in {
        "out_of_stock",
        "cart_has_problems",
    }
    got = await client.get(
        f"/api/v1/stores/{world.store.id}/products/{p['id']}", headers=world.owner
    )
    assert got.json()["variants"][0]["stock_count"] == 1

    # the store rejects alice's order: her 2 units go back
    oid = (await client.get(store_url(world), headers=world.owner)).json()["items"][0]["id"]
    rej = await client.post(
        store_url(world, f"/{oid}/reject"), json={"reason": "out"}, headers=world.owner
    )
    assert rej.status_code == 200
    got = await client.get(
        f"/api/v1/stores/{world.store.id}/products/{p['id']}", headers=world.owner
    )
    assert got.json()["variants"][0]["stock_count"] == 3


async def test_order_numbers_count_up_per_store_and_codes_are_unique_among_open_orders(
    client: httpx.AsyncClient, alice: dict, bob: dict, menu: Menu
) -> None:
    for h, key in ((alice, "a"), (bob, "b")):
        await client.post(f"{CART}/lines", json=line(menu.burger), headers=h)
        assert (await checkout(client, h, key)).status_code == 201
    orders = (await client.get("/api/v1/orders", headers=alice)).json()["items"]
    assert orders[0]["stores"][0]["order_no"] == 1
    mine = (await client.get("/api/v1/orders", headers=bob)).json()["items"]
    assert mine[0]["stores"][0]["order_no"] == 2


# ---------- customer views ----------


async def test_customer_sees_own_orders_only(
    client: httpx.AsyncClient, alice: dict, bob: dict, menu: Menu
) -> None:
    await fill_cart(client, alice, menu)
    oid = (await checkout(client, alice)).json()["id"]
    got = await client.get(f"/api/v1/orders/{oid}", headers=alice)
    assert got.status_code == 200 and got.json()["stores"][0]["steps"][-1]["status"] == "paid"
    assert (await client.get(f"/api/v1/orders/{oid}", headers=bob)).status_code == 404
    assert (await client.get("/api/v1/orders", headers=bob)).json()["items"] == []
    assert (await client.get("/api/v1/orders")).status_code == 401


async def test_customer_cancels_before_accept_only(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World, payments: FakePaymentProvider
) -> None:
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    created = (await checkout(client, alice)).json()
    sid = created["stores"][0]["id"]
    cancel = await client.post(f"/api/v1/orders/stores/{sid}/cancel", headers=alice)
    assert cancel.status_code == 200 and cancel.json()["stores"][0]["status"] == "refunded"
    assert payments.refunds and payments.refunds[0][0] == 12000

    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    second = (await checkout(client, alice, "k2")).json()["stores"][0]["id"]
    await client.post(store_url(world, f"/{second}/accept"), headers=world.owner)
    late = await client.post(f"/api/v1/orders/stores/{second}/cancel", headers=alice)
    assert late.status_code == 409 and late.json()["code"] == "invalid_transition"


# ---------- store flow ----------


async def place(client: httpx.AsyncClient, h: dict, menu: Menu, key: str = "k1") -> dict:
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=h)
    return (await checkout(client, h, key)).json()["stores"][0]


async def test_full_store_flow_with_pickup_code(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World, db_session: AsyncSession
) -> None:
    order = await place(client, alice, menu)
    oid, code = order["id"], order["pickup_code"]
    listing = (await client.get(store_url(world), headers=world.staff)).json()["items"]
    assert [o["id"] for o in listing] == [oid]
    assert "pickup_code" not in listing[0]
    assert listing[0]["customer_phone"].endswith("9061") and "9361899061" not in str(listing)

    for step, status in (("accept", "accepted"), ("preparing", "preparing"), ("ready", "ready")):
        r = await client.post(store_url(world, f"/{oid}/{step}"), headers=world.staff)
        assert r.status_code == 200 and r.json()["status"] == status, r.text

    wrong = "0000" if code != "0000" else "1111"
    bad = await client.post(
        store_url(world, f"/{oid}/pickup"), json={"code": wrong}, headers=world.staff
    )
    assert bad.status_code == 400 and bad.json()["code"] == "wrong_pickup_code"
    ok = await client.post(
        store_url(world, f"/{oid}/pickup"), json={"code": code}, headers=world.staff
    )
    assert ok.status_code == 200 and ok.json()["status"] == "picked_up"

    events = (
        await db_session.execute(
            select(OrderEvent.to_status).order_by(OrderEvent.created_at, OrderEvent.id)
        )
    ).scalars()
    assert [e.value for e in events] == [
        "pending_payment",
        "paid",
        "accepted",
        "preparing",
        "ready",
        "picked_up",
    ]


async def test_pickup_code_attempts_are_rate_limited_and_order_specific(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    order = await place(client, alice, menu)
    oid, code = order["id"], order["pickup_code"]
    for step in ("accept", "preparing", "ready"):
        await client.post(store_url(world, f"/{oid}/{step}"), headers=world.owner)
    wrong = "0000" if code != "0000" else "1111"
    codes = []
    for _ in range(6):
        r = await client.post(
            store_url(world, f"/{oid}/pickup"), json={"code": wrong}, headers=world.owner
        )
        codes.append(r.status_code)
    assert codes[:5] == [400] * 5 and codes[5] == 429
    # even the right code is refused while limited
    r = await client.post(
        store_url(world, f"/{oid}/pickup"), json={"code": code}, headers=world.owner
    )
    assert r.status_code == 429


async def test_pickup_only_when_ready_and_state_machine_is_enforced(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    order = await place(client, alice, menu)
    oid, code = order["id"], order["pickup_code"]
    early = await client.post(
        store_url(world, f"/{oid}/pickup"), json={"code": code}, headers=world.owner
    )
    assert early.status_code == 409 and early.json()["code"] == "invalid_transition"
    skip = await client.post(store_url(world, f"/{oid}/ready"), headers=world.owner)
    assert skip.status_code == 409
    again = await client.post(store_url(world, f"/{oid}/accept"), headers=world.owner)
    assert again.status_code == 200
    twice = await client.post(store_url(world, f"/{oid}/accept"), headers=world.owner)
    assert twice.status_code == 409


async def test_reject_refunds_and_records_the_reason(
    client: httpx.AsyncClient,
    alice: dict,
    menu: Menu,
    world: World,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    order = await place(client, alice, menu)
    r = await client.post(
        store_url(world, f"/{order['id']}/reject"),
        json={"reason": "kitchen closed"},
        headers=world.owner,
    )
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert r.json()["reason"] == "kitchen closed"
    assert payments.refunds[0][0] == 12000
    refunds = (
        (await db_session.execute(select(Payment).where(Payment.kind == "refund"))).scalars().all()
    )
    assert len(refunds) == 1 and refunds[0].amount_paise == 12000
    assert (
        await client.post(
            store_url(world, f"/{order['id']}/reject"), json={"reason": "x"}, headers=world.owner
        )
    ).status_code == 409


async def test_store_cancel_needs_the_cancel_permission(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    order = await place(client, alice, menu)
    oid = order["id"]
    await client.post(store_url(world, f"/{oid}/accept"), headers=world.staff)
    denied = await client.post(
        store_url(world, f"/{oid}/cancel"), json={"reason": "x"}, headers=world.staff
    )
    assert denied.status_code == 403
    ok = await client.post(
        store_url(world, f"/{oid}/cancel"), json={"reason": "x"}, headers=world.owner
    )
    assert ok.status_code == 200 and ok.json()["status"] == "refunded"


async def test_unaccepted_orders_expire_and_refund(
    client: httpx.AsyncClient,
    app: FastAPI,
    alice: dict,
    menu: Menu,
    world: World,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    from mallt.modules.orders.service import OrderService

    order = await place(client, alice, menu)
    await db_session.execute(
        text("UPDATE store_orders SET accept_by = now() - interval '1 minute'")
    )
    svc = OrderService(db_session, app.state.kv, app.state.bus, payments)
    assert await svc.sweep_expired() == 1
    got = await client.get(f"/api/v1/orders/{order['id']}", headers=alice)
    assert got.status_code == 404  # store-order id is not a customer-order id
    mine = (await client.get("/api/v1/orders", headers=alice)).json()["items"]
    assert mine[0]["stores"][0]["status"] == "refunded"
    assert payments.refunds
    assert await svc.sweep_expired() == 0


# ---------- isolation ----------


async def test_stores_only_see_their_own_orders(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    await fill_cart(client, alice, menu)
    await checkout(client, alice)
    burger_orders = (await client.get(store_url(world), headers=world.owner)).json()["items"]
    chai_orders = (
        await client.get(store_url(world, other=True), headers=world.other_store_owner)
    ).json()["items"]
    assert len(burger_orders) == 1 and len(chai_orders) == 1
    assert burger_orders[0]["id"] != chai_orders[0]["id"]
    # sibling store and other organisation get 404, never the order
    foreign_id = chai_orders[0]["id"]
    for headers in (world.owner, world.outsider):
        r = await client.get(store_url(world, f"/{foreign_id}"), headers=headers)
        assert r.status_code == 404
    assert (await client.get(store_url(world), headers=world.outsider)).status_code == 404
    r = await client.post(store_url(world, f"/{foreign_id}/accept"), headers=world.owner)
    assert r.status_code == 404


async def test_org_owner_reads_orders_across_stores(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    await fill_cart(client, alice, menu)
    await checkout(client, alice)
    r = await client.get(f"/api/v1/orgs/{world.org.id}/orders", headers=world.org_owner)
    assert r.status_code == 200 and len(r.json()["items"]) == 2
    r = await client.get(f"/api/v1/malls/{world.mall.id}/orders", headers=world.org_owner)
    assert len(r.json()["items"]) == 2
    assert (
        await client.get(f"/api/v1/orgs/{world.org.id}/orders", headers=world.owner)
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/orgs/{world.org.id}/orders", headers=world.outsider)
    ).status_code == 404


async def test_history_and_active_filters(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    order = await place(client, alice, menu)
    await client.post(
        store_url(world, f"/{order['id']}/reject"), json={"reason": "x"}, headers=world.owner
    )
    await place(client, alice, menu, "k2")
    active = (await client.get(store_url(world) + "?view=active", headers=world.owner)).json()[
        "items"
    ]
    history = (await client.get(store_url(world) + "?view=history", headers=world.owner)).json()[
        "items"
    ]
    assert len(active) == 1 and len(history) == 1 and history[0]["status"] == "refunded"
