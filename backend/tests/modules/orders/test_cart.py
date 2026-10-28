import httpx

from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import CART, Menu, line


async def add(client: httpx.AsyncClient, h: dict[str, str], body: dict) -> httpx.Response:
    return await client.post(f"{CART}/lines", json=body, headers=h)


async def test_cart_prices_lines_with_option_deltas_and_groups_by_store(
    client: httpx.AsyncClient, alice: dict, menu: Menu
) -> None:
    assert (
        await add(client, alice, line(menu.burger, 1, qty=2, options=[0, 1]))
    ).status_code == 201
    assert (await add(client, alice, line(menu.chai, qty=1))).status_code == 201
    cart = (await client.get(CART, headers=alice)).json()
    by_store = {s["store_slug"]: s for s in cart["stores"]}
    burger = by_store["burger-hub"]["lines"][0]
    assert burger["unit_price_paise"] == 18000 + 2000 + 1500 and burger["quantity"] == 2
    assert burger["line_total_paise"] == 2 * 21500
    assert burger["options"] == ["Extra cheese", "Jalapeno"]
    assert by_store["chai-point"]["subtotal_paise"] == 3000
    assert cart["total_paise"] == 43000 + 3000 and cart["can_checkout"] is True


async def test_identical_lines_merge_and_different_options_do_not(
    client: httpx.AsyncClient, alice: dict, menu: Menu
) -> None:
    await add(client, alice, line(menu.burger, qty=1))
    await add(client, alice, line(menu.burger, qty=2))
    await add(client, alice, line(menu.burger, qty=1, options=[0]))
    lines = (await client.get(CART, headers=alice)).json()["stores"][0]["lines"]
    assert sorted(x["quantity"] for x in lines) == [1, 3]


async def test_update_quantity_note_and_remove(
    client: httpx.AsyncClient, alice: dict, menu: Menu
) -> None:
    created = (await add(client, alice, line(menu.burger))).json()
    lid = created["stores"][0]["lines"][0]["id"]
    r = await client.patch(
        f"{CART}/lines/{lid}", json={"quantity": 4, "note": "no onion"}, headers=alice
    )
    got = r.json()["stores"][0]["lines"][0]
    assert got["quantity"] == 4 and got["note"] == "no onion"
    gone = await client.patch(f"{CART}/lines/{lid}", json={"quantity": 0}, headers=alice)
    assert gone.json()["stores"] == []


async def test_carts_are_private(
    client: httpx.AsyncClient, alice: dict, bob: dict, menu: Menu
) -> None:
    lid = (await add(client, alice, line(menu.burger))).json()["stores"][0]["lines"][0]["id"]
    r = await client.patch(f"{CART}/lines/{lid}", json={"quantity": 9}, headers=bob)
    assert r.status_code == 404
    assert (await client.get(CART, headers=bob)).json()["stores"] == []
    assert (await client.get(CART)).status_code == 401


async def test_rejects_bad_lines(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    ok = line(menu.burger)
    assert (await add(client, alice, {**ok, "quantity": 0})).status_code == 422
    assert (await add(client, alice, {**ok, "quantity": 99})).status_code == 422
    other_variant = menu.chai["variants"][0]["id"]
    r = await add(client, alice, {**ok, "variant_id": other_variant})
    assert r.status_code == 400 and r.json()["code"] == "unknown_variant"
    r = await add(client, alice, {**ok, "product_id": "00000000-0000-7000-8000-000000000001"})
    assert r.status_code == 404
    # three extras where max_select is 2 -> option rule violated
    too_many = line(menu.burger, options=[0, 1])
    too_many["option_ids"].append("00000000-0000-7000-8000-000000000002")
    r = await add(client, alice, too_many)
    assert r.status_code == 400 and r.json()["code"] == "unknown_option"
    r = await client.post("/api/v1/malls/nope/cart/lines", json=ok, headers=alice)
    assert r.status_code == 404


async def test_required_option_groups_are_enforced(
    client: httpx.AsyncClient, alice: dict, world: World
) -> None:
    body = {
        "name": "Pizza",
        "variants": [{"name": "Medium", "price_paise": 20000}],
        "option_groups": [
            {
                "name": "Crust",
                "min_select": 1,
                "max_select": 1,
                "options": [{"name": "Thin"}, {"name": "Thick"}],
            }
        ],
    }
    p = (
        await client.post(
            f"/api/v1/stores/{world.store.id}/products", json=body, headers=world.owner
        )
    ).json()
    missing = {
        "product_id": p["id"],
        "variant_id": p["variants"][0]["id"],
        "option_ids": [],
        "quantity": 1,
    }
    r = await add(client, alice, missing)
    assert r.status_code == 400 and r.json()["code"] == "option_required"
    ok = {**missing, "option_ids": [p["option_groups"][0]["options"][0]["id"]]}
    assert (await add(client, alice, ok)).status_code == 201


async def test_cannot_add_unavailable_or_from_closed_store(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    await client.patch(
        f"/api/v1/stores/{world.store.id}/products/{menu.burger['id']}/availability",
        json={"is_available": False},
        headers=world.staff,
    )
    r = await add(client, alice, line(menu.burger))
    assert r.status_code == 409 and r.json()["code"] == "unavailable"
    await client.patch(
        f"/api/v1/stores/{world.other_store.id}/settings",
        json={"is_paused": True},
        headers=world.other_store_owner,
    )
    r = await add(client, alice, line(menu.chai))
    assert r.status_code == 409 and r.json()["code"] == "store_closed"


async def test_cart_reflects_current_prices_and_flags_lines_that_became_unavailable(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    await add(client, alice, line(menu.burger))
    body = {
        "name": "Cheese Burger",
        "variants": [
            {"id": menu.burger["variants"][0]["id"], "name": "Regular", "price_paise": 15000}
        ],
    }
    await client.put(
        f"/api/v1/stores/{world.store.id}/products/{menu.burger['id']}",
        json=body,
        headers=world.owner,
    )
    cart = (await client.get(CART, headers=alice)).json()
    assert cart["stores"][0]["lines"][0]["unit_price_paise"] == 15000
    await client.delete(
        f"/api/v1/stores/{world.store.id}/products/{menu.burger['id']}", headers=world.owner
    )
    cart = (await client.get(CART, headers=alice)).json()
    assert cart["can_checkout"] is False
    assert cart["stores"][0]["lines"][0]["problem"] == "unavailable"


async def test_clear_cart(client: httpx.AsyncClient, alice: dict, menu: Menu) -> None:
    await add(client, alice, line(menu.burger))
    assert (await client.delete(CART, headers=alice)).status_code == 204
    assert (await client.get(CART, headers=alice)).json()["stores"] == []
