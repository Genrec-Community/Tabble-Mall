import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.rbac import Scope
from mallt.core.security import new_totp_secret
from mallt.modules.audit.models import AuditLog
from mallt.modules.tenancy.models import Organization
from tests.factories import make_mall, make_org, make_staff, make_store, store_scope
from tests.helpers import staff_headers

T0 = datetime(2026, 1, 1, tzinfo=UTC)


async def log(
    db: AsyncSession,
    org: Organization | None,
    n: int,
    *,
    actor_id: uuid.UUID | None = None,
    actor_type: ActorType = ActorType.STAFF,
    action: str | None = None,
) -> AuditLog:
    """Insert one audit row; row n happened n minutes after T0."""
    row = AuditLog(
        created_at=T0 + timedelta(minutes=n),
        actor_type=actor_type,
        actor_id=actor_id,
        action=action or f"thing.{n}",
        target_type="thing",
        target_id=uuid.uuid4(),
        organization_id=org.id if org else None,
        before={"n": n - 1},
        after={"n": n},
    )
    db.add(row)
    await db.flush()
    return row


async def admin(client: httpx.AsyncClient, db: AsyncSession) -> dict[str, str]:
    secret = new_totp_secret()
    await make_staff(db, "root", [("platform_admin", Scope.platform())], totp_secret=secret)
    return await staff_headers(client, "root", totp_secret=secret)


async def test_org_owner_reads_only_their_orgs_log_newest_first(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await make_org(db_session, "org-a"), await make_org(db_session, "org-b")
    owner = await make_staff(db_session, "owner", [("org_owner", Scope.org(a.id))])
    for n in (1, 3, 2):
        await log(db_session, a, n, actor_id=owner.id)
    await log(db_session, b, 9)
    await log(db_session, None, 10)

    r = await client.get(f"/api/v1/orgs/{a.id}/audit", headers=await staff_headers(client, "owner"))
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["action"] for i in items] == ["thing.3", "thing.2", "thing.1"]
    assert items[0]["actor_username"] == "owner" and items[0]["actor_type"] == "staff"
    assert items[0]["before"] == {"n": 2} and items[0]["after"] == {"n": 3}
    assert r.json()["next_cursor"] is None


async def test_cross_org_and_missing_permission(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await make_org(db_session, "org-a"), await make_org(db_session, "org-b")
    mall = await make_mall(db_session, a)
    store = await make_store(db_session, mall)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(a.id))])
    await make_staff(db_session, "manager", [("org_manager", Scope.org(a.id))])
    await make_staff(db_session, "so", [("store_owner", store_scope(store))])

    owner = await staff_headers(client, "owner")
    assert (await client.get(f"/api/v1/orgs/{b.id}/audit", headers=owner)).status_code == 404
    assert (
        await client.get(f"/api/v1/orgs/{uuid.uuid4()}/audit", headers=owner)
    ).status_code == 404
    for who in ("manager", "so"):
        r = await client.get(f"/api/v1/orgs/{a.id}/audit", headers=await staff_headers(client, who))
        assert r.status_code == 403, who
    assert (await client.get(f"/api/v1/orgs/{a.id}/audit")).status_code == 401


async def test_pagination_covers_everything_without_overlap(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    for n in range(1, 8):
        await log(db_session, org, n)
    h = await staff_headers(client, "owner")

    seen: list[str] = []
    cursor = ""
    for _ in range(5):
        r = await client.get(f"/api/v1/orgs/{org.id}/audit?limit=3{cursor}", headers=h)
        body = r.json()
        seen += [i["action"] for i in body["items"]]
        if not body["next_cursor"]:
            break
        cursor = f"&cursor={body['next_cursor']}"
    assert seen == [f"thing.{n}" for n in range(7, 0, -1)]


async def test_rows_with_identical_timestamps_still_page_cleanly(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    for i in range(5):
        row = await log(db_session, org, 1, action=f"same.{i}")  # all at the same instant
        assert row.created_at == T0 + timedelta(minutes=1)
    h = await staff_headers(client, "owner")
    first = (await client.get(f"/api/v1/orgs/{org.id}/audit?limit=2", headers=h)).json()
    second = (
        await client.get(
            f"/api/v1/orgs/{org.id}/audit?limit=2&cursor={first['next_cursor']}", headers=h
        )
    ).json()
    third = (
        await client.get(
            f"/api/v1/orgs/{org.id}/audit?limit=2&cursor={second['next_cursor']}", headers=h
        )
    ).json()
    ids = [i["id"] for p in (first, second, third) for i in p["items"]]
    assert len(ids) == 5 and len(set(ids)) == 5 and third["next_cursor"] is None


async def test_bad_cursor_and_limits_are_422(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    h = await staff_headers(client, "owner")
    base = f"/api/v1/orgs/{org.id}/audit"
    for query in ("?cursor=garbage", "?cursor=", "?limit=0", "?limit=101"):
        assert (await client.get(base + query, headers=h)).status_code == 422, query


async def test_platform_admin_reads_everything_and_can_filter(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await make_org(db_session, "org-a"), await make_org(db_session, "org-b")
    await log(db_session, a, 1)
    await log(db_session, b, 2)
    await log(db_session, None, 3, actor_type=ActorType.SYSTEM)
    h = await admin(client, db_session)

    everything = (await client.get("/api/v1/admin/audit", headers=h)).json()["items"]
    assert [i["action"] for i in everything] == ["thing.3", "thing.2", "thing.1"]
    assert everything[0]["actor_type"] == "system" and everything[0]["actor_username"] is None
    only_b = (await client.get(f"/api/v1/admin/audit?organization_id={b.id}", headers=h)).json()[
        "items"
    ]
    assert [i["action"] for i in only_b] == ["thing.2"]


async def test_global_audit_is_platform_only(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    r = await client.get("/api/v1/admin/audit", headers=await staff_headers(client, "owner"))
    assert r.status_code == 403
