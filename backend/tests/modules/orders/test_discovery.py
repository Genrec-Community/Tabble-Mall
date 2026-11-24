"""Popular dishes in a mall, and putting a past order back in the cart."""

import httpx

from mallt.modules.payments.provider import FakePaymentProvider
from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import CART, Menu, line
from tests.modules.orders.test_orders import checkout

POPULAR = "/api/v1/public/malls/phoenix-pune/popular"


async def test_popular_ranks_dishes_by_what_people_paid_for(
    client: httpx.AsyncClient, alice: dict, menu: Menu, payments: FakePaymentProvider
) -> None:
    # Nothing ordered yet: the mall still shows dishes (each store's first ones), never an empty rail.
    first = (await client.get(POPULAR)).json()["items"]
    assert {i["product"]["id"] for i in first} == {menu.burger["id"], menu.chai["id"]}

    await client.post(f"{CART}/lines", json=line(menu.chai, qty=3), headers=alice)
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    assert (await checkout(client, alice)).status_code == 201

    items = (await client.get(POPULAR)).json()["items"]
    assert [i["product"]["id"] for i in items][:2] == [menu.chai["id"], menu.burger["id"]]
    assert items[0]["store_slug"] == "chai-point" and items[0]["orders"] == 3


async def test_popular_ignores_unpaid_orders_and_unknown_malls(
    client: httpx.AsyncClient, alice: dict, menu: Menu, payments: FakePaymentProvider
) -> None:
    payments.fail_next = True
    await client.post(f"{CART}/lines", json=line(menu.chai, qty=5), headers=alice)
    await checkout(client, alice)
    items = (await client.get(POPULAR)).json()["items"]
    assert all(i["orders"] == 0 for i in items)
    assert (await client.get("/api/v1/public/malls/nowhere/popular")).status_code == 404


async def test_reorder_puts_a_past_order_back_in_the_cart(
    client: httpx.AsyncClient, alice: dict, menu: Menu, payments: FakePaymentProvider
) -> None:
    await client.post(
        f"{CART}/lines", json=line(menu.burger, 1, qty=2, options=[0], note="spicy"), headers=alice
    )
    await client.post(f"{CART}/lines", json=line(menu.chai), headers=alice)
    order = (await checkout(client, alice)).json()

    r = await client.post(f"{CART}/reorder", json={"order_id": order["id"]}, headers=alice)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 2 and body["skipped"] == []
    lines = {ln["product_name"]: ln for s in body["cart"]["stores"] for ln in s["lines"]}
    burger = lines["Cheese Burger"]
    assert burger["quantity"] == 2 and burger["variant_name"] == "Large"
    assert burger["options"] == ["Extra cheese"] and burger["note"] == "spicy"
    assert lines["Masala Chai"]["quantity"] == 1


async def test_reorder_skips_what_is_gone_and_is_private(
    client: httpx.AsyncClient,
    alice: dict,
    bob: dict,
    world: World,
    menu: Menu,
    payments: FakePaymentProvider,
) -> None:
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    await client.post(f"{CART}/lines", json=line(menu.chai), headers=alice)
    order = (await checkout(client, alice)).json()
    await client.patch(
        f"/api/v1/stores/{world.other_store.id}/products/{menu.chai['id']}/availability",
        json={"is_available": False},
        headers=world.other_store_owner,
    )

    body = (
        await client.post(f"{CART}/reorder", json={"order_id": order["id"]}, headers=alice)
    ).json()
    assert body["added"] == 1 and body["skipped"] == ["Masala Chai"]

    # Someone else's order: as if it did not exist.
    r = await client.post(f"{CART}/reorder", json={"order_id": order["id"]}, headers=bob)
    assert r.status_code == 404


async def test_my_orders_name_their_mall_so_they_can_be_reordered(
    client: httpx.AsyncClient, alice: dict, menu: Menu, payments: FakePaymentProvider
) -> None:
    await client.post(f"{CART}/lines", json=line(menu.chai), headers=alice)
    order = (await checkout(client, alice)).json()
    listed = (await client.get("/api/v1/orders", headers=alice)).json()["items"]
    assert [o["mall_slug"] for o in listed] == ["phoenix-pune"]
    one = (await client.get(f"/api/v1/orders/{order['id']}", headers=alice)).json()
    assert one["mall_slug"] == "phoenix-pune"
