import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from mallt.core.config import Settings
from mallt.core.enums import ActiveStatus
from mallt.core.errors import Conflict
from mallt.core.rbac import Scope
from mallt.modules.iam.authz import AuthzService
from mallt.modules.iam.users import IamUsers
from mallt.modules.staff.service import StaffService
from tests.factories import MemoryKV, make_org, make_staff


async def test_two_owners_cannot_suspend_each_other_at_the_same_moment(
    db_engine: AsyncEngine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real, separate transactions: each one alone sees 'another active owner exists'.

    Each request is held open for a moment after it counts the other owners, so both counts
    happen before either commit unless the guard serialises them."""
    counted = IamUsers.other_active_owners

    async def count_then_linger(self: IamUsers, org_id: object, excluding: object) -> int:
        n = await counted(self, org_id, excluding)  # type: ignore[arg-type]
        await asyncio.sleep(0.3)
        return n

    monkeypatch.setattr(IamUsers, "other_active_owners", count_then_linger)
    async with AsyncSession(db_engine, expire_on_commit=False) as s:
        org = await make_org(s, "race-org")
        a = await make_staff(s, "race.a", [("org_owner", Scope.org(org.id))])
        b = await make_staff(s, "race.b", [("org_owner", Scope.org(org.id))])
        root = await make_staff(s, "race.root", [("platform_admin", Scope.platform())])
        await s.commit()
    ids = {"org": org.id, "a": a.id, "b": b.id, "root": root.id}
    kv = MemoryKV()

    async def suspend(target_id: object) -> str:
        async with AsyncSession(db_engine, expire_on_commit=False) as session:
            principal = await AuthzService(session, kv).load_principal(ids["root"])
            try:
                await StaffService(session, settings, kv).set_status(
                    principal,
                    target_id,
                    ActiveStatus.SUSPENDED,  # type: ignore[arg-type]
                )
                await session.commit()
                return "ok"
            except Conflict as exc:
                await session.rollback()
                return exc.code

    try:
        results = await asyncio.gather(suspend(ids["a"]), suspend(ids["b"]))
        assert sorted(results) == ["last_owner", "ok"]
    finally:
        async with db_engine.begin() as conn:
            people = [ids["a"], ids["b"], ids["root"]]
            await conn.execute(
                text("DELETE FROM audit_logs WHERE organization_id = :o OR actor_id = ANY(:p)"),
                {"o": ids["org"], "p": people},
            )
            await conn.execute(
                text("DELETE FROM refresh_tokens WHERE subject_id = ANY(:p)"), {"p": people}
            )
            await conn.execute(
                text("DELETE FROM role_assignments WHERE staff_user_id = ANY(:p)"), {"p": people}
            )
            await conn.execute(text("DELETE FROM staff_users WHERE id = ANY(:p)"), {"p": people})
            await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": ids["org"]})
