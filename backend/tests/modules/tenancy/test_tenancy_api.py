import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus
from mallt.core.rbac import Scope
from mallt.core.security import new_totp_secret
from mallt.modules.audit.models import AuditLog
from mallt.modules.tenancy.models import Mall, Organization
from tests.factories import (
    make_mall,
    make_org,
    make_staff,
    make_store,
    store_scope,
)
from tests.helpers import staff_headers

ORG_BODY = {
    "name": "Phoenix Group",
    "slug": "phoenix",
    "owner": {"username": "phoenix.owner", "display_name": "Phoenix Owner"},
}


async def admin(client: httpx.AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    secret = new_totp_secret()
    await make_staff(db_session, "root", [("platform_admin", Scope.platform())], totp_secret=secret)
    return await staff_headers(client, "root", totp_secret=secret)


async def audit_actions(db_session: AsyncSession) -> list[str]:
    rows = await db_session.execute(
        select(AuditLog.action).order_by(AuditLog.created_at, AuditLog.id)
    )
    return list(rows.scalars())


# ---------- organizations ----------


async def test_admin_creates_org_with_an_owner_who_must_change_password(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    h = await admin(client, db_session)
    r = await client.post("/api/v1/orgs", json=ORG_BODY, headers=h)

    assert r.status_code == 201
    body = r.json()
    assert body["org"]["slug"] == "phoenix" and body["org"]["commission_bps"] == 500
    assert body["owner_username"] == "phoenix.owner" and len(body["temp_password"]) >= 16

    owner = await client.post(
        "/api/v1/auth/staff/login",
        json={"username": "phoenix.owner", "password": body["temp_password"]},
    )
    assert owner.status_code == 200
    me = (
        await client.get(
            "/api/v1/auth/staff/me",
            headers={"Authorization": f"Bearer {owner.json()['access_token']}"},
        )
    ).json()
    assert me["must_change_password"] is True
    (grant,) = me["grants"]
    assert grant["role_key"] == "org_owner" and grant["organization_id"] == body["org"]["id"]
    assert await audit_actions(db_session) == ["org.created"]


async def test_org_creation_is_all_or_nothing_and_rejects_duplicates(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    h = await admin(client, db_session)
    assert (await client.post("/api/v1/orgs", json=ORG_BODY, headers=h)).status_code == 201

    same_slug = {**ORG_BODY, "owner": {"username": "other.owner", "display_name": "O"}}
    r = await client.post("/api/v1/orgs", json=same_slug, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "slug_taken"

    same_owner = {**ORG_BODY, "slug": "second"}
    r = await client.post("/api/v1/orgs", json=same_owner, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "username_taken"

    slugs = (await db_session.execute(select(Organization.slug))).scalars().all()
    assert sorted(slugs) == ["phoenix"]  # the half-created "second" org was rolled back


async def test_only_platform_admin_can_create_orgs(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    r = await client.post(
        "/api/v1/orgs", json=ORG_BODY, headers=await staff_headers(client, "owner")
    )
    assert r.status_code == 403


async def test_org_input_is_validated(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    h = await admin(client, db_session)
    for bad in ({"slug": "Bad Slug!"}, {"slug": "ab"}, {"name": ""}):
        r = await client.post("/api/v1/orgs", json={**ORG_BODY, **bad}, headers=h)
        assert r.status_code == 422, bad
    org = await make_org(db_session, "ok-org")
    r = await client.patch(f"/api/v1/orgs/{org.id}", json={"commission_bps": 10001}, headers=h)
    assert r.status_code == 422
    r = await client.patch(f"/api/v1/orgs/{org.id}", json={"accept_timeout_s": 5}, headers=h)
    assert r.status_code == 422


async def test_org_lists_are_scoped_and_paged(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    a = await make_org(db_session, "org-a")
    b = await make_org(db_session, "org-b")
    c = await make_org(db_session, "org-c")
    await make_staff(db_session, "owner-a", [("org_owner", Scope.org(a.id))])
    own = await client.get("/api/v1/orgs", headers=await staff_headers(client, "owner-a"))
    assert [o["slug"] for o in own.json()["items"]] == ["org-a"]

    h = await admin(client, db_session)
    first = (await client.get("/api/v1/orgs?limit=2", headers=h)).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = (
        await client.get(f"/api/v1/orgs?limit=2&cursor={first['next_cursor']}", headers=h)
    ).json()
    got = [o["id"] for o in first["items"] + second["items"]]
    assert sorted(got) == sorted(str(o.id) for o in (a, b, c)) and second["next_cursor"] is None


async def test_org_settings_and_commission_permissions(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    await make_staff(db_session, "manager", [("org_manager", Scope.org(org.id))])
    owner = await staff_headers(client, "owner")
    manager = await staff_headers(client, "manager")
    url = f"/api/v1/orgs/{org.id}"

    assert (await client.patch(url, json={"name": "New"}, headers=manager)).status_code == 403
    ok = await client.patch(url, json={"name": "New Name", "accept_timeout_s": 600}, headers=owner)
    assert ok.status_code == 200 and ok.json()["name"] == "New Name"
    # Commission is MallT's revenue: only the platform may change it.
    assert (await client.patch(url, json={"commission_bps": 0}, headers=owner)).status_code == 403
    root = await admin(client, db_session)
    done = await client.patch(url, json={"commission_bps": 700}, headers=root)
    assert done.status_code == 200 and done.json()["commission_bps"] == 700
    assert await audit_actions(db_session) == ["org.updated", "org.updated"]


async def test_cross_org_access_is_404(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    org_a, org_b = await make_org(db_session, "org-a"), await make_org(db_session, "org-b")
    mall_b = await make_mall(db_session, org_b, "mall-b")
    store_b = await make_store(db_session, mall_b, "store-b")
    await make_staff(db_session, "owner-a", [("org_owner", Scope.org(org_a.id))])
    h = await staff_headers(client, "owner-a")

    for method, url, body in (
        ("get", f"/api/v1/orgs/{org_b.id}", None),
        ("patch", f"/api/v1/orgs/{org_b.id}", {"name": "x"}),
        ("get", f"/api/v1/orgs/{org_b.id}/malls", None),
        ("post", f"/api/v1/orgs/{org_b.id}/malls", {"name": "M", "slug": "mall-x"}),
        ("get", f"/api/v1/malls/{mall_b.id}", None),
        ("patch", f"/api/v1/malls/{mall_b.id}", {"name": "x"}),
        ("post", f"/api/v1/malls/{mall_b.id}/suspend", None),
        ("get", f"/api/v1/malls/{mall_b.id}/stores", None),
        ("post", f"/api/v1/malls/{mall_b.id}/stores", {"name": "S", "slug": "store-x"}),
        ("get", f"/api/v1/stores/{store_b.id}", None),
        ("patch", f"/api/v1/stores/{store_b.id}", {"description": "x"}),
        ("post", f"/api/v1/stores/{store_b.id}/suspend", None),
    ):
        r = await client.request(method, url, json=body, headers=h)
        assert r.status_code == 404, (method, url, r.status_code)
    assert await audit_actions(db_session) == []


# ---------- malls and stores ----------


async def test_org_owner_builds_malls_and_stores(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    h = await staff_headers(client, "owner")

    mall = await client.post(
        f"/api/v1/orgs/{org.id}/malls",
        json={"name": "Phoenix Pune", "slug": "phoenix-pune", "city": "Pune"},
        headers=h,
    )
    assert mall.status_code == 201 and mall.json()["status"] == "active"
    mall_id = mall.json()["id"]
    store = await client.post(
        f"/api/v1/malls/{mall_id}/stores",
        json={"name": "Burger Hub", "slug": "burger-hub"},
        headers=h,
    )
    assert store.status_code == 201 and store.json()["mall_id"] == mall_id
    assert store.json()["organization_id"] == str(org.id)

    upd = await client.patch(f"/api/v1/malls/{mall_id}", json={"address": "Viman Nagar"}, headers=h)
    assert upd.status_code == 200 and upd.json()["address"] == "Viman Nagar"
    assert [
        m["slug"] for m in (await client.get(f"/api/v1/orgs/{org.id}/malls", headers=h)).json()
    ] == ["phoenix-pune"]
    assert [
        s["slug"] for s in (await client.get(f"/api/v1/malls/{mall_id}/stores", headers=h)).json()
    ] == ["burger-hub"]
    assert await audit_actions(db_session) == ["mall.created", "store.created", "mall.updated"]


async def test_duplicate_and_invalid_slugs(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org, "taken-mall")
    await make_store(db_session, mall, "taken-store")
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    h = await staff_headers(client, "owner")

    dup_mall = await client.post(
        f"/api/v1/orgs/{org.id}/malls", json={"name": "M", "slug": "taken-mall"}, headers=h
    )
    assert dup_mall.status_code == 409 and dup_mall.json()["code"] == "slug_taken"
    dup_store = await client.post(
        f"/api/v1/malls/{mall.id}/stores", json={"name": "S", "slug": "taken-store"}, headers=h
    )
    assert dup_store.status_code == 409 and dup_store.json()["code"] == "slug_taken"
    bad = await client.post(
        f"/api/v1/orgs/{org.id}/malls", json={"name": "M", "slug": "Bad_Slug"}, headers=h
    )
    assert bad.status_code == 422
    # The same store slug in a different mall is fine.
    other = await make_mall(db_session, org, "other-mall")
    ok = await client.post(
        f"/api/v1/malls/{other.id}/stores", json={"name": "S", "slug": "taken-store"}, headers=h
    )
    assert ok.status_code == 201


async def test_store_owner_edits_description_but_not_name_or_status(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    store = await make_store(db_session, mall)
    await make_staff(db_session, "so", [("store_owner", store_scope(store))])
    h = await staff_headers(client, "so")
    url = f"/api/v1/stores/{store.id}"

    ok = await client.patch(url, json={"description": "Best burgers"}, headers=h)
    assert ok.status_code == 200 and ok.json()["description"] == "Best burgers"
    assert (await client.patch(url, json={"name": "Renamed"}, headers=h)).status_code == 403
    assert (await client.post(f"{url}/suspend", headers=h)).status_code == 403
    assert (await client.patch(url, json={"commission_bps": 0}, headers=h)).status_code == 403
    assert (await client.get(url, headers=h)).json()["name"] == store.name


async def test_org_manager_can_rename_and_suspend_stores_and_platform_sets_override(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    store = await make_store(db_session, mall)
    await make_staff(db_session, "mgr", [("org_manager", Scope.org(org.id))])
    h = await staff_headers(client, "mgr")
    url = f"/api/v1/stores/{store.id}"

    assert (await client.patch(url, json={"name": "Renamed"}, headers=h)).json()[
        "name"
    ] == "Renamed"
    assert (await client.post(f"{url}/suspend", headers=h)).json()["status"] == "suspended"
    assert (await client.post(f"{url}/activate", headers=h)).json()["status"] == "active"
    assert (await client.patch(url, json={"commission_bps": 300}, headers=h)).status_code == 403
    root = await admin(client, db_session)
    assert (await client.patch(url, json={"commission_bps": 300}, headers=root)).json()[
        "commission_bps"
    ] == 300


async def test_scope_visibility_for_store_level_staff(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    s1, s2 = await make_store(db_session, mall, "s1"), await make_store(db_session, mall, "s2")
    other_mall = await make_mall(db_session, org, "other-mall")
    await make_staff(db_session, "cashier", [("store_staff", store_scope(s1))])
    h = await staff_headers(client, "cashier")

    assert (await client.get(f"/api/v1/stores/{s1.id}", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/malls/{mall.id}", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/orgs/{org.id}", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/stores/{s2.id}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/malls/{other_mall.id}", headers=h)).status_code == 404
    listed = await client.get(f"/api/v1/malls/{mall.id}/stores", headers=h)
    assert [s["slug"] for s in listed.json()] == ["s1"]
    assert [
        m["slug"] for m in (await client.get(f"/api/v1/orgs/{org.id}/malls", headers=h)).json()
    ] == [mall.slug]


async def test_suspended_org_blocks_its_own_staff_but_not_the_platform(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    root = await admin(client, db_session)
    owner = await staff_headers(client, "owner")

    assert (await client.post(f"/api/v1/orgs/{org.id}/suspend", headers=root)).json()[
        "status"
    ] == "suspended"
    blocked = await client.post(
        f"/api/v1/orgs/{org.id}/malls", json={"name": "M", "slug": "new-mall"}, headers=owner
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "suspended"
    assert (
        await client.patch(f"/api/v1/malls/{mall.id}", json={"name": "x"}, headers=owner)
    ).status_code == 409
    assert (
        await client.get(f"/api/v1/malls/{mall.id}", headers=owner)
    ).status_code == 200  # reads still work
    assert (
        await client.post(
            f"/api/v1/orgs/{org.id}/malls", json={"name": "M", "slug": "new-mall"}, headers=root
        )
    ).status_code == 201

    assert (await client.post(f"/api/v1/orgs/{org.id}/activate", headers=root)).json()[
        "status"
    ] == "active"
    assert (
        await client.patch(f"/api/v1/malls/{mall.id}", json={"name": "x"}, headers=owner)
    ).status_code == 200


async def test_suspended_mall_blocks_store_changes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    store = await make_store(db_session, mall)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    h = await staff_headers(client, "owner")
    assert (await client.post(f"/api/v1/malls/{mall.id}/suspend", headers=h)).status_code == 200
    r = await client.patch(f"/api/v1/stores/{store.id}", json={"name": "x"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "suspended"
    assert (await client.post(f"/api/v1/malls/{mall.id}/activate", headers=h)).status_code == 200


async def test_every_mutation_writes_exactly_one_audit_row_with_scope(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    h = await staff_headers(client, "owner")
    mall = (
        await client.post(
            f"/api/v1/orgs/{org.id}/malls", json={"name": "M", "slug": "mall-1"}, headers=h
        )
    ).json()
    await client.patch(f"/api/v1/malls/{mall['id']}", json={"name": "M2"}, headers=h)
    await client.post(f"/api/v1/malls/{mall['id']}/suspend", headers=h)

    rows = (
        (await db_session.execute(select(AuditLog).order_by(AuditLog.created_at, AuditLog.id)))
        .scalars()
        .all()
    )
    assert [r.action for r in rows] == ["mall.created", "mall.updated", "mall.suspended"]
    assert all(str(r.organization_id) == str(org.id) and str(r.mall_id) == mall["id"] for r in rows)
    assert rows[1].before == {"name": "M"} and rows[1].after == {"name": "M2"}
    n = (await db_session.execute(select(func.count()).select_from(Mall))).scalar_one()
    assert n == 1


# ---------- public mall page ----------


async def test_public_mall_page_lists_only_active_stores(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org, "phoenix-pune")
    mall.city = "Pune"
    live = await make_store(db_session, mall, "burger-hub")
    live.description = "Burgers"
    hidden = await make_store(db_session, mall, "closed-shop")
    hidden.status = ActiveStatus.SUSPENDED
    await db_session.flush()

    r = await client.get("/api/v1/public/malls/phoenix-pune")  # no auth
    assert r.status_code == 200
    assert r.json()["name"] == mall.name and r.json()["city"] == "Pune"
    assert r.json()["stores"] == [
        {"name": live.name, "slug": "burger-hub", "description": "Burgers"}
    ]
    assert "max-age" in r.headers["cache-control"]
    assert "organization_id" not in r.text and "commission" not in r.text


async def test_public_mall_page_hides_suspended_and_unknown(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org, "live-mall")
    dead = await make_mall(db_session, org, "dead-mall")
    dead.status = ActiveStatus.SUSPENDED
    await db_session.flush()
    assert (await client.get(f"/api/v1/public/malls/{mall.slug}")).status_code == 200
    assert (await client.get("/api/v1/public/malls/dead-mall")).status_code == 404
    assert (await client.get("/api/v1/public/malls/nope")).status_code == 404
    org.status = ActiveStatus.SUSPENDED
    await db_session.flush()
    assert (await client.get(f"/api/v1/public/malls/{mall.slug}")).status_code == 404
