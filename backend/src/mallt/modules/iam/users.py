"""Creating staff users and assigning roles. No authorization here: callers (the staff and
tenancy services) decide who may do what; this only enforces data rules."""

import re
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.errors import Conflict, NotFound, Unprocessable
from mallt.core.rbac import Scope
from mallt.core.security import hash_password
from mallt.modules.iam.models import RoleAssignment, StaffUser
from mallt.modules.iam.repository import IamRepository

USERNAME = re.compile(r"[a-z0-9._-]{3,40}")
MIN_PASSWORD_LENGTH = 10


def normalize_username(raw: str) -> str:
    return raw.strip().lower()


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
