"""Scoped authorization: who may do what, where.

Permissions are resolved per request from role assignments and never trusted from the JWT, so
a revoked role or a suspension takes effect on the very next request.
"""

import json
import uuid
from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.db import defer_after_commit
from mallt.core.enums import ActiveStatus
from mallt.core.errors import Forbidden, NotFound, Unauthorized
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope, ScopeType, contains
from mallt.modules.iam.repository import IamRepository

CACHE_TTL_S = 60


@dataclass(frozen=True)
class Grant:
    role_key: str
    scope: Scope
    permissions: frozenset[P]


@dataclass(frozen=True)
class Principal:
    staff_id: uuid.UUID
    username: str
    must_change_password: bool
    grants: tuple[Grant, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "staff_id": str(self.staff_id),
                "username": self.username,
                "must_change_password": self.must_change_password,
                "grants": [
                    {
                        "role_key": g.role_key,
                        "scope_type": g.scope.type.value,
                        "ids": [
                            str(i) if i else None
                            for i in (g.scope.organization_id, g.scope.mall_id, g.scope.store_id)
                        ],
                        "permissions": sorted(p.value for p in g.permissions),
                    }
                    for g in self.grants
                ],
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "Principal":
        data = json.loads(raw)
        grants = []
        for g in data["grants"]:
            org, mall, store = (uuid.UUID(i) if i else None for i in g["ids"])
            grants.append(
                Grant(
                    g["role_key"],
                    Scope(ScopeType(g["scope_type"]), org, mall, store),
                    frozenset(P(p) for p in g["permissions"]),
                )
            )
        return cls(
            uuid.UUID(data["staff_id"]),
            data["username"],
            data["must_change_password"],
            tuple(grants),
        )


def _cache_key(staff_id: uuid.UUID) -> str:
    return f"authz:staff:{staff_id}"


class AuthzService:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.session = session
        self.repo = IamRepository(session)
        self.kv = kv

    async def load_principal(self, staff_id: uuid.UUID) -> Principal:
        # Cache only when the KV is genuinely fast (Redis); a Postgres-backed KV costs about as
        # much as rebuilding the principal, and would add staleness for nothing.
        if self.kv.fast and (cached := await self.kv.get(_cache_key(staff_id))):
            return Principal.from_json(cached)

        staff = await self.repo.get_staff(staff_id)
        if staff is None:
            raise Unauthorized("invalid_token", "Invalid or expired access token.")
        if staff.status != ActiveStatus.ACTIVE:
            raise Unauthorized("account_suspended", "This account is suspended.")

        grants = []
        for row in await self.repo.grants_for(staff_id):
            known = set()
            for value in row.permissions:
                try:
                    known.add(P(value))
                except ValueError:  # a permission since removed from code; ignore it
                    continue
            scope = Scope(row.scope_type, row.organization_id, row.mall_id, row.store_id)
            grants.append(Grant(row.role_key, scope, frozenset(known)))

        principal = Principal(staff.id, staff.username, staff.must_change_password, tuple(grants))
        if self.kv.fast:
            await self.kv.set(_cache_key(staff_id), principal.to_json(), CACHE_TTL_S)
        return principal

    @staticmethod
    def can(principal: Principal, permission: P, target: Scope) -> bool:
        return any(
            permission in g.permissions and contains(g.scope, target) for g in principal.grants
        )

    def require(self, principal: Principal, permission: P, target: Scope) -> None:
        """Raise unless allowed. Resources in a tenant the principal cannot see are 404, so their
        existence is not revealed; a missing permission inside a visible tenant is 403."""
        if self.can(principal, permission, target):
            return
        if target.type == ScopeType.PLATFORM or self._shares_org(principal, target):
            raise Forbidden("missing_permission", "You do not have permission to do this.")
        raise NotFound("not_found", "Not found.")

    @staticmethod
    def _shares_org(principal: Principal, target: Scope) -> bool:
        return any(
            g.scope.type == ScopeType.PLATFORM or g.scope.organization_id == target.organization_id
            for g in principal.grants
        )

    @staticmethod
    def can_see(principal: Principal, target: Scope) -> bool:
        """Read visibility: platform staff see everything; others see scopes on their own chain
        (an ancestor of a grant, or anything beneath one)."""
        if target.type == ScopeType.PLATFORM:
            # The platform scope contains every tenant, so "contained by" would make it visible to
            # everyone; only platform staff may know what lives there.
            return any(g.scope.type == ScopeType.PLATFORM for g in principal.grants)
        return any(
            g.scope.type == ScopeType.PLATFORM
            or contains(g.scope, target)
            or contains(target, g.scope)
            for g in principal.grants
        )

    def require_visible(self, principal: Principal, target: Scope) -> None:
        if not self.can_see(principal, target):
            raise NotFound("not_found", "Not found.")

    @staticmethod
    def visible_org_ids(principal: Principal) -> set[uuid.UUID] | None:
        """None means every organization (platform-level access)."""
        if any(g.scope.type == ScopeType.PLATFORM for g in principal.grants):
            return None
        return {g.scope.organization_id for g in principal.grants if g.scope.organization_id}

    async def invalidate(self, staff_id: uuid.UUID) -> None:
        """Forget the cached principal now, and again once the change that prompted this commits
        (a request racing the change could otherwise re-cache the old permissions)."""
        key = _cache_key(staff_id)
        await self.kv.delete(key)
        defer_after_commit(self.session, partial(self.kv.delete, key))
