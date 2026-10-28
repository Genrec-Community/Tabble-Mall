from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from mallt.modules.payments.provider import FakePaymentProvider
from tests.factories import FakeSms
from tests.helpers import customer_headers
from tests.modules.catalog.conftest import World, product_body, world  # noqa: F401

PHONE_A = "9361899061"
PHONE_B = "9876543210"
CART = "/api/v1/malls/phoenix-pune/cart"


@dataclass
class Menu:
    burger: dict  # store: burger-hub, variants Regular 12000 / Large 18000, option group Extras
    chai: dict  # store: chai-point, one variant 3000


@pytest.fixture
def payments(app: FastAPI) -> FakePaymentProvider:
    provider = FakePaymentProvider()
    app.state.payments = provider
    return provider


@pytest.fixture
async def alice(client: httpx.AsyncClient, sms: FakeSms, world: World) -> dict[str, str]:  # noqa: F811
    return await customer_headers(client, sms, PHONE_A)


@pytest.fixture
async def bob(client: httpx.AsyncClient, sms: FakeSms, world: World) -> dict[str, str]:  # noqa: F811
    return await customer_headers(client, sms, PHONE_B)


@pytest.fixture
async def menu(client: httpx.AsyncClient, world: World) -> Menu:  # noqa: F811
    burger = await client.post(
        f"/api/v1/stores/{world.store.id}/products", json=product_body(), headers=world.owner
    )
    chai = await client.post(
        f"/api/v1/stores/{world.other_store.id}/products",
        json=product_body(
            name="Masala Chai",
            diet="veg",
            variants=[{"name": "Cup", "price_paise": 3000}],
            option_groups=[],
        ),
        headers=world.other_store_owner,
    )
    assert burger.status_code == 201 and chai.status_code == 201
    return Menu(burger=burger.json(), chai=chai.json())


def line(
    product: dict,
    variant: int = 0,
    *,
    qty: int = 1,
    options: list[int] | None = None,
    note: str | None = None,
) -> dict:
    groups = product["option_groups"]
    ids = [groups[0]["options"][i]["id"] for i in (options or [])]
    return {
        "product_id": product["id"],
        "variant_id": product["variants"][variant]["id"],
        "option_ids": ids,
        "quantity": qty,
        "note": note,
    }
