import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.rbac import ScopeType
from mallt.modules.iam.models import Role, RoleAssignment, RolePermission, StaffUser


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
