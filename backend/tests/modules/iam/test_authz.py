import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.db import run_after_commit
from mallt.core.enums import ActiveStatus
from mallt.core.errors import Forbidden, NotFound, Unauthorized
from mallt.core.ids import uuid7
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope
from mallt.modules.iam.authz import AuthzService
from mallt.modules.iam.models import RoleAssignment, StaffUser
from tests.factories import (
    MemoryKV,
    grant,
    make_mall,
    make_org,
    make_staff,
    make_store,
    store_scope,
)


@pytest.fixture
def kv() -> KV:
    return MemoryKV()


async def test_store_staff_can_update_order_in_own_store_only(
    db_session: AsyncSession, kv: KV
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    s1, s2 = await make_store(db_session, mall, "s1"), await make_store(db_session, mall, "s2")
    staff = await make_staff(db_session, "cashier", [("store_staff", store_scope(s1))])
    authz = AuthzService(db_session, kv)
    p = await authz.load_principal(staff.id)

    assert authz.can(p, P.STORE_ORDER_UPDATE, store_scope(s1))
    assert not authz.can(p, P.STORE_ORDER_UPDATE, store_scope(s2))
    assert not authz.can(p, P.STORE_PRODUCT_WRITE, store_scope(s1))


async def test_org_owner_inherits_down_to_store(db_session: AsyncSession, kv: KV) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    store = await make_store(db_session, mall)
    owner = await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    authz = AuthzService(db_session, kv)
    p = await authz.load_principal(owner.id)

    assert authz.can(p, P.STORE_PRODUCT_WRITE, store_scope(store))
    assert authz.can(p, P.ORG_BILLING_MANAGE, Scope.org(org.id))
    assert not authz.can(p, P.PLATFORM_ORG_MANAGE, Scope.platform())


async def test_require_cross_org_is_404_same_org_is_403(db_session: AsyncSession, kv: KV) -> None:
    org_a, org_b = await make_org(db_session, "a"), await make_org(db_session, "b")
    mall_a, mall_b = (
        await make_mall(db_session, org_a, "mall-a"),
        await make_mall(db_session, org_b, "mall-b"),
    )
    store_a, store_b = await make_store(db_session, mall_a), await make_store(db_session, mall_b)
    staff = await make_staff(db_session, "cashier", [("store_staff", store_scope(store_a))])
    authz = AuthzService(db_session, kv)
    p = await authz.load_principal(staff.id)

    authz.require(p, P.STORE_ORDER_UPDATE, store_scope(store_a))  # allowed: no raise
    with pytest.raises(Forbidden) as same_org:
        authz.require(p, P.STORE_PRODUCT_WRITE, store_scope(store_a))
    assert same_org.value.code == "missing_permission"
    with pytest.raises(NotFound):
        authz.require(p, P.STORE_ORDER_UPDATE, store_scope(store_b))
    with pytest.raises(Forbidden):  # platform-level action: nothing to hide, so 403
        authz.require(p, P.PLATFORM_ORG_MANAGE, Scope.platform())


async def test_platform_admin_sees_every_org(db_session: AsyncSession, kv: KV) -> None:
    org = await make_org(db_session)
    admin = await make_staff(db_session, "root", [("platform_admin", Scope.platform())])
    authz = AuthzService(db_session, kv)
    p = await authz.load_principal(admin.id)

    authz.require(p, P.ORG_SETTINGS_UPDATE, Scope.org(org.id))
    assert authz.visible_org_ids(p) is None


async def test_visible_org_ids_for_org_scoped_staff(db_session: AsyncSession, kv: KV) -> None:
    org_a, org_b = await make_org(db_session, "a"), await make_org(db_session, "b")
    staff = await make_staff(
        db_session,
        "multi",
        [("org_manager", Scope.org(org_a.id)), ("org_manager", Scope.org(org_b.id))],
    )
    p = await AuthzService(db_session, kv).load_principal(staff.id)
    assert AuthzService(db_session, kv).visible_org_ids(p) == {org_a.id, org_b.id}


async def test_principal_cached_and_invalidated(db_session: AsyncSession, kv: KV) -> None:
    org = await make_org(db_session)
    owner = await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    authz = AuthzService(db_session, kv)
    assert len((await authz.load_principal(owner.id)).grants) == 1

    await db_session.execute(delete(RoleAssignment).where(RoleAssignment.staff_user_id == owner.id))
    assert len((await authz.load_principal(owner.id)).grants) == 1  # still served from cache

    await authz.invalidate(owner.id)
    assert (await authz.load_principal(owner.id)).grants == ()


async def test_no_cache_when_kv_is_not_fast(db_session: AsyncSession) -> None:
    class SlowKV(MemoryKV):
        fast = False

    org = await make_org(db_session)
    owner = await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    authz = AuthzService(db_session, SlowKV())
    assert len((await authz.load_principal(owner.id)).grants) == 1
    await db_session.execute(delete(RoleAssignment).where(RoleAssignment.staff_user_id == owner.id))
    assert (await authz.load_principal(owner.id)).grants == ()  # no stale permissions


async def test_suspended_staff_rejected_even_when_previously_cached(
    db_session: AsyncSession, kv: KV
) -> None:
    org = await make_org(db_session)
    owner = await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    authz = AuthzService(db_session, kv)
    await authz.load_principal(owner.id)  # warm the cache

    await db_session.execute(
        update(StaffUser).where(StaffUser.id == owner.id).values(status=ActiveStatus.SUSPENDED)
    )
    await authz.invalidate(owner.id)
    with pytest.raises(Unauthorized) as e:
        await authz.load_principal(owner.id)
    assert e.value.code == "account_suspended"


async def test_unknown_staff_is_unauthorized(db_session: AsyncSession, kv: KV) -> None:
    with pytest.raises(Unauthorized) as e:
        await AuthzService(db_session, kv).load_principal(uuid7())
    assert e.value.code == "invalid_token"


async def test_principal_reports_must_change_password(db_session: AsyncSession, kv: KV) -> None:
    staff = await make_staff(db_session, "fresh", must_change_password=True)
    p = await AuthzService(db_session, kv).load_principal(staff.id)
    assert p.must_change_password and p.grants == ()
    assert (await db_session.execute(select(StaffUser.id).where(StaffUser.id == staff.id))).one()


async def test_extra_grant_is_picked_up_after_invalidate(db_session: AsyncSession, kv: KV) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    store = await make_store(db_session, mall)
    staff = await make_staff(db_session, "s", [("store_staff", store_scope(store))])
    authz = AuthzService(db_session, kv)
    assert not authz.can(
        await authz.load_principal(staff.id), P.STORE_PRODUCT_WRITE, store_scope(store)
    )
    await grant(db_session, staff, "store_owner", store_scope(store))
    await authz.invalidate(staff.id)
    assert authz.can(
        await authz.load_principal(staff.id), P.STORE_PRODUCT_WRITE, store_scope(store)
    )


async def test_invalidate_clears_again_after_commit(db_session: AsyncSession, kv: KV) -> None:
    """A request that raced the change can re-cache the OLD permissions before the commit lands;
    invalidation must therefore also run once the transaction has committed."""
    org = await make_org(db_session)
    owner = await make_staff(db_session, "owner", [("org_owner", Scope.org(org.id))])
    authz = AuthzService(db_session, kv)
    key = f"authz:staff:{owner.id}"

    await authz.invalidate(owner.id)
    assert await kv.get(key) is None
    await kv.set(key, "stale-principal-cached-by-a-racing-request", 60)

    await run_after_commit(db_session)  # what get_session does right after commit()
    assert await kv.get(key) is None
