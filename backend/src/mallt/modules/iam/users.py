"""Creating staff users and assigning roles. No authorization here: callers (the staff and
tenancy services) decide who may do what; this only enforces data rules."""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus
from mallt.core.errors import Conflict, NotFound, Unprocessable
from mallt.core.rbac import Scope
from mallt.core.security import hash_password
from mallt.modules.iam.models import RoleAssignment, StaffUser
from mallt.modules.iam.repository import GrantRow, IamRepository

USERNAME = re.compile(r"[a-z0-9._-]{3,40}")
MIN_PASSWORD_LENGTH = 10


def normalize_username(raw: str) -> str:
    return raw.strip().lower()


@dataclass(frozen=True)
class AssignmentInfo:
    id: uuid.UUID
    role_key: str
    scope: Scope


@dataclass(frozen=True)
class StaffRecord:
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    status: ActiveStatus
    must_change_password: bool
    totp_enabled: bool
    last_login_at: datetime | None
    assignments: tuple[AssignmentInfo, ...]


def _assignment(row: GrantRow) -> AssignmentInfo:
    scope = Scope(row.scope_type, row.organization_id, row.mall_id, row.store_id)
    return AssignmentInfo(row.assignment_id, row.role_key, scope)


class IamUsers:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = IamRepository(session)

    async def create_staff_user(
        self,
        *,
        username: str,
        display_name: str,
        email: str | None,
        password: str,
        must_change_password: bool = True,
    ) -> StaffUser:
        username = normalize_username(username)
        if not USERNAME.fullmatch(username):
            raise Unprocessable(
                "invalid_username", "Use 3-40 letters, digits, dots, dashes or underscores."
            )
        if len(password) < MIN_PASSWORD_LENGTH:
            raise Unprocessable(
                "weak_password", f"Passwords need at least {MIN_PASSWORD_LENGTH} characters."
            )
        staff = StaffUser(
            username=username,
            display_name=display_name.strip(),
            email=email,
            password_hash=hash_password(password),
            must_change_password=must_change_password,
        )
        try:
            async with (
                self.session.begin_nested()
            ):  # a savepoint, so a clash leaves the rest intact
                self.repo.add(staff)
                await self.session.flush()
        except IntegrityError as exc:
            raise Conflict("username_taken", "That username is already in use.") from exc
        return staff

    async def assign_role(
        self,
        staff_id: uuid.UUID,
        role_key: str,
        scope: Scope,
        *,
        granted_by: uuid.UUID | None,
    ) -> RoleAssignment:
        role = await self.repo.get_role_by_key(role_key)
        if role is None:
            raise NotFound("role_not_found", "Unknown role.")
        if role.scope_type != scope.type:
            raise Unprocessable("wrong_scope", f"{role.name} applies at {role.scope_type} level.")
        assignment = RoleAssignment(
            staff_user_id=staff_id,
            role_id=role.id,
            scope_type=scope.type,
            organization_id=scope.organization_id,
            mall_id=scope.mall_id,
            store_id=scope.store_id,
            granted_by=granted_by,
        )
        try:
            async with self.session.begin_nested():
                self.repo.add(assignment)
                await self.session.flush()
        except IntegrityError as exc:
            raise Conflict("role_already_assigned", "They already have this role here.") from exc
        return assignment

    # ---- directory (read) ----

    async def _records(self, staff: list[StaffUser]) -> list[StaffRecord]:
        if not staff:
            return []
        by_staff: dict[uuid.UUID, list[AssignmentInfo]] = {}
        for staff_id, row in await self.repo.assignments_for([u.id for u in staff]):
            by_staff.setdefault(staff_id, []).append(_assignment(row))
        return [
            StaffRecord(
                id=u.id,
                username=u.username,
                display_name=u.display_name,
                email=u.email,
                status=u.status,
                must_change_password=u.must_change_password,
                totp_enabled=u.totp_enabled,
                last_login_at=u.last_login_at,
                assignments=tuple(by_staff.get(u.id, [])),
            )
            for u in staff
        ]

    async def record_for(self, staff_id: uuid.UUID) -> StaffRecord | None:
        staff = await self.repo.get_staff(staff_id)
        return (await self._records([staff]))[0] if staff else None

    async def list_at(self, scope: Scope) -> list[StaffRecord]:
        """Staff holding any role at ``scope`` or beneath it, with all their assignments."""
        ids = await self.repo.staff_ids_at(scope)
        return await self._records(await self.repo.staff_by_ids(ids)) if ids else []

    async def other_active_owners(self, org_id: uuid.UUID, excluding: uuid.UUID) -> int:
        return await self.repo.count_active_owners(org_id, excluding)

    # ---- changes ----

    async def _staff(self, staff_id: uuid.UUID) -> StaffUser:
        staff = await self.repo.get_staff(staff_id)
        if staff is None:
            raise NotFound("not_found", "Not found.")
        return staff

    async def set_status(self, staff_id: uuid.UUID, status: ActiveStatus) -> None:
        (await self._staff(staff_id)).status = status

    async def set_temp_password(self, staff_id: uuid.UUID, password: str) -> None:
        staff = await self._staff(staff_id)
        staff.password_hash = hash_password(password)
        staff.must_change_password = True

    async def revoke_assignment(self, staff_id: uuid.UUID, assignment_id: uuid.UUID) -> None:
        row = await self.repo.get_assignment(staff_id, assignment_id)
        if row is None:
            raise NotFound("not_found", "Not found.")
        await self.repo.delete(row)
        await self.session.flush()
