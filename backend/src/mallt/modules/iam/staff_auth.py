import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.core.enums import ActiveStatus, ActorType, IdentityKind
from mallt.core.errors import BadRequest, Conflict, Unauthorized, Unprocessable
from mallt.core.kv import KV
from mallt.core.ratelimit import hit
from mallt.core.rbac import ScopeType
from mallt.core.security import (
    create_access_token,
    hash_password,
    new_totp_secret,
    password_needs_rehash,
    totp_uri,
    verify_password,
    verify_totp,
)
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.iam.models import StaffUser
from mallt.modules.iam.repository import IamRepository
from mallt.modules.iam.schemas import GrantOut, StaffMe
from mallt.modules.iam.sessions import SessionInfo, SessionService, SuspendedOnRefresh
from mallt.modules.iam.users import normalize_username

LOGIN_LIMIT = 10
LOGIN_WINDOW_S = 900


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


@cache
def _dummy_hash() -> str:
    # Verified when the username does not exist, so unknown users cost as much time as known ones.
    return hash_password("dummy-password-for-timing")


class StaffAuthService:
    def __init__(self, session: AsyncSession, settings: Settings, kv: KV) -> None:
        self.settings = settings
        self.kv = kv
        self.repo = IamRepository(session)
        self.sessions = SessionService(session, settings, kv)
        self.authz = AuthzService(session, kv)
        self.audit = AuditService(session)

    def _pair(self, staff_id: uuid.UUID, family_id: uuid.UUID, refresh: str) -> TokenPair:
        access = create_access_token(self.settings, sub=staff_id, typ="staff", sid=family_id)
        return TokenPair(access, refresh, self.settings.access_ttl_s)

    async def login(
        self,
        username: str,
        password: str,
        totp_code: str | None,
        *,
        user_agent: str | None,
        ip: str | None,
    ) -> TokenPair:
        username = normalize_username(username)
        await hit(self.kv, f"staff-login:{username}:{ip}", LOGIN_LIMIT, LOGIN_WINDOW_S)

        staff = await self.repo.get_staff_by_username(username)
        if staff is None:
            verify_password(_dummy_hash(), password)
            raise Unauthorized("invalid_credentials", "Wrong username or password.")
        if not verify_password(staff.password_hash, password):
            raise Unauthorized("invalid_credentials", "Wrong username or password.")
        if staff.status != ActiveStatus.ACTIVE:
            raise Unauthorized("account_suspended", "This account is suspended.")

        if staff.totp_enabled and staff.totp_secret:
            if not totp_code:
                raise Unauthorized("totp_required", "Enter your authenticator code.")
            if not verify_totp(staff.totp_secret, totp_code):
                raise Unauthorized("invalid_totp", "That authenticator code is not valid.")
        elif await self.repo.has_scope_type(staff.id, ScopeType.PLATFORM):
            raise Unauthorized(
                "totp_enrollment_required", "Platform admins must enrol an authenticator first."
            )

        staff.last_login_at = datetime.now(UTC)
        if password_needs_rehash(staff.password_hash):
            staff.password_hash = hash_password(password)
        raw, row = await self.sessions.issue(
            IdentityKind.STAFF, staff.id, user_agent=user_agent, ip=ip
        )
        return self._pair(staff.id, row.family_id, raw)

    async def refresh(self, raw: str, *, user_agent: str | None, ip: str | None) -> TokenPair:
        new_raw, row = await self.sessions.rotate(
            IdentityKind.STAFF, raw, user_agent=user_agent, ip=ip
        )
        staff = await self.repo.get_staff(row.subject_id)
        if staff is None or staff.status != ActiveStatus.ACTIVE:
            await self.sessions.revoke_family(row.family_id)
            raise SuspendedOnRefresh
        return self._pair(staff.id, row.family_id, new_raw)

    async def logout(self, raw: str | None) -> None:
        if raw and (family_id := await self.sessions.family_of(raw)):
            await self.sessions.revoke_family(family_id)

    async def logout_all(self, staff_id: uuid.UUID) -> None:
        await self.sessions.revoke_all(IdentityKind.STAFF, staff_id)

    async def me(self, principal: Principal) -> StaffMe:
        staff = await self._staff(principal.staff_id)
        return StaffMe(
            id=staff.id,
            username=staff.username,
            display_name=staff.display_name,
            must_change_password=staff.must_change_password,
            totp_enabled=staff.totp_enabled,
            grants=[
                GrantOut(
                    role_key=g.role_key,
                    scope_type=g.scope.type,
                    organization_id=g.scope.organization_id,
                    mall_id=g.scope.mall_id,
                    store_id=g.scope.store_id,
                    permissions=sorted(p.value for p in g.permissions),
                )
                for g in principal.grants
            ],
        )

    async def change_password(
        self, principal: Principal, current_family: uuid.UUID, current: str, new: str
    ) -> None:
        staff = await self._staff(principal.staff_id)
        if not verify_password(staff.password_hash, current):
            raise BadRequest("invalid_current_password", "Your current password is wrong.")
        if new == current:
            raise Unprocessable("same_password", "Choose a different password.")
        staff.password_hash = hash_password(new)
        staff.must_change_password = False
        await self.sessions.revoke_all(IdentityKind.STAFF, staff.id, except_family=current_family)
        await self.authz.invalidate(staff.id)
        await self.audit.record(
            actor=Actor(ActorType.STAFF, staff.id),
            action="staff.password_changed",
            target_type="staff_user",
            target_id=staff.id,
            scope=principal.grants[0].scope if principal.grants else None,
        )

    async def totp_setup(self, principal: Principal) -> tuple[str, str]:
        staff = await self._staff(principal.staff_id)
        if staff.totp_enabled:
            raise Conflict("totp_already_enabled", "An authenticator is already enrolled.")
        staff.totp_secret = new_totp_secret()
        return staff.totp_secret, totp_uri(staff.totp_secret, staff.username)

    async def totp_confirm(self, principal: Principal, code: str) -> None:
        staff = await self._staff(principal.staff_id)
        if staff.totp_enabled or not staff.totp_secret:
            raise Conflict("totp_not_pending", "Start authenticator setup first.")
        if not verify_totp(staff.totp_secret, code):
            raise BadRequest("invalid_totp", "That authenticator code is not valid.")
        staff.totp_enabled = True
        await self.audit.record(
            actor=Actor(ActorType.STAFF, staff.id),
            action="staff.totp_enabled",
            target_type="staff_user",
            target_id=staff.id,
            scope=principal.grants[0].scope if principal.grants else None,
        )

    async def list_sessions(self, staff_id: uuid.UUID) -> list[SessionInfo]:
        return await self.sessions.list_active(IdentityKind.STAFF, staff_id)

    async def _staff(self, staff_id: uuid.UUID) -> StaffUser:
        staff = await self.repo.get_staff(staff_id)
        if staff is None:
            raise Unauthorized("invalid_token", "Invalid or expired access token.")
        return staff
