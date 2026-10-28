import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import IdentityKind
from mallt.core.rbac import ScopeType
from mallt.modules.iam.models import (
    RefreshToken,
    Role,
    RoleAssignment,
    RolePermission,
    StaffUser,
)


@dataclass(frozen=True)
class GrantRow:
    assignment_id: uuid.UUID
    role_key: str
    scope_type: ScopeType
    organization_id: uuid.UUID | None
    mall_id: uuid.UUID | None
    store_id: uuid.UUID | None
    permissions: frozenset[str]


class IamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_staff(self, staff_id: uuid.UUID) -> StaffUser | None:
        return await self.session.get(StaffUser, staff_id)

    def add(self, obj: StaffUser | RoleAssignment) -> None:
        self.session.add(obj)

    async def get_role_by_key(self, key: str) -> Role | None:
        return (
            await self.session.execute(select(Role).where(Role.key == key))
        ).scalar_one_or_none()

    async def get_staff_by_username(self, username: str) -> StaffUser | None:
        stmt = select(StaffUser).where(StaffUser.username == username)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def has_scope_type(self, staff_id: uuid.UUID, scope_type: ScopeType) -> bool:
        stmt = (
            select(RoleAssignment.id)
            .where(
                RoleAssignment.staff_user_id == staff_id, RoleAssignment.scope_type == scope_type
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def grants_for(self, staff_id: uuid.UUID) -> list[GrantRow]:
        """Every role assignment of a staff user with the role's permissions, in one query."""
        stmt = (
            select(
                RoleAssignment.id,
                Role.key,
                RoleAssignment.scope_type,
                RoleAssignment.organization_id,
                RoleAssignment.mall_id,
                RoleAssignment.store_id,
                RolePermission.permission,
            )
            .join(Role, Role.id == RoleAssignment.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .where(RoleAssignment.staff_user_id == staff_id)
            .order_by(RoleAssignment.created_at, RoleAssignment.id)
        )
        heads: dict[
            uuid.UUID, tuple[str, ScopeType, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]
        ] = {}
        perms: dict[uuid.UUID, set[str]] = {}
        for aid, key, scope_type, org, mall, store, permission in (
            await self.session.execute(stmt)
        ).all():
            heads.setdefault(aid, (key, scope_type, org, mall, store))
            perms.setdefault(aid, set()).add(permission)
        return [GrantRow(aid, *head, frozenset(perms[aid])) for aid, head in heads.items()]


class SessionRepository:
    """Refresh-token rows. One 'family' is one login session; rotation chains tokens in it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, token: RefreshToken) -> None:
        self.session.add(token)

    async def by_hash(self, token_hash: str) -> RefreshToken | None:
        # FOR UPDATE serialises two concurrent refreshes of the same token: the second then
        # sees it as already rotated instead of both succeeding and forking the family.
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def live_families(
        self, kind: IdentityKind, subject_id: uuid.UUID, now: datetime
    ) -> list[uuid.UUID]:
        stmt = (
            select(RefreshToken.family_id)
            .where(
                RefreshToken.identity_type == kind,
                RefreshToken.subject_id == subject_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .distinct()
        )
        return list((await self.session.execute(stmt)).scalars())

    async def family_is_active(self, family_id: uuid.UUID, now: datetime) -> bool:
        stmt = (
            select(RefreshToken.id)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def live_tokens(
        self, kind: IdentityKind, subject_id: uuid.UUID, now: datetime
    ) -> list[RefreshToken]:
        stmt = (
            select(RefreshToken)
            .where(
                RefreshToken.identity_type == kind,
                RefreshToken.subject_id == subject_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .order_by(RefreshToken.created_at, RefreshToken.id)
        )
        return list((await self.session.execute(stmt)).scalars())
