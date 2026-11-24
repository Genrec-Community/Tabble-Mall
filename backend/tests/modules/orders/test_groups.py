import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.payments.provider import FakePaymentProvider
from tests.factories import FakeSms
from tests.helpers import customer_headers
from tests.modules.orders.conftest import CART, Menu, line

GROUPS = "/api/v1/malls/phoenix-pune/groups"
CHECKOUT = "/api/v1/malls/phoenix-pune/checkout"


async def name(client: httpx.AsyncClient, h: dict, who: str) -> None:
    r = await client.patch("/api/v1/auth/customer/me", json={"name": who}, headers=h)
    assert r.status_code == 200, r.text


async def test_friends_share_a_link_and_each_pays_their_own_share(
    client: httpx.AsyncClient,
    alice: dict,
    bob: dict,
    menu: Menu,
    payments: FakePaymentProvider,
) -> None:
    await name(client, alice, "Alice Rao")
    await name(client, bob, "Bob")
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    r = await client.post(GROUPS, json={"name": "Lunch"}, headers=alice)
    assert r.status_code == 201, r.text
    group = r.json()
    token = group["token"]
    assert group["is_host"] and group["joined"] and group["status"] == "open"
    assert (await client.get(CART, headers=alice)).json()["group"]["token"] == token

    # bob opens the link, sees alice's pick (first name only) and joins
    peek = (await client.get(f"/api/v1/groups/{token}", headers=bob)).json()
    assert not peek["joined"] and [m["name"] for m in peek["members"]] == ["Alice"]
    assert peek["members"][0]["lines"][0]["product_name"] == "Cheese Burger"
    assert "phone" not in str(peek).lower()
    joined = (await client.post(f"/api/v1/groups/{token}/join", headers=bob)).json()
    assert joined["joined"] and len(joined["members"]) == 2
    await client.post(f"{CART}/lines", json=line(menu.chai, qty=2), headers=bob)

    # each pays only their own cart
    paid = await client.post(CHECKOUT, json={}, headers={**bob, "Idempotency-Key": "g1"})
    assert paid.status_code == 201 and paid.json()["total_paise"] == 6000
    assert paid.json()["group_order_id"] == group["id"]
    view = (await client.get(f"/api/v1/groups/{token}", headers=alice)).json()
    by = {m["name"]: m for m in view["members"]}
    assert by["Bob"]["paid_paise"] == 6000 and by["Bob"]["total_paise"] == 0
    assert by["Alice"]["total_paise"] == 12000 and by["Alice"]["paid_paise"] == 0
    assert payments.charges[0][0] == 6000


async def test_only_the_host_closes_and_a_closed_group_hides_from_strangers(
    client: httpx.AsyncClient, alice: dict, bob: dict, sms: FakeSms, menu: Menu
) -> None:
    token = (await client.post(GROUPS, json={}, headers=alice)).json()["token"]
    await client.post(f"/api/v1/groups/{token}/join", headers=bob)
    assert (await client.post(f"/api/v1/groups/{token}/close", headers=bob)).status_code == 404
    closed = await client.post(f"/api/v1/groups/{token}/close", headers=alice)
    assert closed.json()["status"] == "closed"
    carol = await customer_headers(client, sms, "9000000001")
    assert (await client.get(f"/api/v1/groups/{token}", headers=carol)).status_code == 409
    assert (await client.post(f"/api/v1/groups/{token}/join", headers=carol)).status_code == 409
    # members still see it
    assert (await client.get(f"/api/v1/groups/{token}", headers=bob)).status_code == 200


async def test_leaving_unlinks_the_cart_and_bad_tokens_are_404(
    client: httpx.AsyncClient, alice: dict, bob: dict, menu: Menu
) -> None:
    token = (await client.post(GROUPS, json={}, headers=alice)).json()["token"]
    await client.post(f"/api/v1/groups/{token}/join", headers=bob)
    assert (await client.post(f"/api/v1/groups/{token}/leave", headers=bob)).status_code == 204
    assert (await client.get(CART, headers=bob)).json()["group"] is None
    assert (await client.get("/api/v1/groups/nope", headers=bob)).status_code == 404
    assert (await client.get(f"/api/v1/groups/{token}")).status_code == 401


async def test_starting_twice_returns_the_same_open_group(
    client: httpx.AsyncClient, alice: dict, menu: Menu
) -> None:
    first = (await client.post(GROUPS, json={}, headers=alice)).json()
    again = (await client.post(GROUPS, json={}, headers=alice)).json()
    assert first["token"] == again["token"]


async def test_group_orders_switched_off(
    client: httpx.AsyncClient, alice: dict, menu: Menu, db_session: AsyncSession
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO platform_features (key, enabled, updated_at)"
            " VALUES ('group_orders', false, now())"
        )
    )
    r = await client.post(GROUPS, json={}, headers=alice)
    assert r.status_code == 404 and r.json()["code"] == "feature_off"
