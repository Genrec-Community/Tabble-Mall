"""'Sold out for today': one tap hides a dish until the store's next local midnight."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.catalog.availability import next_local_midnight
from mallt.modules.catalog.models import Product
from mallt.modules.platform.models import PlatformFeature
from tests.modules.catalog.conftest import World, product_body

MENU = "/api/v1/public/malls/phoenix-pune/stores/burger-hub/menu"


def url(w: World, path: str = "") -> str:
    return f"/api/v1/stores/{w.store.id}{path}"


async def _product(client: httpx.AsyncClient, w: World) -> dict:  # type: ignore[type-arg]
    r = await client.post(url(w, "/products"), json=product_body(), headers=w.owner)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_next_local_midnight_is_the_start_of_tomorrow_in_the_store_timezone() -> None:
    ist = ZoneInfo("Asia/Kolkata")
    # 23:30 IST on 24 Nov is 18:00 UTC; the dish is back at 00:00 IST on 25 Nov.
    now = datetime(2026, 11, 24, 18, 0, tzinfo=UTC)
    assert next_local_midnight(now, "Asia/Kolkata") == datetime(2026, 11, 25, tzinfo=ist)
    # Just after midnight IST, it means the next midnight, not the one that just passed.
    now = datetime(2026, 11, 24, 18, 31, tzinfo=UTC)  # 00:01 IST on 25 Nov
    assert next_local_midnight(now, "Asia/Kolkata") == datetime(2026, 11, 26, tzinfo=ist)


async def test_staff_marks_a_dish_sold_out_for_today(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await _product(client, world)
    r = await client.patch(
        url(world, f"/products/{p['id']}/availability"),
        json={"sold_out_today": True},
        headers=world.staff,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_available"] is True and body["sold_out_until"] is not None
    until = datetime.fromisoformat(body["sold_out_until"])
    assert until > datetime.now(UTC) and until - datetime.now(UTC) <= timedelta(days=1)

    product = (await client.get(MENU)).json()["categories"][0]["products"][0]
    assert product["available"] is False and product["unavailable_reason"] == "sold_out"


async def test_it_comes_back_by_itself_after_midnight(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    p = await _product(client, world)
    await client.patch(
        url(world, f"/products/{p['id']}/availability"),
        json={"sold_out_today": True},
        headers=world.staff,
    )
    # Pretend midnight has passed.
    await db_session.execute(
        update(Product)
        .where(Product.id == p["id"])
        .values(sold_out_until=datetime.now(UTC) - timedelta(minutes=1))
    )
    product = (await client.get(MENU)).json()["categories"][0]["products"][0]
    assert product["available"] is True


async def test_undo_and_marking_available_clear_it(client: httpx.AsyncClient, world: World) -> None:
    p = await _product(client, world)
    avail = url(world, f"/products/{p['id']}/availability")
    await client.patch(avail, json={"sold_out_today": True}, headers=world.staff)
    r = await client.patch(avail, json={"sold_out_today": False}, headers=world.staff)
    assert r.json()["sold_out_until"] is None
    await client.patch(avail, json={"sold_out_today": True}, headers=world.staff)
    r = await client.patch(avail, json={"is_available": True}, headers=world.staff)
    assert r.json()["sold_out_until"] is None
    product = (await client.get(MENU)).json()["categories"][0]["products"][0]
    assert product["available"] is True


async def test_store_card_stops_timing_a_dish_sold_out_today(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await _product(client, world)
    await client.patch(
        url(world, f"/products/{p['id']}/availability"),
        json={"sold_out_today": True},
        headers=world.staff,
    )
    cards = (await client.get("/api/v1/public/malls/phoenix-pune/stores")).json()
    burger = next(c for c in cards if c["slug"] == "burger-hub")
    assert burger["prep_minutes"] is None  # nothing on sale to time


async def test_switched_off_by_the_owner_the_one_tap_is_refused(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    db_session.add(PlatformFeature(key="auto_sold_out", enabled=False))
    await db_session.flush()
    p = await _product(client, world)
    r = await client.patch(
        url(world, f"/products/{p['id']}/availability"),
        json={"sold_out_today": True},
        headers=world.staff,
    )
    assert r.status_code == 404 and r.json()["code"] == "feature_off"


async def test_another_organization_cannot_mark_sold_out(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await _product(client, world)
    r = await client.patch(
        url(world, f"/products/{p['id']}/availability"),
        json={"sold_out_today": True},
        headers=world.outsider,
    )
    assert r.status_code == 404
