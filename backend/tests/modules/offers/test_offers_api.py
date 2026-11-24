import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.orders.models import StoreOrder
from mallt.modules.payments.provider import FakePaymentProvider
from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import CART, Menu, line

CHECKOUT = "/api/v1/malls/phoenix-pune/checkout"
PUBLIC = "/api/v1/public/malls/phoenix-pune/offers"


def offers_url(w: World, *, other: bool = False) -> str:
    return f"/api/v1/stores/{(w.other_store if other else w.store).id}/offers"


def pct(title: str = "10% off", **over: object) -> dict[str, object]:
    return {"title": title, "kind": "percent", "value": 1000, **over}


async def fill(client: httpx.AsyncClient, h: dict, menu: Menu) -> None:
    await client.post(f"{CART}/lines", json=line(menu.burger, 1, qty=2), headers=h)  # 36,000
    await client.post(f"{CART}/lines", json=line(menu.chai), headers=h)  # 3,000


# ---------- store offers: permissions and isolation ----------


async def test_store_owner_creates_lists_toggles_and_deletes_offers(
    client: httpx.AsyncClient, world: World
) -> None:
    r = await client.post(offers_url(world), json=pct(code="burger10"), headers=world.owner)
    assert r.status_code == 201, r.text
    offer = r.json()
    assert offer["code"] == "BURGER10" and offer["is_active"]
    listed = await client.get(offers_url(world), headers=world.staff)  # staff may read
    assert [o["id"] for o in listed.json()] == [offer["id"]]
    off = await client.patch(
        f"{offers_url(world)}/{offer['id']}/active", json={"is_active": False}, headers=world.owner
    )
    assert off.json()["is_active"] is False
    gone = await client.delete(f"{offers_url(world)}/{offer['id']}", headers=world.owner)
    assert gone.status_code == 204
    assert (await client.get(offers_url(world), headers=world.owner)).json() == []


async def test_store_staff_cannot_create_offers(client: httpx.AsyncClient, world: World) -> None:
    r = await client.post(offers_url(world), json=pct(), headers=world.staff)
    assert r.status_code == 403


async def test_offers_of_another_tenant_are_404(client: httpx.AsyncClient, world: World) -> None:
    created = (await client.post(offers_url(world), json=pct(), headers=world.owner)).json()
    for h in (world.outsider, world.other_store_owner):
        assert (await client.get(offers_url(world), headers=h)).status_code == 404
        r = await client.patch(
            f"{offers_url(world)}/{created['id']}/active", json={"is_active": False}, headers=h
        )
        assert r.status_code == 404
    # an offer id from one store used under another store's url is not found either
    r = await client.delete(
        f"{offers_url(world, other=True)}/{created['id']}", headers=world.other_store_owner
    )
    assert r.status_code == 404


async def test_offer_validation(client: httpx.AsyncClient, world: World) -> None:
    bad = [
        pct(value=20_000),
        pct(code="no spaces"),
        pct(starts_at="2026-12-02T00:00:00Z", ends_at="2026-12-01T00:00:00Z"),
        {"title": "x", "kind": "free", "value": 1},
    ]
    for body in bad:
        assert (
            await client.post(offers_url(world), json=body, headers=world.owner)
        ).status_code == 422
    await client.post(offers_url(world), json=pct(code="SAME"), headers=world.owner)
    dup = await client.post(offers_url(world), json=pct(code="same"), headers=world.owner)
    assert dup.status_code == 409


