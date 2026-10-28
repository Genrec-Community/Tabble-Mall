"""Test-only helpers that insert rows directly, bypassing services."""

from functools import cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus
from mallt.core.rbac import Scope
from mallt.core.security import hash_password
from mallt.modules.iam.models import Role, RoleAssignment, StaffUser
from mallt.modules.tenancy.models import Mall, Organization, Store

DEFAULT_PASSWORD = "Passw0rd!!"


@cache
def _default_hash() -> str:
    return hash_password(DEFAULT_PASSWORD)  # hashing is slow; do it once per test run


class MemoryKV:
    """In-memory KV that claims to be fast, so cache behaviour is testable without Redis."""

    fast = True

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def incr_window(self, key: str, window_s: int) -> tuple[int, int]:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key], window_s

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self.data[key] = value

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def ping(self) -> None:
        return None

    async def flush(self) -> None:
        self.data.clear()
        self.counters.clear()

    async def aclose(self) -> None:
        return None


async def make_org(
    session: AsyncSession, slug: str = "phoenix", name: str | None = None
) -> Organization:
    org = Organization(name=name or slug.title(), slug=slug)
    session.add(org)
    await session.flush()
    return org


async def make_mall(session: AsyncSession, org: Organization, slug: str = "phoenix-pune") -> Mall:
    mall = Mall(organization_id=org.id, name=slug.title(), slug=slug)
    session.add(mall)
    await session.flush()
    return mall


async def make_store(session: AsyncSession, mall: Mall, slug: str = "burger-hub") -> Store:
    store = Store(
        organization_id=mall.organization_id, mall_id=mall.id, name=slug.title(), slug=slug
    )
    session.add(store)
    await session.flush()
    return store


def store_scope(store: Store) -> Scope:
    return Scope.store(store.organization_id, store.mall_id, store.id)


async def grant(
    session: AsyncSession, staff: StaffUser, role_key: str, scope: Scope
) -> RoleAssignment:
    role = (await session.execute(select(Role).where(Role.key == role_key))).scalar_one()
    row = RoleAssignment(
        staff_user_id=staff.id,
        role_id=role.id,
        scope_type=scope.type,
        organization_id=scope.organization_id,
        mall_id=scope.mall_id,
        store_id=scope.store_id,
    )
    session.add(row)
    await session.flush()
    return row


async def make_staff(
    session: AsyncSession,
    username: str,
    roles: list[tuple[str, Scope]] | None = None,
    *,
    password_hash: str | None = None,
    must_change_password: bool = False,
    status: ActiveStatus = ActiveStatus.ACTIVE,
    totp_secret: str | None = None,
) -> StaffUser:
    staff = StaffUser(
        username=username,
        display_name=username.title(),
        password_hash=password_hash or _default_hash(),
        must_change_password=must_change_password,
        status=status,
        totp_secret=totp_secret,
        totp_enabled=totp_secret is not None,
    )
    session.add(staff)
    await session.flush()
    for role_key, scope in roles or []:
        await grant(session, staff, role_key, scope)
    return staff
