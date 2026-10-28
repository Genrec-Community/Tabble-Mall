import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.core.enums import ActiveStatus, ActorType, IdentityKind
from mallt.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from mallt.core.kv import KV
from mallt.core.rbac import (
    GRANT_RULES,
    STAFF_MANAGE_FOR,
    SYSTEM_ROLES,
    P,
    RoleDef,
    Scope,
    ScopeType,
    contains,
)
from mallt.core.security import new_temp_password
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.iam.sessions import SessionService
from mallt.modules.iam.users import AssignmentInfo, IamUsers, StaffRecord
from mallt.modules.staff.schemas import RoleAssign, StaffCreate
from mallt.modules.tenancy.service import TenancyService


class StaffService:
    """Who may create, change and remove whom.

    The one principle behind every rule: you can manage a person only if you could have granted
    each of their roles yourself (see GRANT_RULES). It stops privilege escalation, and it stops
    a lower role from touching a higher one.
    """

    def __init__(self, session: AsyncSession, settings: Settings, kv: KV) -> None:
        self.users = IamUsers(session)
        self.authz = AuthzService(session, kv)
        self.tenancy = TenancyService(session, kv)
        self.sessions = SessionService(session, settings, kv)
        self.audit = AuditService(session)

    # ---- helpers ----

    async def _scope(self, scope_type: ScopeType, scope_id: uuid.UUID | None) -> Scope:
        match scope_type:
            case ScopeType.PLATFORM:
                if scope_id is not None:
                    raise Unprocessable("bad_scope", "Platform scope takes no id.")
                return Scope.platform()
            case _ if scope_id is None:
                raise Unprocessable("bad_scope", "scope_id is required.")
            case ScopeType.ORGANIZATION:
                return await self.tenancy.scope_for_org(scope_id)
            case ScopeType.MALL:
                return await self.tenancy.scope_for_mall(scope_id)
            case ScopeType.STORE:
                return await self.tenancy.scope_for_store(scope_id)

    def _could_grant(self, principal: Principal, role_key: str, scope: Scope) -> bool:
        role = SYSTEM_ROLES[role_key]
        granters = GRANT_RULES[role_key]
        return any(
            g.role_key in granters and contains(g.scope, scope) for g in principal.grants
        ) and all(self.authz.can(principal, perm, scope) for perm in role.permissions)

    def _check_can_grant(self, principal: Principal, role_key: str, target: Scope) -> None:
        role = SYSTEM_ROLES.get(role_key)
        if role is None:
            raise Unprocessable("unknown_role", "No such role.")
        if role.scope_type != target.type:
            raise Unprocessable("wrong_scope", f"{role.name} applies at {role.scope_type} level.")
        self.authz.require(principal, STAFF_MANAGE_FOR[target.type], target)
        if not self._could_grant(principal, role_key, target):
            raise Forbidden("cannot_grant_role", f"You cannot hand out the {role.name} role.")

    async def _managed(self, principal: Principal, staff_id: uuid.UUID) -> StaffRecord:
        """Load a staff member the caller is allowed to act on (never themselves)."""
        record = await self.users.record_for(staff_id)
        if record is None:
            raise NotFound("not_found", "Not found.")
        if record.id == principal.staff_id:
            raise Conflict("self_action", "You cannot do this to your own account.")
        if not record.assignments:  # nobody's staff right now: only the platform may touch them
            if self.authz.visible_org_ids(principal) is not None:
                raise NotFound("not_found", "Not found.")
            return record
        if not any(self.authz.can_see(principal, a.scope) for a in record.assignments):
            raise NotFound("not_found", "Not found.")
        for a in record.assignments:
            may_manage = self.authz.can(principal, STAFF_MANAGE_FOR[a.scope.type], a.scope)
            if not (may_manage and self._could_grant(principal, a.role_key, a.scope)):
                raise Forbidden("cannot_manage_staff", "You cannot manage this person.")
        return record

    async def _guard_last_owner(
        self, record: StaffRecord, assignments: list[AssignmentInfo]
    ) -> None:
        if record.status != ActiveStatus.ACTIVE:
            return  # a suspended owner is not counted as an owner anyway
        for a in assignments:
            if a.role_key == "org_owner" and a.scope.organization_id:
                others = await self.users.other_active_owners(a.scope.organization_id, record.id)
                if others == 0:
                    raise Conflict("last_owner", "An organization must keep at least one owner.")

    async def _log(
        self,
        principal: Principal,
        action: str,
        target_id: uuid.UUID,
        scope: Scope,
        *,
        before: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
    ) -> None:
        await self.audit.record(
            actor=Actor(ActorType.STAFF, principal.staff_id),
            action=action,
            target_type="staff_user",
            target_id=target_id,
            scope=scope,
            before=before,
            after=after,
        )

    @staticmethod
    def _scope_of(record: StaffRecord) -> Scope:
        return record.assignments[0].scope if record.assignments else Scope.platform()

    async def _refreshed(self, staff_id: uuid.UUID) -> StaffRecord:
        record = await self.users.record_for(staff_id)
        if record is None:
            raise NotFound("not_found", "Not found.")
        return record

    # ---- operations ----

    @staticmethod
    def roles() -> list[RoleDef]:
        return list(SYSTEM_ROLES.values())

    async def list_staff(
        self, principal: Principal, scope_type: ScopeType, scope_id: uuid.UUID
    ) -> list[StaffRecord]:
        scope = await self._scope(scope_type, scope_id)
        if not self.authz.can(principal, P.AUDIT_READ, scope):
            self.authz.require(principal, STAFF_MANAGE_FOR[scope.type], scope)
        records = await self.users.list_at(scope)
        # Show each person only the roles the caller is allowed to see.
        return [
            StaffRecord(
                **{
                    **r.__dict__,
                    "assignments": tuple(
                        a for a in r.assignments if self.authz.can_see(principal, a.scope)
                    ),
                }
            )
            for r in records
        ]

    async def create_staff(
        self,
        principal: Principal,
        scope_type: ScopeType,
        scope_id: uuid.UUID,
        data: StaffCreate,
    ) -> tuple[StaffRecord, str]:
        target = await self._scope(scope_type, scope_id)
        self._check_can_grant(principal, data.role_key, target)
        await self.tenancy.assert_operational(principal, target)
        temp_password = new_temp_password()
        user = await self.users.create_staff_user(
            username=data.username,
            display_name=data.display_name,
            email=data.email,
            password=temp_password,
            must_change_password=True,
        )
        await self.users.assign_role(user.id, data.role_key, target, granted_by=principal.staff_id)
        await self._log(
            principal,
            "staff.created",
            user.id,
            target,
            after={"username": user.username, "role": data.role_key},
        )
        return await self._refreshed(user.id), temp_password

    async def assign_role(
        self, principal: Principal, staff_id: uuid.UUID, data: RoleAssign
    ) -> AssignmentInfo:
        target = await self._scope(data.scope_type, data.scope_id)
        record = await self._managed(principal, staff_id)
        self._check_can_grant(principal, data.role_key, target)
        role = SYSTEM_ROLES[data.role_key]
        if role.scope_type == ScopeType.PLATFORM and not record.totp_enabled:
            # Platform admins cannot sign in without TOTP, and enrolling needs a signed-in session.
            raise Conflict(
                "totp_required_first",
                "They must set up an authenticator app before becoming a platform admin.",
            )
        await self.tenancy.assert_operational(principal, target)
        row = await self.users.assign_role(
            record.id, data.role_key, target, granted_by=principal.staff_id
        )
        await self.authz.invalidate(record.id)
        await self._log(
            principal, "staff.role_granted", record.id, target, after={"role": data.role_key}
        )
        return AssignmentInfo(row.id, data.role_key, target)

    async def revoke_role(
        self, principal: Principal, staff_id: uuid.UUID, assignment_id: uuid.UUID
    ) -> None:
        record = await self._managed(principal, staff_id)
        assignment = next((a for a in record.assignments if a.id == assignment_id), None)
        if assignment is None:
            raise NotFound("not_found", "Not found.")
        await self.tenancy.assert_operational(principal, assignment.scope)
        await self._guard_last_owner(record, [assignment])
        await self.users.revoke_assignment(record.id, assignment.id)
        await self.authz.invalidate(record.id)
        await self._log(
            principal,
            "staff.role_revoked",
            record.id,
            assignment.scope,
            before={"role": assignment.role_key},
        )

    async def set_status(
        self, principal: Principal, staff_id: uuid.UUID, status: ActiveStatus
    ) -> StaffRecord:
        record = await self._managed(principal, staff_id)
        if record.status == status:
            return record
        await self.tenancy.assert_operational(principal, self._scope_of(record))
        if status == ActiveStatus.SUSPENDED:
            await self._guard_last_owner(record, list(record.assignments))
        await self.users.set_status(record.id, status)
        if status == ActiveStatus.SUSPENDED:
            await self.sessions.revoke_all(IdentityKind.STAFF, record.id)
        await self.authz.invalidate(record.id)
        verb = "suspended" if status == ActiveStatus.SUSPENDED else "activated"
        await self._log(
            principal,
            f"staff.{verb}",
            record.id,
            self._scope_of(record),
            before={"status": record.status.value},
            after={"status": status.value},
        )
        return await self._refreshed(record.id)

    async def reset_password(self, principal: Principal, staff_id: uuid.UUID) -> str:
        record = await self._managed(principal, staff_id)
        await self.tenancy.assert_operational(principal, self._scope_of(record))
        temp_password = new_temp_password()
        await self.users.set_temp_password(record.id, temp_password)
        await self.sessions.revoke_all(IdentityKind.STAFF, record.id)
        await self.authz.invalidate(record.id)
        await self._log(principal, "staff.password_reset", record.id, self._scope_of(record))
        return temp_password
