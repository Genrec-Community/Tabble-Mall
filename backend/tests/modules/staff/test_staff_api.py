from dataclasses import dataclass

import httpx
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus
from mallt.core.rbac import Scope
from mallt.core.security import new_totp_secret
from mallt.modules.audit.models import AuditLog
from mallt.modules.iam.authz import AuthzService
from mallt.modules.iam.models import StaffUser
from mallt.modules.tenancy.models import Mall, Organization, Store
from tests.factories import (
    DEFAULT_PASSWORD,
    make_mall,
    make_org,
    make_staff,
    make_store,
    store_scope,
)
from tests.helpers import staff_headers

STAFF_API = "/api/v1/auth/staff"


@dataclass
class World:
    org: Organization
    mall: Mall
    s1: Store
    s2: Store


async def world(db: AsyncSession) -> World:
    """Org with one mall and two stores; staff: owner, manager, so1 (store owner of s1), cashier."""
    org = await make_org(db, "org-a")
    mall = await make_mall(db, org, "mall-a")
    s1, s2 = await make_store(db, mall, "s1"), await make_store(db, mall, "s2")
    await make_staff(db, "owner", [("org_owner", Scope.org(org.id))])
    await make_staff(db, "manager", [("org_manager", Scope.org(org.id))])
    await make_staff(db, "so1", [("store_owner", store_scope(s1))])
    await make_staff(db, "cashier", [("store_staff", store_scope(s1))])
    return World(org, mall, s1, s2)


