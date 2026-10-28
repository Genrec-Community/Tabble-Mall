import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus, IdentityKind
from mallt.core.rbac import Scope, ScopeType
from mallt.modules.iam.models import (
    Customer,
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

    async def usernames(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        stmt = select(StaffUser.id, StaffUser.username).where(StaffUser.id.in_(ids))
        return {row[0]: row[1] for row in (await self.session.execute(stmt)).all()}

    async def staff_by_ids(self, ids: list[uuid.UUID]) -> list[StaffUser]:
        stmt = select(StaffUser).where(StaffUser.id.in_(ids)).order_by(StaffUser.username)
        return list((await self.session.execute(stmt)).scalars())

    async def staff_ids_at(self, scope: Scope) -> list[uuid.UUID]:
        """Staff holding any role at this scope or beneath it."""
        column = {
            ScopeType.ORGANIZATION: RoleAssignment.organization_id,
            ScopeType.MALL: RoleAssignment.mall_id,
            ScopeType.STORE: RoleAssignment.store_id,
        }[scope.type]
        scope_id = {
            ScopeType.ORGANIZATION: scope.organization_id,
            ScopeType.MALL: scope.mall_id,
            ScopeType.STORE: scope.store_id,
        }[scope.type]
        stmt = select(RoleAssignment.staff_user_id).where(column == scope_id).distinct()
        return list((await self.session.execute(stmt)).scalars())

    async def assignments_for(self, staff_ids: list[uuid.UUID]) -> list[tuple[uuid.UUID, GrantRow]]:
        """(staff_id, assignment) pairs; permissions are left empty (use core.rbac.SYSTEM_ROLES)."""
        stmt = (
            select(
                RoleAssignment.staff_user_id,
                RoleAssignment.id,
                Role.key,
                RoleAssignment.scope_type,
                RoleAssignment.organization_id,
                RoleAssignment.mall_id,
                RoleAssignment.store_id,
            )
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(RoleAssignment.staff_user_id.in_(staff_ids))
            .order_by(RoleAssignment.created_at, RoleAssignment.id)
        )
        return [
            (row[0], GrantRow(row[1], row[2], row[3], row[4], row[5], row[6], frozenset()))
            for row in (await self.session.execute(stmt)).all()
        ]

    async def get_assignment(
        self, staff_id: uuid.UUID, assignment_id: uuid.UUID
    ) -> RoleAssignment | None:
        stmt = select(RoleAssignment).where(
            RoleAssignment.id == assignment_id, RoleAssignment.staff_user_id == staff_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def delete(self, obj: RoleAssignment) -> None:
        await self.session.delete(obj)

    async def count_active_owners(self, org_id: uuid.UUID, excluding: uuid.UUID) -> int:
        # Serialise "is anyone else still an owner?" checks per organization until commit; without
        # this, two owners removing each other at once both see the other and both succeed.
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"last-owner:{org_id}"},
        )
        stmt = (
            select(func.count(func.distinct(RoleAssignment.staff_user_id)))
            .join(Role, Role.id == RoleAssignment.role_id)
            .join(StaffUser, StaffUser.id == RoleAssignment.staff_user_id)
            .where(
                Role.key == "org_owner",
                RoleAssignment.organization_id == org_id,
                StaffUser.status == ActiveStatus.ACTIVE,
                StaffUser.id != excluding,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

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


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, customer: Customer) -> Customer | None:
        """Insert; None means a unique value (phone or Google id) was taken a moment ago."""
        try:
            async with self.session.begin_nested():
                self.session.add(customer)
                await self.session.flush()
        except IntegrityError:
            return None
        return customer

    async def get(self, customer_id: uuid.UUID) -> Customer | None:
        return await self.session.get(Customer, customer_id)

    async def by_phone(self, phone: str) -> Customer | None:
        stmt = select(Customer).where(Customer.phone == phone)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def by_google_sub(self, sub: str) -> Customer | None:
        stmt = select(Customer).where(Customer.google_sub == sub)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def delete(self, customer: Customer) -> None:
        await self.session.delete(customer)
        await self.session.flush()
