import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.printing.models import PrintJob
from tests.modules.catalog.conftest import World
from tests.modules.orders.test_orders import checkout, store_url
from tests.modules.printing.conftest import CART, Menu, add_printer, base, line


async def jobs(db: AsyncSession) -> list[PrintJob]:
    return list(
        (await db.execute(select(PrintJob).order_by(PrintJob.created_at, PrintJob.id))).scalars()
    )


async def place(client: httpx.AsyncClient, alice: dict, menu: Menu, key: str = "k1") -> dict:
    await client.post(
        f"{CART}/lines", json=line(menu.burger, 1, qty=2, options=[0], note="spicy"), headers=alice
    )
    return (await checkout(client, alice, key)).json()["stores"][0]


async def step(client: httpx.AsyncClient, w: World, oid: str, name: str) -> None:
    r = await client.post(store_url(w, f"/{oid}/{name}"), headers=w.owner)
    assert r.status_code == 200, r.text


async def test_default_rules_kot_on_accept_and_bill_when_ready(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    alice: dict,
    menu: Menu,
    world: World,
    printers: dict,
) -> None:
    order = await place(client, alice, menu)
    assert await jobs(db_session) == []  # paid is not a trigger by default
    await step(client, world, order["id"], "accept")
    (kot,) = await jobs(db_session)
    assert kot.kind.value == "ticket" and str(kot.printer_id) == printers["kitchen"]["id"]
    assert kot.payload["order_no"] == 1 and kot.payload["items"][0]["quantity"] == 2
    assert order["pickup_code"] not in str(kot.payload) and "price" not in str(kot.payload)
    await step(client, world, order["id"], "preparing")
    await step(client, world, order["id"], "ready")
    kot, bill = await jobs(db_session)
    assert bill.kind.value == "bill" and str(bill.printer_id) == printers["counter"]["id"]
    assert bill.payload["total"] == "400.00" and bill.payload["copy_number"] == 1
    assert order["pickup_code"] not in str(bill.payload)


async def test_rules_are_per_store_and_can_be_changed_or_switched_off(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    alice: dict,
    menu: Menu,
    world: World,
    printers: dict,
) -> None:
    await client.patch(
        f"{base(world)}/settings",
        json={"kot_when": "paid", "bill_when": "picked_up"},
        headers=world.owner,
    )
    order = await place(client, alice, menu)
    assert [j.kind.value for j in await jobs(db_session)] == ["ticket"]  # KOT at payment
    for name in ("accept", "preparing", "ready"):
        await step(client, world, order["id"], name)
    assert [j.kind.value for j in await jobs(db_session)] == ["ticket"]
    code = order["pickup_code"]
    await client.post(
        store_url(world, f"/{order['id']}/pickup"), json={"code": code}, headers=world.owner
    )
    assert [j.kind.value for j in await jobs(db_session)] == ["ticket", "bill"]

    await client.patch(f"{base(world)}/settings", json={"auto_print": False}, headers=world.owner)
    second = await place(client, alice, menu, "k2")
    await step(client, world, second["id"], "accept")
    assert len(await jobs(db_session)) == 2  # nothing new


async def test_orders_work_with_no_printers_and_jobs_never_cross_stores(
    client: httpx.AsyncClient, db_session: AsyncSession, alice: dict, menu: Menu, world: World
) -> None:
    chai_printer = await add_printer(client, world, "Chai printer")  # a printer in the burger store
    order = await place(client, alice, menu)
    await step(client, world, order["id"], "accept")
    (kot,) = await jobs(db_session)
    assert str(kot.store_id) == str(world.store.id)
    # the sibling store has no printers: its order still works, and prints nothing
    await client.post(f"{CART}/lines", json=line(menu.chai), headers=alice)
    other = (await checkout(client, alice, "k9")).json()["stores"][0]
    r = await client.post(
        store_url(world, f"/{other['id']}/accept", other=True), headers=world.other_store_owner
    )
    assert r.status_code == 200
    assert len(await jobs(db_session)) == 1 and chai_printer["id"]


async def test_a_counter_printer_prints_the_kot_when_there_is_no_kitchen_printer(
    client: httpx.AsyncClient, db_session: AsyncSession, alice: dict, menu: Menu, world: World
) -> None:
    counter = await add_printer(client, world, "Only", "counter")
    order = await place(client, alice, menu)
    await step(client, world, order["id"], "accept")
    (kot,) = await jobs(db_session)
    assert kot.kind.value == "ticket" and str(kot.printer_id) == counter["id"]


async def test_design_shows_up_on_the_bill(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    alice: dict,
    menu: Menu,
    world: World,
    printers: dict,
) -> None:
    await client.put(
        f"{base(world)}/print-design",
        json={
            "header_name": "Burger Hub Pvt",
            "footer_text": "See you!",
            "options": {"total_label": "PAY"},
        },
        headers=world.owner,
    )
    await client.patch(
        f"{base(world)}/settings", json={"gstin": "27AAPFU0939F1ZV"}, headers=world.owner
    )
    order = await place(client, alice, menu)
    for name in ("accept", "preparing", "ready"):
        await step(client, world, order["id"], name)
    bill = (await jobs(db_session))[-1].payload
    assert bill["header"]["name"] == "Burger Hub Pvt" and bill["footer"] == "See you!"
    assert bill["options"]["total_label"] == "PAY" and bill["gstin"] == "27AAPFU0939F1ZV"


async def test_reprint_makes_a_new_job_and_a_numbered_bill_copy(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    alice: dict,
    menu: Menu,
    world: World,
    printers: dict,
) -> None:
    order = await place(client, alice, menu)
    for name in ("accept", "preparing", "ready"):
        await step(client, world, order["id"], name)
    base_count = len(await jobs(db_session))
    url = store_url(world, f"/{order['id']}/print")
    r = await client.post(url, json={"what": "bill"}, headers=world.staff)  # staff may reprint
    assert r.status_code == 202 and r.json() == {"queued": 1}
    r = await client.post(url, json={"what": "ticket"}, headers=world.staff)
    assert r.status_code == 202
    all_jobs = await jobs(db_session)
    assert len(all_jobs) == base_count + 2
    bills = [j for j in all_jobs if j.kind.value == "bill"]
    assert [b.payload["copy_number"] for b in bills] == [1, 2]
    assert (await client.post(url, json={"what": "poster"}, headers=world.staff)).status_code == 422
    assert (
        await client.post(url, json={"what": "bill"}, headers=world.outsider)
    ).status_code == 404


async def test_reprint_without_a_printer_is_a_clear_error(
    client: httpx.AsyncClient, alice: dict, menu: Menu, world: World
) -> None:
    order = await place(client, alice, menu)
    r = await client.post(
        store_url(world, f"/{order['id']}/print"), json={"what": "bill"}, headers=world.owner
    )
    assert r.status_code == 400 and r.json()["code"] == "no_printer"
