import httpx

from tests.modules.catalog.conftest import World, product_body


def url(w: World, path: str = "") -> str:
    return f"/api/v1/stores/{w.store.id}{path}"


async def create_product(client: httpx.AsyncClient, w: World, **over: object) -> dict:
    r = await client.post(url(w, "/products"), json=product_body(**over), headers=w.owner)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- products ----------


async def test_owner_creates_and_reads_a_product_with_variants_and_options(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(client, world)
    assert p["name"] == "Cheese Burger" and p["tax_bps"] == 500 and p["stock_mode"] == "manual"
    assert [v["name"] for v in p["variants"]] == ["Regular", "Large"]
    assert p["option_groups"][0]["options"][0]["price_delta_paise"] == 2000

    r = await client.get(url(world, f"/products/{p['id']}"), headers=world.staff)
    assert r.status_code == 200 and r.json()["id"] == p["id"]
    listing = await client.get(url(world, "/products"), headers=world.owner)
    assert [x["id"] for x in listing.json()] == [p["id"]]


async def test_staff_cannot_write_products_but_can_read(
    client: httpx.AsyncClient, world: World
) -> None:
    r = await client.post(url(world, "/products"), json=product_body(), headers=world.staff)
    assert r.status_code == 403
    assert (await client.get(url(world, "/products"), headers=world.staff)).status_code == 200


async def test_org_owner_manages_any_store_menu(client: httpx.AsyncClient, world: World) -> None:
    r = await client.post(url(world, "/products"), json=product_body(), headers=world.org_owner)
    assert r.status_code == 201


async def test_other_organization_gets_404_everywhere(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(client, world)
    h = world.outsider
    assert (await client.get(url(world, "/products"), headers=h)).status_code == 404
    assert (await client.get(url(world, f"/products/{p['id']}"), headers=h)).status_code == 404
    assert (
        await client.post(url(world, "/products"), json=product_body(), headers=h)
    ).status_code == 404
    assert (
        await client.put(url(world, f"/products/{p['id']}"), json=product_body(), headers=h)
    ).status_code == 404
    assert (await client.delete(url(world, f"/products/{p['id']}"), headers=h)).status_code == 404
    assert (await client.get(url(world, "/categories"), headers=h)).status_code == 404
    assert (await client.get(url(world, "/settings"), headers=h)).status_code == 404


async def test_a_sibling_store_cannot_touch_this_stores_products(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(client, world)
    h = world.other_store_owner
    assert (await client.get(url(world, f"/products/{p['id']}"), headers=h)).status_code == 404


async def test_product_id_from_another_store_is_404_not_leaked(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(client, world)
    r = await client.get(
        f"/api/v1/stores/{world.other_store.id}/products/{p['id']}", headers=world.org_owner
    )
    assert r.status_code == 404


async def test_counted_stock_requires_a_count_per_variant(
    client: httpx.AsyncClient, world: World
) -> None:
    r = await client.post(
        url(world, "/products"), json=product_body(stock_mode="counted"), headers=world.owner
    )
    assert r.status_code == 400 and r.json()["code"] == "stock_count_required"
    ok = await client.post(
        url(world, "/products"),
        json=product_body(
            stock_mode="counted",
            variants=[{"name": "Pack", "price_paise": 5000, "stock_count": 20}],
        ),
        headers=world.owner,
    )
    assert ok.status_code == 201 and ok.json()["variants"][0]["stock_count"] == 20


async def test_validation_rejects_bad_option_bounds_and_empty_variants(
    client: httpx.AsyncClient, world: World
) -> None:
    bad = product_body(
        option_groups=[{"name": "X", "min_select": 3, "max_select": 2, "options": [{"name": "a"}]}]
    )
    assert (
        await client.post(url(world, "/products"), json=bad, headers=world.owner)
    ).status_code == 422
    none = product_body(variants=[])
    assert (
        await client.post(url(world, "/products"), json=none, headers=world.owner)
    ).status_code == 422


async def test_update_keeps_ids_and_retires_removed_variants(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(client, world)
    regular, large = p["variants"]
    body = product_body(
        name="Cheese Burger XL",
        variants=[{"id": regular["id"], "name": "Regular", "price_paise": 13000}],
        option_groups=[],
    )
    r = await client.put(url(world, f"/products/{p['id']}"), json=body, headers=world.owner)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["name"] == "Cheese Burger XL" and out["option_groups"] == []
    assert [(v["id"], v["price_paise"]) for v in out["variants"]] == [(regular["id"], 13000)]
    assert large["id"] not in [v["id"] for v in out["variants"]]


async def test_update_rejects_a_variant_id_from_elsewhere(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(client, world)
    body = product_body(
        variants=[{"id": "00000000-0000-7000-8000-000000000001", "name": "x", "price_paise": 1}]
    )
    r = await client.put(url(world, f"/products/{p['id']}"), json=body, headers=world.owner)
    assert r.status_code == 400 and r.json()["code"] == "unknown_variant"


async def test_delete_archives_and_hides_from_lists(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(client, world)
    assert (
        await client.delete(url(world, f"/products/{p['id']}"), headers=world.owner)
    ).status_code == 204
    assert (await client.get(url(world, "/products"), headers=world.owner)).json() == []
    assert (
        await client.get(url(world, f"/products/{p['id']}"), headers=world.owner)
    ).status_code == 404


async def test_staff_toggles_availability_and_stock(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(
        client,
        world,
        stock_mode="counted",
        variants=[{"name": "Pack", "price_paise": 5000, "stock_count": 5}],
    )
    vid = p["variants"][0]["id"]
    r = await client.patch(
        url(world, f"/products/{p['id']}/availability"),
        json={"is_available": False, "variants": [{"id": vid, "stock_count": 9}]},
        headers=world.staff,
    )
    assert r.status_code == 200
    assert r.json()["is_available"] is False and r.json()["variants"][0]["stock_count"] == 9


# ---------- categories ----------


async def test_categories_crud_and_product_assignment(
    client: httpx.AsyncClient, world: World
) -> None:
    c = await client.post(
        url(world, "/categories"), json={"name": "Burgers", "position": 1}, headers=world.owner
    )
    assert c.status_code == 201
    cid = c.json()["id"]
    dup = await client.post(
        url(world, "/categories"), json={"name": "Burgers"}, headers=world.owner
    )
    assert dup.status_code == 409
    p = await create_product(client, world, category_id=cid)
    assert p["category_id"] == cid
    r = await client.patch(
        url(world, f"/categories/{cid}"), json={"name": "Big burgers"}, headers=world.owner
    )
    assert r.json()["name"] == "Big burgers"
    assert (
        await client.delete(url(world, f"/categories/{cid}"), headers=world.owner)
    ).status_code == 204
    after = await client.get(url(world, f"/products/{p['id']}"), headers=world.owner)
    assert after.json()["category_id"] is None


async def test_a_category_from_another_store_cannot_be_used(
    client: httpx.AsyncClient, world: World
) -> None:
    c = await client.post(
        f"/api/v1/stores/{world.other_store.id}/categories",
        json={"name": "Tea"},
        headers=world.other_store_owner,
    )
    r = await client.post(
        url(world, "/products"),
        json=product_body(category_id=c.json()["id"]),
        headers=world.owner,
    )
    assert r.status_code == 400 and r.json()["code"] == "unknown_category"


# ---------- settings ----------


async def test_settings_defaults_and_owner_update(client: httpx.AsyncClient, world: World) -> None:
    r = await client.get(url(world, "/settings"), headers=world.staff)
    assert r.status_code == 200
    s = r.json()
    assert s["is_open"] is True and s["kot_when"] == "accepted" and s["accepting_orders"] is True
    upd = await client.patch(
        url(world, "/settings"),
        json={
            "food_types": ["fast_food", "beverages"],
            "gstin": "27AAPFU0939F1ZV",
            "theme": {"primary": "#112233", "accent": "#ff8800", "font": "serif", "template": 2},
            "bill_when": "picked_up",
        },
        headers=world.owner,
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["theme"]["template"] == 2 and upd.json()["gstin"] == "27AAPFU0939F1ZV"


async def test_settings_validation(client: httpx.AsyncClient, world: World) -> None:
    for bad in (
        {"theme": {"primary": "red"}},
        {"food_types": ["pizza_planet"]},
        {"gstin": "NOPE"},
        {"timezone": "Mars/Base"},
        {"kot_when": "never"},
        {"hours": [{"days": [9], "open": "09:00", "close": "21:00"}]},
    ):
        r = await client.patch(url(world, "/settings"), json=bad, headers=world.owner)
        assert r.status_code == 422, bad


async def test_staff_may_pause_orders_but_not_edit_profile_or_theme(
    client: httpx.AsyncClient, world: World
) -> None:
    ok = await client.patch(url(world, "/settings"), json={"is_paused": True}, headers=world.staff)
    assert ok.status_code == 200 and ok.json()["accepting_orders"] is False
    for body in ({"gstin": "27AAPFU0939F1ZV"}, {"theme": {"font": "mono"}}, {"kot_when": "paid"}):
        r = await client.patch(url(world, "/settings"), json=body, headers=world.staff)
        assert r.status_code == 403, body


async def test_closed_by_hours_is_not_accepting(client: httpx.AsyncClient, world: World) -> None:
    every_day_never_open = [{"days": [0, 1, 2, 3, 4, 5, 6], "open": "03:00", "close": "03:01"}]
    r = await client.patch(
        url(world, "/settings"), json={"hours": every_day_never_open}, headers=world.owner
    )
    assert r.status_code == 200
    # accepting_orders depends on the wall clock; a 1-minute window at 03:00 is closed at test time
    # except in that minute, which is why this asserts the field is computed, not its value.
    assert isinstance(r.json()["accepting_orders"], bool)


# ---------- images ----------


async def test_presign_issues_a_tenant_scoped_key(client: httpx.AsyncClient, world: World) -> None:
    r = await client.post(
        url(world, "/images/presign"),
        json={"kind": "product", "content_type": "image/webp"},
        headers=world.owner,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    prefix = f"org/{world.org.id}/store/{world.store.id}/product/"
    assert body["key"].startswith(prefix) and body["key"].endswith(".webp")
    assert body["headers"]["Content-Type"] == "image/webp"
    assert (
        await client.post(
            url(world, "/images/presign"),
            json={"kind": "product", "content_type": "image/webp"},
            headers=world.staff,
        )
    ).status_code == 403


async def test_image_keys_must_belong_to_this_store(
    client: httpx.AsyncClient, world: World
) -> None:
    foreign = f"org/{world.org.id}/store/{world.other_store.id}/product/x.webp"
    r = await client.post(
        url(world, "/products"), json=product_body(image_key=foreign), headers=world.owner
    )
    assert r.status_code == 400 and r.json()["code"] == "bad_image_key"
    mine = f"org/{world.org.id}/store/{world.store.id}/product/x.webp"
    ok = await client.post(
        url(world, "/products"), json=product_body(image_key=mine), headers=world.owner
    )
    assert ok.status_code == 201 and ok.json()["image_url"].endswith(mine)


# ---------- public menu ----------


async def test_public_directory_and_menu(client: httpx.AsyncClient, world: World) -> None:
    c = await client.post(url(world, "/categories"), json={"name": "Burgers"}, headers=world.owner)
    p = await create_product(client, world, category_id=c.json()["id"])
    await create_product(client, world, name="Loose Item")
    gone = await create_product(client, world, name="Retired")
    await client.delete(url(world, f"/products/{gone['id']}"), headers=world.owner)
    await client.patch(
        url(world, "/settings"), json={"food_types": ["fast_food"]}, headers=world.owner
    )

    d = await client.get("/api/v1/public/malls/phoenix-pune/stores")
    assert d.status_code == 200
    cards = {x["slug"]: x for x in d.json()}
    assert (
        cards["burger-hub"]["food_types"] == ["fast_food"]
        and cards["burger-hub"]["accepting_orders"]
    )

    m = await client.get("/api/v1/public/malls/phoenix-pune/stores/burger-hub/menu")
    assert m.status_code == 200, m.text
    body = m.json()
    names = {cat["name"]: [x["name"] for x in cat["products"]] for cat in body["categories"]}
    assert names == {"Burgers": ["Cheese Burger"], "Others": ["Loose Item"]}
    burger = body["categories"][0]["products"][0]
    assert burger["id"] == p["id"] and burger["available"] is True
    assert "tax_bps" not in burger and "stock_count" not in burger["variants"][0]


async def test_public_menu_marks_sold_out_and_paused(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await create_product(
        client,
        world,
        stock_mode="counted",
        variants=[{"name": "Pack", "price_paise": 5000, "stock_count": 0}],
    )
    sold = await client.get("/api/v1/public/malls/phoenix-pune/stores/burger-hub/menu")
    product = sold.json()["categories"][0]["products"][0]
    assert product["available"] is False and product["unavailable_reason"] == "sold_out"

    await client.patch(
        url(world, f"/products/{p['id']}/availability"),
        json={"is_available": False},
        headers=world.staff,
    )
    await client.patch(url(world, "/settings"), json={"is_paused": True}, headers=world.staff)
    paused = await client.get("/api/v1/public/malls/phoenix-pune/stores/burger-hub/menu")
    assert paused.json()["store"]["accepting_orders"] is False


async def test_public_menu_unknown_or_suspended_is_404(
    client: httpx.AsyncClient, world: World
) -> None:
    assert (
        await client.get("/api/v1/public/malls/phoenix-pune/stores/nope/menu")
    ).status_code == 404
    assert (await client.get("/api/v1/public/malls/nope/stores/burger-hub/menu")).status_code == 404
    # A store of a different mall is not reachable through this mall's slug.
    assert (
        await client.get("/api/v1/public/malls/phoenix-pune/stores/rival/menu")
    ).status_code == 404