async def as_(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    return await staff_headers(client, username)


async def actions(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(AuditLog.action).order_by(AuditLog.created_at, AuditLog.id))
    return list(rows.scalars())


def new_staff(username: str, role_key: str) -> dict[str, str]:
    return {"username": username, "display_name": username.title(), "role_key": role_key}


async def staff_id(db: AsyncSession, username: str) -> str:
    row = await db.execute(select(StaffUser.id).where(StaffUser.username == username))
    return str(row.scalar_one())


# ---------- creating staff ----------


async def test_org_owner_creates_a_store_owner_whose_temp_password_works(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    r = await client.post(
        f"/api/v1/stores/{w.s2.id}/staff",
        json=new_staff("so2", "store_owner"),
        headers=await as_(client, "owner"),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["staff"]["username"] == "so2" and body["staff"]["must_change_password"] is True
    assert [g["role_key"] for g in body["staff"]["grants"]] == ["store_owner"]
    login = await client.post(
        f"{STAFF_API}/login", json={"username": "so2", "password": body["temp_password"]}
    )
    assert login.status_code == 200
    assert await actions(db_session) == ["staff.created"]


async def test_store_owner_builds_their_own_team_only(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    h = await as_(client, "so1")
    own = await client.post(
        f"/api/v1/stores/{w.s1.id}/staff", json=new_staff("cashier2", "store_staff"), headers=h
    )
    assert own.status_code == 201
    other_store = await client.post(
        f"/api/v1/stores/{w.s2.id}/staff", json=new_staff("so3", "store_owner"), headers=h
    )
    assert other_store.status_code == 403
    co_owner = await client.post(
        f"/api/v1/stores/{w.s1.id}/staff", json=new_staff("so1b", "store_owner"), headers=h
    )
    assert co_owner.status_code == 201  # co-owners are allowed
    no_org_roles = await client.post(
        f"/api/v1/stores/{w.s1.id}/staff", json=new_staff("xray1", "org_manager"), headers=h
    )
    assert no_org_roles.status_code == 422 and no_org_roles.json()["code"] == "wrong_scope"


async def test_store_staff_cannot_manage_staff(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    h = await as_(client, "cashier")
    r = await client.post(
        f"/api/v1/stores/{w.s1.id}/staff", json=new_staff("cashier3", "store_staff"), headers=h
    )
    assert r.status_code == 403
    assert (await client.get(f"/api/v1/stores/{w.s1.id}/staff", headers=h)).status_code == 403


async def test_org_manager_cannot_mint_owners_or_managers(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    h = await as_(client, "manager")
    for role in ("org_owner", "org_manager"):
        r = await client.post(
            f"/api/v1/orgs/{w.org.id}/staff", json=new_staff(f"x-{role}", role), headers=h
        )
        assert r.status_code == 403 and r.json()["code"] == "cannot_grant_role", role
    # Store owners can submit KYC (bank details); managers can't, so they can't mint one either.
    no_owner = await client.post(
        f"/api/v1/stores/{w.s1.id}/staff", json=new_staff("so9", "store_owner"), headers=h
    )
    assert no_owner.status_code == 403 and no_owner.json()["code"] == "cannot_grant_role"
    ok = await client.post(
        f"/api/v1/stores/{w.s1.id}/staff", json=new_staff("clerk9", "store_staff"), headers=h
    )
    assert ok.status_code == 201
    assert (
        await client.post(
            f"/api/v1/orgs/{w.org.id}/staff",
            json=new_staff("owner.two", "org_owner"),
            headers=await as_(client, "owner"),
        )
    ).status_code == 201


async def test_cross_org_staff_calls_are_404(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    org_b = await make_org(db_session, "org-b")
    mall_b = await make_mall(db_session, org_b, "mall-b")
    store_b = await make_store(db_session, mall_b, "store-b")
    await make_staff(db_session, "owner-b", [("org_owner", Scope.org(org_b.id))])
    b_id = await staff_id(db_session, "owner-b")
    h = await as_(client, "owner")

    for method, url, body in (
        ("get", f"/api/v1/orgs/{org_b.id}/staff", None),
        ("post", f"/api/v1/orgs/{org_b.id}/staff", new_staff("zed", "org_manager")),
        ("post", f"/api/v1/stores/{store_b.id}/staff", new_staff("zed", "store_staff")),
        (
            "post",
            f"/api/v1/staff/{b_id}/roles",
            {"role_key": "org_manager", "scope_type": "organization", "scope_id": str(w.org.id)},
        ),
        ("post", f"/api/v1/staff/{b_id}/suspend", None),
        ("post", f"/api/v1/staff/{b_id}/activate", None),
        ("post", f"/api/v1/staff/{b_id}/reset-password", None),
    ):
        r = await client.request(method, url, json=body, headers=h)
        assert r.status_code == 404, (method, url, r.status_code)
    # And assigning a role *in* org B is a 404 as well, even for a user of org A.
    mine = await staff_id(db_session, "cashier")
    r = await client.post(
        f"/api/v1/staff/{mine}/roles",
        json={"role_key": "org_manager", "scope_type": "organization", "scope_id": str(org_b.id)},
        headers=h,
    )
    assert r.status_code == 404


async def test_usernames_are_unique_ignoring_case_and_validated(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    await make_staff(db_session, "ravi.k")
    h = await as_(client, "owner")
    dup = await client.post(
        f"/api/v1/orgs/{w.org.id}/staff", json=new_staff("Ravi.K", "org_manager"), headers=h
    )
    assert dup.status_code == 409 and dup.json()["code"] == "username_taken"
    bad = await client.post(
        f"/api/v1/orgs/{w.org.id}/staff", json=new_staff("a b", "org_manager"), headers=h
    )
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_username"
    assert await actions(db_session) == []


async def test_creating_staff_under_a_suspended_org_is_blocked_for_tenants(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    w.org.status = ActiveStatus.SUSPENDED
    await db_session.flush()
    r = await client.post(
        f"/api/v1/stores/{w.s1.id}/staff",
        json=new_staff("cashier9", "store_staff"),
        headers=await as_(client, "so1"),
    )
    assert r.status_code == 409 and r.json()["code"] == "suspended"


# ---------- listing ----------


async def test_staff_lists_are_scoped(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    w = await world(db_session)
    at_store = await client.get(f"/api/v1/stores/{w.s1.id}/staff", headers=await as_(client, "so1"))
    assert sorted(s["username"] for s in at_store.json()) == ["cashier", "so1"]
    at_org = await client.get(f"/api/v1/orgs/{w.org.id}/staff", headers=await as_(client, "owner"))
    assert sorted(s["username"] for s in at_org.json()) == ["cashier", "manager", "owner", "so1"]
    other_store = await client.get(
        f"/api/v1/stores/{w.s2.id}/staff", headers=await as_(client, "so1")
    )
    assert other_store.status_code == 403
    assert (
        await client.get(f"/api/v1/orgs/{w.org.id}/staff", headers=await as_(client, "so1"))
    ).status_code == 403


async def test_roles_endpoint_lists_the_system_roles(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await world(db_session)
    r = await client.get("/api/v1/roles", headers=await as_(client, "cashier"))
    assert r.status_code == 200
    roles = {x["key"]: x for x in r.json()}
    assert set(roles) == {
        "platform_admin",
        "org_owner",
        "org_manager",
        "store_owner",
        "store_staff",
    }
    assert roles["store_staff"]["scope_type"] == "store"
    assert "store.order.update" in roles["store_staff"]["permissions"]
    # The UI uses this to hide roles the viewer cannot hand out (same rule the API enforces).
    assert roles["org_owner"]["grantable_by"] == ["org_owner", "platform_admin"]
    assert set(roles["store_staff"]["grantable_by"]) == {
        "platform_admin",
        "org_owner",
        "org_manager",
        "store_owner",
    }


# ---------- role assignment ----------


async def test_assign_and_revoke_roles(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    w = await world(db_session)
    h = await as_(client, "owner")
    cashier = await staff_id(db_session, "cashier")

    grant = await client.post(
        f"/api/v1/staff/{cashier}/roles",
        json={"role_key": "store_staff", "scope_type": "store", "scope_id": str(w.s2.id)},
        headers=h,
    )
    assert grant.status_code == 201 and grant.json()["store_id"] == str(w.s2.id)
    dup = await client.post(
        f"/api/v1/staff/{cashier}/roles",
        json={"role_key": "store_staff", "scope_type": "store", "scope_id": str(w.s2.id)},
        headers=h,
    )
    assert dup.status_code == 409 and dup.json()["code"] == "role_already_assigned"
    wrong = await client.post(
        f"/api/v1/staff/{cashier}/roles",
        json={"role_key": "store_staff", "scope_type": "organization", "scope_id": str(w.org.id)},
        headers=h,
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "wrong_scope"

    assert (
        await client.delete(f"/api/v1/staff/{cashier}/roles/{grant.json()['id']}", headers=h)
    ).status_code == 204
    assert (
        await client.delete(f"/api/v1/staff/{cashier}/roles/{grant.json()['id']}", headers=h)
    ).status_code == 404
    assert await actions(db_session) == ["staff.role_granted", "staff.role_revoked"]


async def test_role_changes_take_effect_on_the_next_request(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    cashier = await as_(client, "cashier")
    assert (await client.get(f"/api/v1/stores/{w.s2.id}", headers=cashier)).status_code == 404
    cashier_id = await staff_id(db_session, "cashier")
    r = await client.post(
        f"/api/v1/staff/{cashier_id}/roles",
        json={"role_key": "store_staff", "scope_type": "store", "scope_id": str(w.s2.id)},
        headers=await as_(client, "owner"),
    )
    assert r.status_code == 201
    assert (
        await client.get(f"/api/v1/stores/{w.s2.id}", headers=cashier)
    ).status_code == 200  # same token


# ---------- managing existing staff ----------


async def test_suspend_locks_the_user_out_immediately_and_activate_restores(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await world(db_session)
    victim_login = await client.post(
        f"{STAFF_API}/login", json={"username": "cashier", "password": DEFAULT_PASSWORD}
    )
    victim = {"Authorization": f"Bearer {victim_login.json()['access_token']}"}
    assert (await client.get(f"{STAFF_API}/me", headers=victim)).status_code == 200

    cid = await staff_id(db_session, "cashier")
    boss = await as_(client, "so1")
    assert (await client.post(f"/api/v1/staff/{cid}/suspend", headers=boss)).json()[
        "status"
    ] == "suspended"
    assert (await client.get(f"{STAFF_API}/me", headers=victim)).status_code == 401
    assert (
        await client.post(
            f"{STAFF_API}/login", json={"username": "cashier", "password": DEFAULT_PASSWORD}
        )
    ).status_code == 401

    assert (await client.post(f"/api/v1/staff/{cid}/activate", headers=boss)).json()[
        "status"
    ] == "active"
    assert (
        await client.post(
            f"{STAFF_API}/login", json={"username": "cashier", "password": DEFAULT_PASSWORD}
        )
    ).status_code == 200
    assert await actions(db_session) == ["staff.suspended", "staff.activated"]


async def test_you_can_only_manage_people_you_could_have_created(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await world(db_session)
    owner_id, manager_id = (
        await staff_id(db_session, "owner"),
        await staff_id(db_session, "manager"),
    )
    so1 = await as_(client, "so1")
    # A store owner can't touch an org manager; an org manager can't touch the owner.
    assert (
        await client.post(f"/api/v1/staff/{manager_id}/suspend", headers=so1)
    ).status_code == 403
    mgr = await as_(client, "manager")
    assert (await client.post(f"/api/v1/staff/{owner_id}/suspend", headers=mgr)).status_code == 403
    assert (
        await client.post(f"/api/v1/staff/{owner_id}/reset-password", headers=mgr)
    ).status_code == 403


async def test_nobody_manages_themselves_through_these_endpoints(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await world(db_session)
    me = await staff_id(db_session, "so1")
    h = await as_(client, "so1")
    for action in ("suspend", "reset-password"):
        r = await client.post(f"/api/v1/staff/{me}/{action}", headers=h)
        assert r.status_code == 409 and r.json()["code"] == "self_action", action


async def test_reset_password_ends_their_sessions_and_forces_a_change(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await world(db_session)
    old = await client.post(
        f"{STAFF_API}/login", json={"username": "cashier", "password": DEFAULT_PASSWORD}
    )
    old_h = {"Authorization": f"Bearer {old.json()['access_token']}"}
    cid = await staff_id(db_session, "cashier")

    r = await client.post(f"/api/v1/staff/{cid}/reset-password", headers=await as_(client, "so1"))
    assert r.status_code == 200 and len(r.json()["temp_password"]) >= 16
    assert (await client.get(f"{STAFF_API}/me", headers=old_h)).status_code == 401
    assert (
        await client.post(
            f"{STAFF_API}/login", json={"username": "cashier", "password": DEFAULT_PASSWORD}
        )
    ).status_code == 401
    fresh = await client.post(
        f"{STAFF_API}/login", json={"username": "cashier", "password": r.json()["temp_password"]}
    )
    assert fresh.status_code == 200
    me = await client.get(
        f"{STAFF_API}/me", headers={"Authorization": f"Bearer {fresh.json()['access_token']}"}
    )
    assert me.json()["must_change_password"] is True
    assert await actions(db_session) == ["staff.password_reset"]


async def test_an_org_can_never_lose_its_last_owner(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    owner_id = await staff_id(db_session, "owner")
    root_secret = new_totp_secret()
    await make_staff(
        db_session, "root", [("platform_admin", Scope.platform())], totp_secret=root_secret
    )
    root = await staff_headers(client, "root", totp_secret=root_secret)
    detail = (await client.get(f"/api/v1/orgs/{w.org.id}/staff", headers=root)).json()
    (owner_row,) = [s for s in detail if s["username"] == "owner"]
    assignment = owner_row["grants"][0]["id"]

    refused = await client.delete(f"/api/v1/staff/{owner_id}/roles/{assignment}", headers=root)
    assert refused.status_code == 409 and refused.json()["code"] == "last_owner"
    assert (await client.post(f"/api/v1/staff/{owner_id}/suspend", headers=root)).json()[
        "code"
    ] == "last_owner"

    second = await client.post(
        f"/api/v1/orgs/{w.org.id}/staff", json=new_staff("owner2", "org_owner"), headers=root
    )
    assert second.status_code == 201
    assert (
        await client.delete(f"/api/v1/staff/{owner_id}/roles/{assignment}", headers=root)
    ).status_code == 204


async def test_suspended_co_owner_does_not_count_as_a_remaining_owner(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    await make_staff(
        db_session, "owner2", [("org_owner", Scope.org(w.org.id))], status=ActiveStatus.SUSPENDED
    )
    owner_id = await staff_id(db_session, "owner")
    root_secret = new_totp_secret()
    await make_staff(
        db_session, "root", [("platform_admin", Scope.platform())], totp_secret=root_secret
    )
    root = await staff_headers(client, "root", totp_secret=root_secret)
    r = await client.post(f"/api/v1/staff/{owner_id}/suspend", headers=root)
    assert r.status_code == 409 and r.json()["code"] == "last_owner"
    await db_session.execute(
        update(StaffUser).where(StaffUser.username == "owner2").values(status=ActiveStatus.ACTIVE)
    )
    # The raw UPDATE above bypassed the service, so drop the cached principal ourselves.
    await AuthzService(db_session, app.state.kv).invalidate(owner_id)
    assert (await client.post(f"/api/v1/staff/{owner_id}/suspend", headers=root)).status_code == 200


async def test_staff_endpoints_require_a_signed_in_staff_member(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    assert (await client.get(f"/api/v1/stores/{w.s1.id}/staff")).status_code == 401
    assert (await client.get("/api/v1/roles")).status_code == 401


async def test_platform_admin_role_needs_an_authenticator_enrolled_first(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Platform admins cannot sign in without TOTP, so promoting someone who has none would lock
    them out for good."""
    secret = new_totp_secret()
    await make_staff(db_session, "root", [("platform_admin", Scope.platform())], totp_secret=secret)
    target = await make_staff(db_session, "future.admin")
    h = await staff_headers(client, "root", totp_secret=secret)
    url = f"/api/v1/staff/{target.id}/roles"
    body = {"role_key": "platform_admin", "scope_type": "platform"}

    refused = await client.post(url, json=body, headers=h)
    assert refused.status_code == 409 and refused.json()["code"] == "totp_required_first"

    target.totp_secret, target.totp_enabled = new_totp_secret(), True
    await db_session.flush()
    assert (await client.post(url, json=body, headers=h)).status_code == 201


async def test_tenant_staff_cannot_probe_for_platform_admins(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await world(db_session)
    root = await make_staff(db_session, "root", [("platform_admin", Scope.platform())])
    owner = await as_(client, "owner")
    for action in ("suspend", "activate", "reset-password"):
        r = await client.post(f"/api/v1/staff/{root.id}/{action}", headers=owner)
        assert r.status_code == 404, action  # indistinguishable from an id that does not exist


async def test_a_suspended_org_cannot_change_its_staff(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    w = await world(db_session)
    owner = await as_(client, "owner")
    cashier = await staff_id(db_session, "cashier")
    assignment = (await client.get(f"/api/v1/stores/{w.s1.id}/staff", headers=owner)).json()
    (row,) = [x for x in assignment if x["username"] == "cashier"]
    w.org.status = ActiveStatus.SUSPENDED
    await db_session.flush()

    for call in (
        client.post(f"/api/v1/staff/{cashier}/suspend", headers=owner),
        client.post(f"/api/v1/staff/{cashier}/reset-password", headers=owner),
        client.delete(f"/api/v1/staff/{cashier}/roles/{row['grants'][0]['id']}", headers=owner),
    ):
        r = await call
        assert r.status_code == 409 and r.json()["code"] == "suspended"
