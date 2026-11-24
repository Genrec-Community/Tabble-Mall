import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.payments.provider import FakePaymentProvider
from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import CART, Menu, line

CHECKOUT = "/api/v1/malls/phoenix-pune/checkout"
RATINGS = "/api/v1/public/malls/phoenix-pune/ratings"


async def collected(
    client: httpx.AsyncClient, world: World, h: dict, menu: Menu, key: str = "r1"
) -> dict:
    """Order a burger at Burger Hub and walk it to picked up. Returns the store order."""
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=h)
    order = (await client.post(CHECKOUT, json={}, headers={**h, "Idempotency-Key": key})).json()
    so = order["stores"][0]
    base = f"/api/v1/stores/{world.store.id}/orders/{so['id']}"
    for step in ("accept", "preparing", "ready"):
        assert (await client.post(f"{base}/{step}", headers=world.owner)).status_code == 200
    r = await client.post(f"{base}/pickup", json={"code": so["pickup_code"]}, headers=world.owner)
    assert r.status_code == 200, r.text
    return so


async def test_customer_rates_a_collected_order_and_it_shows_everywhere(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
) -> None:
    so = await collected(client, world, alice, menu)
    url = f"/api/v1/orders/stores/{so['id']}/review"
    r = await client.put(url, json={"rating": 4, "comment": "Great burger"}, headers=alice)
    assert r.status_code == 200, r.text
    assert r.json()["rating"] == 4
    # changing it within a week updates the same review
    await client.put(url, json={"rating": 5, "comment": "Even better"}, headers=alice)

    mine = (await client.get("/api/v1/orders", headers=alice)).json()["items"][0]
    assert mine["stores"][0]["review"]["rating"] == 5

    ratings = (await client.get(RATINGS)).json()
    assert ratings["stores"]["burger-hub"] == {"average": 5.0, "count": 1}
    assert ratings["products"][menu.burger["id"]] == {"average": 5.0, "count": 1}

    public = await client.get("/api/v1/public/malls/phoenix-pune/stores/burger-hub/reviews")
    assert public.json()[0]["comment"] == "Even better"
    assert public.json()[0]["store_order_id"] is None  # customers don't see order ids

    staff = await client.get(f"/api/v1/stores/{world.store.id}/reviews", headers=world.staff)
    item = staff.json()["items"][0]
    assert item["order_no"] == 1 and item["dishes"] == ["Cheese Burger"]
    reply = await client.put(
        f"/api/v1/stores/{world.store.id}/reviews/{item['id']}/reply",
        json={"reply": "Thank you!"},
        headers=world.owner,
    )
    assert reply.json()["reply"] == "Thank you!"

    popular = (await client.get("/api/v1/public/malls/phoenix-pune/popular")).json()["items"]
    burger = next(i for i in popular if i["product"]["id"] == menu.burger["id"])
    assert burger["rating"] == 5.0 and burger["rating_count"] == 1


async def test_only_the_owner_of_a_collected_order_may_rate_it(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    bob: dict,
    menu: Menu,
    payments: FakePaymentProvider,
) -> None:
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    order = (await client.post(CHECKOUT, json={}, headers={**alice, "Idempotency-Key": "x"})).json()
    url = f"/api/v1/orders/stores/{order['stores'][0]['id']}/review"
    r = await client.put(url, json={"rating": 5}, headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "not_collected"
    assert (await client.put(url, json={"rating": 5}, headers=bob)).status_code == 404
    assert (await client.put(url, json={"rating": 6}, headers=alice)).status_code == 422


async def test_store_reviews_are_tenant_scoped(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
) -> None:
    so = await collected(client, world, alice, menu)
    await client.put(f"/api/v1/orders/stores/{so['id']}/review", json={"rating": 3}, headers=alice)
    url = f"/api/v1/stores/{world.store.id}/reviews"
    assert (await client.get(url, headers=world.outsider)).status_code == 404
    assert (await client.get(url, headers=world.other_store_owner)).status_code == 404
    item = (await client.get(url, headers=world.owner)).json()["items"][0]
    other = f"/api/v1/stores/{world.other_store.id}/reviews/{item['id']}/reply"
    r = await client.put(other, json={"reply": "x"}, headers=world.other_store_owner)
    assert r.status_code == 404
    staff_reply = await client.put(
        f"{url}/{item['id']}/reply", json={"reply": "x"}, headers=world.staff
    )
    assert staff_reply.status_code == 200  # store staff may update orders, so may reply


async def test_reviews_switched_off(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    so = await collected(client, world, alice, menu)
    await db_session.execute(
        text(
            "INSERT INTO platform_features (key, enabled, updated_at) VALUES ('reviews', false, now())"
        )
    )
    r = await client.put(
        f"/api/v1/orders/stores/{so['id']}/review", json={"rating": 5}, headers=alice
    )
    assert r.status_code == 404 and r.json()["code"] == "feature_off"
    assert (await client.get(RATINGS)).json() == {"stores": {}, "products": {}}
