"""Daily sales reports and GST invoices, for a store and for its whole mall."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.payments.provider import FakePaymentProvider
from mallt.modules.platform.models import PlatformFeature
from tests.modules.catalog.conftest import World
from tests.modules.orders.conftest import Menu
from tests.modules.orders.test_orders import checkout, fill_cart, store_url


def report_url(w: World, kind: str = "sales") -> str:
    return f"/api/v1/stores/{w.store.id}/reports/{kind}"


async def _two_orders(
    client: httpx.AsyncClient, alice: dict[str, str], menu: Menu, world: World
) -> None:
    await fill_cart(client, alice, menu)
    assert (await checkout(client, alice, "k1")).status_code == 201
    await fill_cart(client, alice, menu)
    r = await checkout(client, alice, "k2")
    assert r.status_code == 201
    # Burger Hub rejects the second order; it must not count as a sale.
    second = next(s for s in r.json()["stores"] if s["store_slug"] == "burger-hub")
    rejected = await client.post(
        store_url(world, f"/{second['id']}/reject"), json={"reason": "busy"}, headers=world.owner
    )
    assert rejected.status_code == 200, rejected.text


async def test_store_sales_report_totals_best_sellers_hours_and_gst(
    client: httpx.AsyncClient,
    alice: dict[str, str],
    menu: Menu,
    world: World,
    payments: FakePaymentProvider,
) -> None:
    await _two_orders(client, alice, menu, world)
    r = await client.get(report_url(world), headers=world.owner)
    assert r.status_code == 200, r.text
    rep = r.json()
    t = rep["totals"]
    assert t["orders"] == 1 and t["items"] == 2
    assert t["gross_paise"] == 40000 and t["tax_paise"] == 1905
    assert t["taxable_paise"] == 40000 - 1905
    assert t["gateway_fee_paise"] == 200 and t["payout_paise"] == 39800
    assert t["cancelled_orders"] == 1
    assert rep["best_sellers"] == [
        {
            "name": "Cheese Burger",
            "variant_name": "Large",
            "store_name": world.store.name,
            "quantity": 2,
            "gross_paise": 40000,
        }
    ]
    assert len(rep["hours"]) == 24 and sum(h["orders"] for h in rep["hours"]) == 1
    assert rep["gst"] == [
        {
            "tax_bps": 500,
            "taxable_paise": 38095,
            "cgst_paise": 952,
            "sgst_paise": 953,
            "tax_paise": 1905,
            "gross_paise": 40000,
        }
    ]
    assert len(rep["days"]) == 1 and rep["days"][0]["gross_paise"] == 40000


async def test_store_invoices_are_gst_ready_and_hide_the_pickup_code(
    client: httpx.AsyncClient,
    alice: dict[str, str],
    menu: Menu,
    world: World,
    payments: FakePaymentProvider,
) -> None:
    await _two_orders(client, alice, menu, world)
    r = await client.get(report_url(world, "invoices"), headers=world.owner)
    assert r.status_code == 200, r.text
    invoices = r.json()
    assert len(invoices) == 1
    inv = invoices[0]
    assert inv["invoice_no"].endswith("-0001") and inv["sac"] == "996331"
    assert inv["total_paise"] == 40000 and inv["cgst_paise"] + inv["sgst_paise"] == 1905
    assert inv["lines"][0]["quantity"] == 2 and inv["lines"][0]["taxable_paise"] == 38095
    assert "pickup_code" not in str(inv)


async def test_mall_report_adds_up_every_store(
    client: httpx.AsyncClient,
    alice: dict[str, str],
    menu: Menu,
    world: World,
    payments: FakePaymentProvider,
) -> None:
    await _two_orders(client, alice, menu, world)
    r = await client.get(f"/api/v1/malls/{world.mall.id}/reports/sales", headers=world.org_owner)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["totals"]["orders"] == 3  # one burger order, two chai orders
    assert rep["totals"]["gross_paise"] == 40000 + 2 * 3000
    by_store = {s["store_name"]: s["totals"]["gross_paise"] for s in rep["stores"]}
    assert by_store == {world.store.name: 40000, world.other_store.name: 6000}
    assert rep["best_sellers"][0]["name"] == "Cheese Burger"


async def test_who_may_read_reports(
    client: httpx.AsyncClient, world: World, menu: Menu, payments: FakePaymentProvider
) -> None:
    assert (await client.get(report_url(world), headers=world.owner)).status_code == 200
    assert (await client.get(report_url(world), headers=world.org_owner)).status_code == 200
    # Counter staff run orders but don't see the books.
    assert (await client.get(report_url(world), headers=world.staff)).status_code == 403
    # A store owner can't read the whole mall, or a sibling store.
    mall = f"/api/v1/malls/{world.mall.id}/reports/sales"
    assert (await client.get(mall, headers=world.owner)).status_code == 403
    sibling = f"/api/v1/stores/{world.other_store.id}/reports/sales"
    assert (await client.get(sibling, headers=world.owner)).status_code in (403, 404)


async def test_another_organization_gets_404(client: httpx.AsyncClient, world: World) -> None:
    for path in (report_url(world), report_url(world, "invoices")):
        assert (await client.get(path, headers=world.outsider)).status_code == 404
    mall = f"/api/v1/malls/{world.mall.id}/reports/sales"
    assert (await client.get(mall, headers=world.outsider)).status_code == 404


async def test_date_range_is_checked(client: httpx.AsyncClient, world: World) -> None:
    r = await client.get(
        report_url(world), params={"start": "2026-11-10", "end": "2026-11-01"}, headers=world.owner
    )
    assert r.status_code == 400
    r = await client.get(
        report_url(world), params={"start": "2026-01-01", "end": "2026-11-01"}, headers=world.owner
    )
    assert r.status_code == 400


async def test_switched_off_reports_are_404(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    db_session.add(PlatformFeature(key="sales_reports", enabled=False))
    await db_session.flush()
    r = await client.get(report_url(world), headers=world.owner)
    assert r.status_code == 404 and r.json()["code"] == "feature_off"
