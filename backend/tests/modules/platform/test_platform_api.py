"""Owner dashboard: feature switches, featured spots and the whole-platform directory."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.features import FEATURES
from mallt.core.rbac import Scope
from mallt.core.security import new_totp_secret
from mallt.modules.platform.service import FeatureService
from mallt.modules.tenancy.models import Mall, Store
from tests.factories import make_mall, make_org, make_staff, make_store, store_scope
from tests.helpers import staff_headers


@dataclass
class World:
    mall: Mall
    store: Store
    other: Store
    root: dict[str, str]
    org_owner: dict[str, str]
    store_owner: dict[str, str]


@pytest.fixture
async def world(client: httpx.AsyncClient, db_session: AsyncSession) -> World:
    org = await make_org(db_session, "phoenix")
    mall = await make_mall(db_session, org, "phoenix-pune")
    store = await make_store(db_session, mall, "burger-hub")
    other = await make_store(db_session, mall, "chai-point")
    secret = new_totp_secret()
    await make_staff(db_session, "root", [("platform_admin", Scope.platform())], totp_secret=secret)
    await make_staff(db_session, "orgowner", [("org_owner", Scope.org(org.id))])
    await make_staff(db_session, "owner1", [("store_owner", store_scope(store))])
    return World(
        mall=mall,
        store=store,
        other=other,
        root=await staff_headers(client, "root", totp_secret=secret),
        org_owner=await staff_headers(client, "orgowner"),
        store_owner=await staff_headers(client, "owner1"),
    )


# ---------- feature switches ----------


async def test_public_features_show_defaults(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/features")
    assert r.status_code == 200
    flags = r.json()["flags"]
    assert flags == {k: f.default for k, f in FEATURES.items()}
    assert flags["whatsapp"] is False and flags["sales_reports"] is True


async def test_owner_switches_a_feature_off_and_it_is_audited(
    client: httpx.AsyncClient, world: World
) -> None:
    r = await client.put(
        "/api/v1/admin/features/sales_reports", json={"enabled": False}, headers=world.root
    )
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert (await client.get("/api/v1/features")).json()["flags"]["sales_reports"] is False
    listing = await client.get("/api/v1/admin/features", headers=world.root)
    row = next(f for f in listing.json() if f["key"] == "sales_reports")
    assert row["enabled"] is False and row["default"] is True and row["label"]
    audit = (await client.get("/api/v1/admin/audit", headers=world.root)).json()["items"]
    assert audit[0]["action"] == "feature.updated"
    # Back on again.
    r = await client.put(
        "/api/v1/admin/features/sales_reports", json={"enabled": True}, headers=world.root
    )
    assert (await client.get("/api/v1/features")).json()["flags"]["sales_reports"] is True


async def test_unknown_feature_is_404(client: httpx.AsyncClient, world: World) -> None:
    r = await client.put("/api/v1/admin/features/nope", json={"enabled": True}, headers=world.root)
    assert r.status_code == 404


@pytest.mark.parametrize("who", ["org_owner", "store_owner"])
async def test_only_the_platform_owner_controls_features_and_featured(
    client: httpx.AsyncClient, world: World, who: str
) -> None:
    h = getattr(world, who)
    assert (await client.get("/api/v1/admin/features", headers=h)).status_code == 403
    r = await client.put("/api/v1/admin/features/reviews", json={"enabled": False}, headers=h)
    assert r.status_code == 403
    assert (await client.get("/api/v1/admin/directory", headers=h)).status_code == 403
    assert (await client.get("/api/v1/admin/featured", headers=h)).status_code == 403
    r = await client.post(
        "/api/v1/admin/featured", json={"store_id": str(world.store.id)}, headers=h
    )
    assert r.status_code == 403


async def test_feature_service_reads_switches(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    svc = FeatureService(db_session)
    assert await svc.is_enabled("reviews") is True
    await client.put("/api/v1/admin/features/reviews", json={"enabled": False}, headers=world.root)
    assert await svc.is_enabled("reviews") is False
    with pytest.raises(KeyError):
        await svc.is_enabled("not-a-feature")


# ---------- featured spots ----------


async def test_owner_grants_and_revokes_a_featured_spot(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    r = await client.post(
        "/api/v1/admin/featured",
        json={"store_id": str(world.store.id), "amount_paise": 50000, "note": "November"},
        headers=world.root,
    )
    assert r.status_code == 201, r.text
    spot = r.json()
    assert spot["live"] is True and spot["store_name"] == world.store.name
    assert spot["mall_id"] == str(world.mall.id) and spot["amount_paise"] == 50000
    assert await FeatureService(db_session).featured_store_ids(world.mall.id) == [world.store.id]

    directory = (await client.get("/api/v1/admin/directory", headers=world.root)).json()
    stores = directory["orgs"][0]["malls"][0]["stores"]
    assert {s["slug"]: s["featured"] for s in stores} == {"burger-hub": True, "chai-point": False}

    r = await client.post(f"/api/v1/admin/featured/{spot['id']}/revoke", headers=world.root)
    assert r.status_code == 200 and r.json()["live"] is False and r.json()["revoked_at"]
    assert await FeatureService(db_session).featured_store_ids(world.mall.id) == []


async def test_future_and_expired_spots_are_not_live(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    future = {
        "store_id": str(world.store.id),
        "starts_at": (now + timedelta(days=1)).isoformat(),
    }
    past = {
        "store_id": str(world.other.id),
        "starts_at": (now - timedelta(days=3)).isoformat(),
        "ends_at": (now - timedelta(days=1)).isoformat(),
    }
    for body in (future, past):
        r = await client.post("/api/v1/admin/featured", json=body, headers=world.root)
        assert r.status_code == 201 and r.json()["live"] is False
    assert await FeatureService(db_session).featured_store_ids(world.mall.id) == []
    assert len((await client.get("/api/v1/admin/featured", headers=world.root)).json()) == 2


async def test_end_before_start_is_rejected(client: httpx.AsyncClient, world: World) -> None:
    now = datetime.now(UTC)
    body = {
        "store_id": str(world.store.id),
        "starts_at": now.isoformat(),
        "ends_at": (now - timedelta(hours=1)).isoformat(),
    }
    r = await client.post("/api/v1/admin/featured", json=body, headers=world.root)
    assert r.status_code == 400


async def test_switching_featured_spots_off_hides_every_spot(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    await client.post(
        "/api/v1/admin/featured", json={"store_id": str(world.store.id)}, headers=world.root
    )
    await client.put(
        "/api/v1/admin/features/featured_spots", json={"enabled": False}, headers=world.root
    )
    assert await FeatureService(db_session).featured_store_ids(world.mall.id) == []


async def test_mall_store_cards_carry_the_featured_flag(
    client: httpx.AsyncClient, world: World
) -> None:
    cards_url = "/api/v1/public/malls/phoenix-pune/stores"
    cards = {c["slug"]: c for c in (await client.get(cards_url)).json()}
    assert cards["burger-hub"]["featured"] is False
    await client.post(
        "/api/v1/admin/featured", json={"store_id": str(world.other.id)}, headers=world.root
    )
    cards = {c["slug"]: c for c in (await client.get(cards_url)).json()}
    assert cards["chai-point"]["featured"] is True and cards["chai-point"]["featured_rank"] == 0
    assert cards["burger-hub"]["featured"] is False
    await client.put(
        "/api/v1/admin/features/featured_spots", json={"enabled": False}, headers=world.root
    )
    cards = {c["slug"]: c for c in (await client.get(cards_url)).json()}
    assert cards["chai-point"]["featured"] is False
