import httpx
import pytest

from tests.modules.catalog.conftest import World, world  # noqa: F401
from tests.modules.orders.conftest import (  # noqa: F401
    CART,
    Menu,
    alice,
    bob,
    line,
    menu,
    payments,
)


def base(w: World) -> str:
    return f"/api/v1/stores/{w.store.id}"


async def add_printer(
    client: httpx.AsyncClient,
    w: World,
    name: str = "Kitchen",
    role: str = "kitchen",
    **over: object,
) -> dict:
    body = {"name": name, "role": role, "connection": "lan", "target": "192.168.1.50", **over}
    r = await client.post(f"{base(w)}/printers", json=body, headers=w.owner)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def printers(client: httpx.AsyncClient, world: World) -> dict[str, dict]:  # noqa: F811
    return {
        "kitchen": await add_printer(client, world, "Kitchen", "kitchen"),
        "counter": await add_printer(client, world, "Counter", "counter", paper_width=48),
    }
