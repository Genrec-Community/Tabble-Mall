import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.catalog.service import OrderableStore
from mallt.modules.orders import schedule
from mallt.modules.orders.models import StoreOrder
from mallt.modules.payments.provider import FakePaymentProvider
from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import CART, Menu, line

CHECKOUT = "/api/v1/malls/phoenix-pune/checkout"
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 25, 6, 2, tzinfo=UTC)  # Wednesday 11:32 in Kolkata


def store(hours: list[dict] | None = None, name: str = "Burger Hub") -> OrderableStore:
    return OrderableStore(
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        "s",
        name,
        "Asia/Kolkata",
        True,
        None,
        hours or [],
    )


def test_slots_start_after_the_food_can_be_ready_on_quarter_hours() -> None:
    out = schedule.slots(NOW, 12, [store()])
    # 11:32 + 12 min + 5 min margin = 11:49 → first slot 12:00 local (06:30 UTC)
    assert out[0] == datetime(2026, 11, 25, 6, 30, tzinfo=UTC)
    assert all((b - a) == timedelta(minutes=15) for a, b in zip(out, out[1:], strict=False))
    assert out[-1] <= NOW + schedule.MAX_AHEAD and len(out) == 47  # 12:00 .. 23:30


def test_slots_skip_times_any_store_is_closed() -> None:
    lunch = [{"days": [2], "open": "12:00", "close": "13:00"}]
    out = schedule.slots(NOW, 12, [store(), store(lunch)])
    assert [t.astimezone(IST).strftime("%H:%M") for t in out] == [
        "12:00",
        "12:15",
        "12:30",
        "12:45",
    ]


def test_problem_explains_too_soon_too_late_and_closed() -> None:
    s = [store([{"days": [2], "open": "11:00", "close": "15:00"}], "Chai Point")]
    assert "12 minutes" in (schedule.problem(NOW + timedelta(minutes=5), NOW, 12, s) or "")
    assert "12 hours" in (schedule.problem(NOW + timedelta(hours=13), NOW, 12, s) or "")
    assert "Chai Point will be closed" in (
        schedule.problem(NOW + timedelta(hours=5), NOW, 12, s) or ""
    )
    assert schedule.problem(NOW + timedelta(minutes=30), NOW, 12, s) is None


async def test_pickup_slots_endpoint_and_scheduled_checkout(
    client: httpx.AsyncClient,
    world: World,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    slots = (await client.get(f"{CART}/pickup-slots", headers=alice)).json()
    assert slots["enabled"] and slots["asap_minutes"] == 12 and slots["slots"]
    when = slots["slots"][2]
    r = await client.post(
        CHECKOUT, json={"pickup_at": when}, headers={**alice, "Idempotency-Key": "s1"}
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["pickup_at"] is not None and order["stores"][0]["pickup_at"] is not None
    row = (await db_session.execute(select(StoreOrder))).scalar_one()
    assert row.pickup_at == datetime.fromisoformat(when)
    staff = await client.get(f"/api/v1/stores/{world.store.id}/orders", headers=world.owner)
    assert staff.json()["items"][0]["pickup_at"] is not None


async def test_checkout_refuses_a_time_too_soon(
    client: httpx.AsyncClient, alice: dict, menu: Menu, payments: FakePaymentProvider
) -> None:
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    soon = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()
    r = await client.post(
        CHECKOUT, json={"pickup_at": soon}, headers={**alice, "Idempotency-Key": "s2"}
    )
    assert r.status_code == 400 and r.json()["code"] == "bad_pickup_time"
    assert payments.charges == []


async def test_schedule_ahead_switched_off(
    client: httpx.AsyncClient,
    alice: dict,
    menu: Menu,
    payments: FakePaymentProvider,
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO platform_features (key, enabled, updated_at)"
            " VALUES ('schedule_ahead', false, now())"
        )
    )
    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    slots = (await client.get(f"{CART}/pickup-slots", headers=alice)).json()
    assert slots == {"enabled": False, "asap_minutes": 12, "slots": []}
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = await client.post(
        CHECKOUT, json={"pickup_at": later}, headers={**alice, "Idempotency-Key": "s3"}
    )
    assert r.status_code == 400 and r.json()["code"] == "feature_off"
