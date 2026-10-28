import asyncio
import json

import httpx
from fastapi import FastAPI

from mallt.modules.orders.ws import serve_orders
from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import CART, Menu, line
from tests.modules.orders.test_orders import checkout


class FakeSocket:
    def __init__(self, first: dict | str | None) -> None:
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        if first is not None:
            self.inbox.put_nowait(first if isinstance(first, str) else json.dumps(first))
        self.sent: asyncio.Queue[dict] = asyncio.Queue()
        self.closed: int | None = None

    async def accept(self) -> None: ...

    async def receive_text(self) -> str:
        return await self.inbox.get()

    async def send_text(self, data: str) -> None:
        await self.sent.put(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        self.closed = code

    async def next(self) -> dict:
        async with asyncio.timeout(3):
            return await self.sent.get()


def token(headers: dict[str, str]) -> str:
    return headers["Authorization"].split()[1]


async def connect(app: FastAPI, first: dict | str | None) -> tuple[FakeSocket, asyncio.Task]:
    ws = FakeSocket(first)
    task = asyncio.ensure_future(serve_orders(ws, app))
    return ws, task


async def test_store_and_customer_sockets_get_their_own_events_only(
    client: httpx.AsyncClient, app: FastAPI, alice: dict, bob: dict, menu: Menu, world: World
) -> None:
    # Connect one at a time: in tests every socket shares the one transaction-bound connection.
    store_ws, t1 = await connect(
        app, {"token": token(world.owner), "channel": "store", "store_id": str(world.store.id)}
    )
    assert (await store_ws.next())["type"] == "ready"
    chai_ws, t2 = await connect(
        app,
        {
            "token": token(world.other_store_owner),
            "channel": "store",
            "store_id": str(world.other_store.id),
        },
    )
    assert (await chai_ws.next())["type"] == "ready"
    alice_ws, t3 = await connect(app, {"token": token(alice), "channel": "customer"})
    assert (await alice_ws.next())["type"] == "ready"
    bob_ws, t4 = await connect(app, {"token": token(bob), "channel": "customer"})
    assert (await bob_ws.next())["type"] == "ready"

    await client.post(f"{CART}/lines", json=line(menu.burger), headers=alice)
    assert (await checkout(client, alice)).status_code == 201

    created = await store_ws.next()
    assert created["type"] == "order.created" and created["status"] == "paid"
    assert (await alice_ws.next())["type"] == "order.created"
    assert chai_ws.sent.empty() and bob_ws.sent.empty()  # not their order

    await client.post(
        f"/api/v1/stores/{world.store.id}/orders/{created['store_order_id']}/accept",
        headers=world.owner,
    )
    assert (await store_ws.next())["status"] == "accepted"
    assert (await alice_ws.next())["status"] == "accepted"
    for t in (t1, t2, t3, t4):
        t.cancel()


async def test_refusals_close_with_policy_code(
    app: FastAPI, alice: dict, menu: Menu, world: World
) -> None:
    cases = [
        {"token": "garbage", "channel": "customer"},
        {"channel": "customer"},
        "not json",
        {"token": token(alice), "channel": "store", "store_id": str(world.store.id)},
        {"token": token(world.outsider), "channel": "store", "store_id": str(world.store.id)},
        {"token": token(world.owner), "channel": "store", "store_id": str(world.other_store.id)},
        {"token": token(world.owner), "channel": "customer"},
        {"token": token(world.owner), "channel": "store", "store_id": "nope"},
    ]
    for first in cases:
        ws = FakeSocket(first)
        await serve_orders(ws, app)
        assert ws.closed == 1008, first
        assert ws.sent.empty()


async def test_a_socket_does_not_outlive_its_access_token(
    app: FastAPI, alice: dict, world: World
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"access_ttl_s": 1})
    ws = FakeSocket({"token": token(alice), "channel": "customer"})
    async with asyncio.timeout(5):
        await serve_orders(ws, app)  # returns by itself once the lifetime is up
    assert ws.closed == 1000
    assert (await ws.next())["type"] == "ready"
