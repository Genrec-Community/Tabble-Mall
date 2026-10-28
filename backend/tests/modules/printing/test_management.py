import io

import httpx
from PIL import Image

from tests.modules.catalog.conftest import World
from tests.modules.printing.conftest import add_printer, base


def logo_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 120), (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


# ---------- agents ----------


async def test_pairing_shows_the_token_once_and_never_again(
    client: httpx.AsyncClient, world: World
) -> None:
    r = await client.post(
        f"{base(world)}/print-agents", json={"name": "Counter PC"}, headers=world.owner
    )
    assert r.status_code == 201
    body = r.json()
    agent_id = body["agent"]["id"]
    assert body["token"].startswith(agent_id + ".") and len(body["token"]) > 40
    assert body["agent"]["online"] is False and body["agent"]["last_seen_at"] is None
    listing = await client.get(f"{base(world)}/print-agents", headers=world.owner)
    assert all("token" not in a and "token_hash" not in a for a in listing.json())
    dup = await client.post(
        f"{base(world)}/print-agents", json={"name": "Counter PC"}, headers=world.owner
    )
    assert dup.status_code == 409


async def test_rotate_and_revoke(client: httpx.AsyncClient, world: World) -> None:
    created = (
        await client.post(f"{base(world)}/print-agents", json={"name": "PC"}, headers=world.owner)
    ).json()
    aid = created["agent"]["id"]
    rotated = await client.post(f"{base(world)}/print-agents/{aid}/rotate", headers=world.owner)
    assert rotated.status_code == 200 and rotated.json()["token"] != created["token"]
    revoked = await client.post(f"{base(world)}/print-agents/{aid}/revoke", headers=world.owner)
    assert revoked.json()["is_active"] is False


async def test_only_printer_managers_of_this_store_can_manage_agents(
    client: httpx.AsyncClient, world: World
) -> None:
    url = f"{base(world)}/print-agents"
    assert (await client.get(url, headers=world.staff)).status_code == 403
    assert (await client.post(url, json={"name": "x"}, headers=world.staff)).status_code == 403
    for headers in (world.outsider, world.other_store_owner):
        expected = 404 if headers is world.outsider else 403
        assert (await client.get(url, headers=headers)).status_code in {404, expected}
    assert (await client.get(url, headers=world.org_owner)).status_code == 200
    assert (await client.get(url)).status_code == 401


# ---------- printers ----------


async def test_printer_crud_validation_and_isolation(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await add_printer(client, world, layout={"cut": "full", "copies": 2})
    assert p["layout"]["cut"] == "full" and p["paper_width"] == 32 and p["is_active"] is True
    assert (
        await client.post(
            f"{base(world)}/printers",
            json={"name": "Kitchen", "connection": "lan", "target": "1.1.1.1"},
            headers=world.owner,
        )
    ).status_code == 409
    for bad in (
        {"paper_width": 40},
        {"layout": {"copies": 9}},
        {"layout": {"mystery": 1}},
        {"connection": "carrier-pigeon"},
        {"target": "bad\nnewline"},
        {"role": "chef"},
    ):
        body = {"name": "X", "connection": "lan", "target": "1.1.1.1", **bad}
        r = await client.post(f"{base(world)}/printers", json=body, headers=world.owner)
        assert r.status_code == 422, bad
    upd = await client.patch(
        f"{base(world)}/printers/{p['id']}",
        json={"name": "Kitchen 2", "paper_width": 48, "is_active": False},
        headers=world.owner,
    )
    assert upd.json()["name"] == "Kitchen 2" and upd.json()["is_active"] is False
    other = f"/api/v1/stores/{world.other_store.id}/printers/{p['id']}"
    assert (
        await client.patch(other, json={"name": "hijack"}, headers=world.other_store_owner)
    ).status_code == 404
    assert (await client.get(f"{base(world)}/printers", headers=world.outsider)).status_code == 404
    assert (await client.get(f"{base(world)}/printers", headers=world.staff)).status_code == 403


async def test_test_print_queues_a_job_visible_in_history(
    client: httpx.AsyncClient, world: World
) -> None:
    p = await add_printer(client, world)
    r = await client.post(f"{base(world)}/printers/{p['id']}/test", headers=world.owner)
    assert r.status_code == 202 and r.json()["kind"] == "test" and r.json()["status"] == "queued"
    jobs = await client.get(f"{base(world)}/print-jobs", headers=world.staff)  # staff may see jobs
    assert [j["kind"] for j in jobs.json()] == ["test"]
    await client.patch(
        f"{base(world)}/printers/{p['id']}", json={"is_active": False}, headers=world.owner
    )
    off = await client.post(f"{base(world)}/printers/{p['id']}/test", headers=world.owner)
    assert off.status_code == 400 and off.json()["code"] == "printer_inactive"


# ---------- design ----------


async def test_design_defaults_update_and_validation(
    client: httpx.AsyncClient, world: World
) -> None:
    d = (await client.get(f"{base(world)}/print-design", headers=world.owner)).json()
    assert d["has_logo"] is False and d["header_name"] is None
    body = {
        "header_name": "Burger Hub",
        "header_address": "Shop 4, Phoenix Mall",
        "footer_text": "Visit again!",
        "options": {
            "show_tax_breakdown": False,
            "total_label": "AMOUNT",
            "bill_title": "  TAX   BILL ",
        },
    }
    r = await client.put(f"{base(world)}/print-design", json=body, headers=world.owner)
    assert r.status_code == 200
    assert (
        r.json()["options"]["bill_title"] == "TAX BILL"
        and r.json()["options"]["show_tax_breakdown"] is False
    )
    bad = await client.put(
        f"{base(world)}/print-design",
        json={"options": {"total_label": "x" * 40}},
        headers=world.owner,
    )
    assert bad.status_code == 422
    unknown = await client.put(
        f"{base(world)}/print-design", json={"options": {"nope": True}}, headers=world.owner
    )
    assert unknown.status_code == 422
    assert (
        await client.put(f"{base(world)}/print-design", json={}, headers=world.staff)
    ).status_code == 403


async def test_logo_upload_download_and_removal(client: httpx.AsyncClient, world: World) -> None:
    url = f"{base(world)}/print-design/logo"
    assert (await client.get(url, headers=world.owner)).status_code == 404
    up = await client.put(
        url, content=logo_bytes(), headers={**world.owner, "Content-Type": "image/png"}
    )
    assert up.status_code == 200 and up.json()["has_logo"] is True
    got = await client.get(url, headers=world.owner)
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(got.content)).mode == "L"
    junk = await client.put(url, content=b"not an image", headers=world.owner)
    assert junk.status_code == 400 and junk.json()["code"] == "bad_image"
    assert (await client.put(url, content=logo_bytes(), headers=world.staff)).status_code == 403
    assert (await client.get(url, headers=world.outsider)).status_code == 404
    gone = await client.delete(url, headers=world.owner)
    assert (
        gone.json()["has_logo"] is False
        and (await client.get(url, headers=world.owner)).status_code == 404
    )