async def test_offer_changes_are_audited(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    await client.post(offers_url(world), json=pct(), headers=world.owner)
    n = await db_session.scalar(
        text("SELECT count(*) FROM audit_logs WHERE action = 'offer.create'")
    )
    assert n == 1


# ---------- the cart and checkout ----------


async def test_automatic_offer_shows_in_cart_and_comes_off_the_store_share(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    await client.post(offers_url(world), json=pct(max_discount_paise=2500), headers=world.owner)
    await fill(client, alice, menu)
    cart = (await client.get(CART, headers=alice)).json()
    burger = next(s for s in cart["stores"] if s["store_slug"] == "burger-hub")
    assert burger["discount_paise"] == 2500 and burger["total_paise"] == 33500
    assert burger["discounts"] == [{"kind": "offer", "name": "10% off", "amount_paise": 2500}]
    assert cart["items_total_paise"] == 39000 and cart["total_paise"] == 36500

    r = await client.post(CHECKOUT, json={}, headers={**alice, "Idempotency-Key": "o1"})
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["total_paise"] == 36500 and order["discount_paise"] == 2500
    assert payments.charges[0][0] == 36500
    so = next(s for s in order["stores"] if s["store_slug"] == "burger-hub")
    assert so["subtotal_paise"] == 36000 and so["total_paise"] == 33500
    rows = {r.store_id: r for r in (await db_session.execute(select(StoreOrder))).scalars()}
    burger_row = rows[world.store.id]
    # the store pays the 0.5% fee on what it actually gets: 33,500 → 168 (rounded half up)
    assert burger_row.gateway_fee_paise == 168
    assert burger_row.tax_paise == 1595  # 5% GST inside 33,500
    assert rows[world.other_store.id].discount_paise == 0


async def test_coupon_applies_only_with_its_code_and_once_per_customer(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
) -> None:
    await client.post(
        offers_url(world, other=True),
        json={
            "title": "₹10 off chai",
            "kind": "flat",
            "value": 1000,
            "code": "CHAI10",
            "per_customer_limit": 1,
        },
        headers=world.other_store_owner,
    )
    await fill(client, alice, menu)
    assert (await client.get(CART, headers=alice)).json()["discount_paise"] == 0
    bad = (await client.put(f"{CART}/coupon", json={"code": "WRONG"}, headers=alice)).json()
    assert bad["coupon"]["status"] == "invalid" and bad["discount_paise"] == 0
    good = (await client.put(f"{CART}/coupon", json={"code": "chai10"}, headers=alice)).json()
    assert good["coupon"] == {"code": "CHAI10", "status": "applied", "message": None}
    assert good["discount_paise"] == 1000
    r = await client.post(CHECKOUT, json={}, headers={**alice, "Idempotency-Key": "c1"})
    assert r.json()["discount_paise"] == 1000
    # the coupon is used up for alice; the next cart does not carry it either
    await fill(client, alice, menu)
    again = (await client.put(f"{CART}/coupon", json={"code": "CHAI10"}, headers=alice)).json()
    assert again["coupon"]["status"] == "not_eligible" and again["discount_paise"] == 0
    removed = (await client.delete(f"{CART}/coupon", headers=alice)).json()
    assert removed["coupon"] is None


async def test_mall_combo_is_split_between_its_stores(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
) -> None:
    combos = f"/api/v1/malls/{world.mall.id}/combos"
    body = {
        "name": "Burger + Chai",
        "price_paise": 12000,
        "items": [{"product_id": menu.burger["id"]}, {"product_id": menu.chai["id"]}],
    }
    assert (await client.post(combos, json=body, headers=world.owner)).status_code == 403
    assert (await client.post(combos, json=body, headers=world.outsider)).status_code == 404
    r = await client.post(combos, json=body, headers=world.org_owner)
    assert r.status_code == 201, r.text
    combo = r.json()
    assert combo["regular_price_paise"] == 15000 and len(combo["items"]) == 2
    too_dear = {**body, "price_paise": 15000}
    assert (await client.post(combos, json=too_dear, headers=world.org_owner)).status_code == 400

    public = (await client.get(PUBLIC)).json()
    assert [c["name"] for c in public["combos"]] == ["Burger + Chai"]

    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)  # 12,000
    await client.post(f"{CART}/lines", json=line(menu.chai), headers=alice)  # 3,000
    cart = (await client.get(CART, headers=alice)).json()
    by = {s["store_slug"]: s for s in cart["stores"]}
    assert by["burger-hub"]["discount_paise"] == 2400 and by["chai-point"]["discount_paise"] == 600
    assert cart["total_paise"] == 12000

    off = await client.patch(
        f"{combos}/{combo['id']}/active", json={"is_active": False}, headers=world.org_owner
    )
    assert off.json()["is_active"] is False
    assert (await client.get(CART, headers=alice)).json()["total_paise"] == 15000
    assert (await client.get(PUBLIC)).json()["combos"] == []


async def test_public_offers_list_live_offers_only(client: httpx.AsyncClient, world: World) -> None:
    await client.post(offers_url(world), json=pct(), headers=world.owner)
    await client.post(offers_url(world), json=pct("Off", is_active=False), headers=world.owner)
    offers = (await client.get(PUBLIC)).json()["offers"]
    assert [(o["store_slug"], o["title"]) for o in offers] == [("burger-hub", "10% off")]


async def test_offers_switched_off_take_nothing_off(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    menu: Menu,
    db_session: AsyncSession,
) -> None:
    await client.post(offers_url(world), json=pct(), headers=world.owner)
    await db_session.execute(
        text(
            "INSERT INTO platform_features (key, enabled, updated_at) VALUES ('offers', false, now())"
        )
    )
    await fill(client, alice, menu)
    assert (await client.get(CART, headers=alice)).json()["discount_paise"] == 0
