import httpx

from tests.modules.catalog.conftest import World, product_body

URL = "/api/v1/public/malls/phoenix-pune/items"


async def make(client: httpx.AsyncClient, w: World, store: str = "burger", **over: object) -> dict:
    sid, headers = (
        (w.store.id, w.owner) if store == "burger" else (w.other_store.id, w.other_store_owner)
    )
    r = await client.post(
        f"/api/v1/stores/{sid}/products", json=product_body(**over), headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_items_from_every_store_with_their_store(
    client: httpx.AsyncClient, world: World
) -> None:
    await make(client, world, name="Cheese Burger")
    await make(client, world, "chai", name="Masala Chai", diet="veg", option_groups=[])
    r = await client.get(URL)
    assert r.status_code == 200
    body = r.json()
    got = {i["product"]["name"]: i for i in body["items"]}
    assert set(got) == {"Cheese Burger", "Masala Chai"}
    assert got["Cheese Burger"]["store_slug"] == "burger-hub"
    assert got["Masala Chai"]["store_name"] == "Chai-Point"
    assert got["Cheese Burger"]["product"]["variants"][0]["price_paise"] == 12000
    assert "tax_bps" not in str(got["Cheese Burger"]["product"])


async def test_search_matches_name_and_description_and_ignores_case(
    client: httpx.AsyncClient, world: World
) -> None:
    await make(client, world, name="Cheese Burger", description="Juicy patty")
    await make(client, world, name="Paneer Wrap", description="Spicy cheese filling")
    await make(client, world, name="Fries", description=None)
    names = lambda r: sorted(i["product"]["name"] for i in r.json()["items"])  # noqa: E731
    assert names(await client.get(URL, params={"q": "CHEESE"})) == ["Cheese Burger", "Paneer Wrap"]
    assert names(await client.get(URL, params={"q": "juicy"})) == ["Cheese Burger"]
    assert names(await client.get(URL, params={"q": "zzz"})) == []


async def test_search_treats_wildcards_literally(client: httpx.AsyncClient, world: World) -> None:
    await make(client, world, name="100% Juice")
    await make(client, world, name="Cola")
    r = await client.get(URL, params={"q": "%"})
    assert [i["product"]["name"] for i in r.json()["items"]] == ["100% Juice"]
    assert (await client.get(URL, params={"q": "_"})).json()["items"] == []


async def test_filters_by_diet_food_type_and_store(client: httpx.AsyncClient, world: World) -> None:
    await make(client, world, name="Veg Burger", diet="veg")
    await make(client, world, name="Chicken Burger", diet="nonveg")
    await make(client, world, "chai", name="Chai", option_groups=[])
    await client.patch(
        f"/api/v1/stores/{world.other_store.id}/settings",
        json={"food_types": ["beverages"]},
        headers=world.other_store_owner,
    )
    names = lambda r: sorted(i["product"]["name"] for i in r.json()["items"])  # noqa: E731
    assert names(await client.get(URL, params={"diet": "nonveg"})) == ["Chicken Burger"]
    assert names(await client.get(URL, params={"food_type": "beverages"})) == ["Chai"]
    assert names(await client.get(URL, params={"store": "burger-hub"})) == [
        "Chicken Burger",
        "Veg Burger",
    ]
    assert (await client.get(URL, params={"diet": "vegan"})).status_code == 422
    assert (await client.get(URL, params={"food_type": "pizza_planet"})).status_code == 422


async def test_hides_archived_items_and_inactive_or_foreign_stores(
    client: httpx.AsyncClient, world: World
) -> None:
    gone = await make(client, world, name="Retired")
    await client.delete(
        f"/api/v1/stores/{world.store.id}/products/{gone['id']}", headers=world.owner
    )
    await make(client, world, name="Keeper")
    rival = await client.post(
        f"/api/v1/stores/{(await _rival_store(client, world))}/products",
        json=product_body(name="Rival Dish"),
        headers=world.outsider,
    )
    assert rival.status_code == 201
    names = [i["product"]["name"] for i in (await client.get(URL)).json()["items"]]
    assert names == ["Keeper"]  # no archived item, no other mall's item


async def _rival_store(client: httpx.AsyncClient, w: World) -> str:
    me = await client.get("/api/v1/auth/staff/me", headers=w.outsider)
    return me.json()["grants"][0]["store_id"]


async def test_sold_out_items_are_listed_but_marked(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await make(client, world, name="Samosa")
    await client.patch(
        f"/api/v1/stores/{world.store.id}/products/{p['id']}/availability",
        json={"is_available": False},
        headers=world.staff,
    )
    item = (await client.get(URL)).json()["items"][0]
    assert (
        item["product"]["available"] is False
        and item["product"]["unavailable_reason"] == "sold_out"
    )


async def test_paging(client: httpx.AsyncClient, world: World) -> None:
    for i in range(5):
        await make(client, world, name=f"Dish {i}")
    first = (await client.get(URL, params={"limit": 2})).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = (await client.get(URL, params={"limit": 2, "after": first["next_cursor"]})).json()
    third = (await client.get(URL, params={"limit": 2, "after": second["next_cursor"]})).json()
    seen = [i["product"]["name"] for p in (first, second, third) for i in p["items"]]
    assert sorted(seen) == [f"Dish {i}" for i in range(5)] and third["next_cursor"] is None


async def test_unknown_mall_is_404(client: httpx.AsyncClient, world: World) -> None:
    assert (await client.get("/api/v1/public/malls/nope/items")).status_code == 404
